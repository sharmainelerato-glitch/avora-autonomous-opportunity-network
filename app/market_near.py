"""AVORA NEAR-only direct product orders, buyer-consented testnet settlement.

IMPORTANT: USD prices are illustrative and NOT converted to NEAR.
Sellers explicitly set a separate testnet NEAR amount for each product.
No private keys, automatic transfers, custody, shipping, or fiat conversion.
"""
from __future__ import annotations
import os,re,time
from decimal import Decimal,InvalidOperation
from typing import Optional
import httpx
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field

from app.near_workflows import NEAR_ACCOUNT,TX_HASH,YOCTO,amount_yocto

RPC=os.getenv('NEAR_TESTNET_RPC','https://rpc.testnet.near.org')

class PayoutConfig(BaseModel):
    account:str=Field(min_length=8,max_length=64)
class PriceConfig(BaseModel):
    amount_near:str=Field(min_length=1,max_length=40)
class Line(BaseModel):
    listing_id:int=Field(gt=0)
    quantity:int=Field(ge=1,le=10)
class Checkout(BaseModel):
    lines:list[Line]=Field(min_length=1,max_length=20)
    note:str=Field(default='',max_length=400)
class FulfillmentUpdate(BaseModel):
    note:str=Field(default='',max_length=500)

class IssueReport(BaseModel):
    message:str=Field(min_length=10,max_length=1000)

class Proof(BaseModel):
    tx_hash:str=Field(min_length=40,max_length=48)
    signer_account_id:str=Field(min_length=4,max_length=64)


def install(app,conn,current):
    with conn() as db:
        db.executescript("""
CREATE TABLE IF NOT EXISTS market_near_payouts(provider_id INTEGER PRIMARY KEY REFERENCES providers(id),account TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS market_near_prices(listing_id INTEGER PRIMARY KEY REFERENCES listings(id),amount_yocto TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS market_near_orders(order_id INTEGER PRIMARY KEY REFERENCES marketplace_orders(id),
 recipient TEXT NOT NULL,amount_yocto TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'REVIEW',
 tx_hash TEXT UNIQUE,signer TEXT,approved_at INTEGER,verified_at INTEGER,created INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS market_near_orders_status_idx ON market_near_orders(status);
CREATE TABLE IF NOT EXISTS market_near_fulfillment(
 order_id INTEGER PRIMARY KEY REFERENCES marketplace_orders(id),
 status TEXT NOT NULL DEFAULT 'PENDING_PAYMENT',
 note TEXT NOT NULL DEFAULT '',updated INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS market_near_issues(
 id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES marketplace_orders(id),
 buyer_id INTEGER NOT NULL REFERENCES users(id),message TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'OPEN',created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS market_near_events(
 id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES marketplace_orders(id),
 event TEXT NOT NULL,actor_id INTEGER NOT NULL REFERENCES users(id),
 detail TEXT NOT NULL DEFAULT '',created INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS market_near_events_order_idx ON market_near_events(order_id);
""")
    router=APIRouter(prefix='/api/marketplace/near')
    def own(db,pid,uid):
        p=db.execute('SELECT id FROM providers WHERE id=? AND owner_id=?',(pid,uid)).fetchone()
        if not p:raise HTTPException(403,'Only the registered seller can set payment terms')
    def checkout_quote(db,lines,uid):
        if not lines:raise HTTPException(422,'Bag is empty')
        pid=None;payee=None;total=0;usd=0;products=[];seen=set()
        for line in lines:
            if line.listing_id in seen:raise HTTPException(422,'Duplicate listing')
            seen.add(line.listing_id)
            item=db.execute("""SELECT l.id,l.provider_id,l.title,l.kind,l.price,l.stock,p.owner_id,
                       nw.account recipient, np.amount_yocto unit_yocto FROM listings l
                       JOIN providers p ON p.id=l.provider_id
                       LEFT JOIN market_near_payouts nw ON nw.provider_id=p.id
                       LEFT JOIN market_near_prices np ON np.listing_id=l.id WHERE l.id=?""",(line.listing_id,)).fetchone()
            if not item:raise HTTPException(404,'Product not found')
            if item['owner_id'] is None:raise HTTPException(422,'Sample providers cannot receive NEAR payments')
            if item['owner_id']==uid:raise HTTPException(403,'Cannot buy from your own store')
            if item['kind']!='Products':raise HTTPException(422,'Only products can use bag checkout; use service enquiries for services')
            if not item['recipient'] or not item['unit_yocto']:raise HTTPException(422,'Seller has not enabled NEAR checkout for every selected product')
            if item['stock']<line.quantity:raise HTTPException(409,'Insufficient inventory for '+item['title'])
            if pid is None:pid=item['provider_id'];payee=item['recipient']
            if item['provider_id']!=pid:raise HTTPException(422,'Complete one seller at a time')
            total+=int(item['unit_yocto'])*line.quantity
            usd+=item['price']*line.quantity
            products.append({'listing_id':line.listing_id,'title':item['title'],'quantity':line.quantity,'unit_usd_example':item['price'],'unit_near':str(Decimal(item['unit_yocto'])/YOCTO)})
        if total>YOCTO:raise HTTPException(422,'Maximum test checkout is 1 NEAR; use a smaller bag')
        return {'provider_id':pid,'recipient':payee,'amount_near':str(Decimal(total)/YOCTO),
                'amount_yocto':str(total),'example_usd':usd,'items':products,'network':'testnet',
                'notice':'NEAR prices are seller-set testnet amounts, not USD conversions. No funds move until you sign.'}
    @router.put('/providers/{pid}/payout')
    def set_payout(pid:int,body:PayoutConfig,u=Depends(current)):
        if not NEAR_ACCOUNT.fullmatch(body.account):raise HTTPException(422,'Use a valid NEAR .testnet receiving account')
        with conn() as db:
            own(db,pid,u['id'])
            db.execute('INSERT INTO market_near_payouts(provider_id,account) VALUES(?,?) ON CONFLICT(provider_id) DO UPDATE SET account=excluded.account',(pid,body.account))
        return {'saved':True,'account':body.account,'network':'testnet'}
    @router.put('/providers/{pid}/listings/{lid}/price')
    def set_price(pid:int,lid:int,body:PriceConfig,u=Depends(current)):
        yocto=amount_yocto(body.amount_near)
        with conn() as db:
            own(db,pid,u['id'])
            item=db.execute('SELECT kind FROM listings WHERE id=? AND provider_id=?',(lid,pid)).fetchone()
            if not item:raise HTTPException(404,'Product not found')
            if item['kind']!='Products':raise HTTPException(422,'Direct bag payment is only for products')
            db.execute('INSERT INTO market_near_prices(listing_id,amount_yocto) VALUES(?,?) ON CONFLICT(listing_id) DO UPDATE SET amount_yocto=excluded.amount_yocto',(lid,yocto))
        return {'saved':True,'amount_near':str(Decimal(yocto)/YOCTO)}
    @router.get('/providers/{pid}/settings')
    def settings(pid:int,u=Depends(current)):
        with conn() as db:
            own(db,pid,u['id'])
            account=db.execute('SELECT account FROM market_near_payouts WHERE provider_id=?',(pid,)).fetchone()
            prices=db.execute("""SELECT mp.listing_id,mp.amount_yocto,l.title FROM market_near_prices mp JOIN listings l ON l.id=mp.listing_id WHERE l.provider_id=?""",(pid,)).fetchall()
            return {'account':account['account'] if account else '', 'prices':[{'listing_id':x['listing_id'],'title':x['title'],'amount_near':str(Decimal(x['amount_yocto'])/YOCTO)} for x in prices]}
    @router.post('/preview')
    def preview(body:Checkout,u=Depends(current)):
        with conn() as db:return checkout_quote(db,body.lines,u['id'])
    @router.post('/orders')
    def create_order(body:Checkout,u=Depends(current)):
        with conn() as db:
            q=checkout_quote(db,body.lines,u['id'])
            ts=int(time.time())
            oid=db.execute('INSERT INTO marketplace_orders(buyer_id,provider_id,status,total_usd,note,created) VALUES(?,?,?,?,?,?)',
                (u['id'],q['provider_id'],'NEAR_REVIEW',q['example_usd'],body.note,ts)).lastrowid
            for item in q['items']:
                db.execute('INSERT INTO marketplace_order_lines(order_id,listing_id,title,unit_price_usd,quantity) VALUES(?,?,?,?,?)',
                    (oid,item['listing_id'],item['title'],item['unit_usd_example'],item['quantity']))
            db.execute('INSERT INTO market_near_orders(order_id,recipient,amount_yocto,status,created) VALUES(?,?,?,?,?)',
                (oid,q['recipient'],q['amount_yocto'],'REVIEW',ts))
            db.execute('INSERT INTO market_near_fulfillment(order_id,status,updated) VALUES(?,?,?)', (oid,'PENDING_PAYMENT',ts))
            db.execute('INSERT INTO market_near_events(order_id,event,actor_id,created) VALUES(?,?,?,?)',(oid,'CREATED',u['id'],ts))
            return {'order_id':oid,'status':'NEAR_REVIEW',**q}
    def get_order(db,oid,uid):
        record=db.execute("""SELECT o.*,mn.recipient,mn.amount_yocto,mn.status payment_status,mn.tx_hash,mn.signer,mn.verified_at,mn.approved_at,
          p.name provider_name,p.owner_id FROM marketplace_orders o JOIN market_near_orders mn ON o.id=mn.order_id
          JOIN providers p ON p.id=o.provider_id WHERE o.id=?""",(oid,)).fetchone()
        if not record:raise HTTPException(404,'NEAR order not found')
        if uid not in (record['buyer_id'],record['owner_id']):raise HTTPException(403,'This order is private')
        return record
    def details(db,rec):
        result=dict(rec)
        result['amount_near']=str(Decimal(result.pop('amount_yocto'))/YOCTO)
        result['items']=[dict(x) for x in db.execute('SELECT title,quantity,unit_price_usd,listing_id FROM marketplace_order_lines WHERE order_id=?',(rec['id'],))]
        result['network']='testnet'
        result['explorer_url']='https://testnet.nearblocks.io/txns/'+rec['tx_hash'] if rec['tx_hash'] else None
        fulfillment=db.execute('SELECT status,note,updated FROM market_near_fulfillment WHERE order_id=?',(rec['id'],)).fetchone()
        result['fulfillment']=dict(fulfillment) if fulfillment else {'status':'PENDING_PAYMENT','note':'','updated':0}
        result['events']=[dict(x) for x in db.execute('SELECT event,detail,created FROM market_near_events WHERE order_id=? ORDER BY id',(rec['id'],))]
        issue=db.execute('SELECT id,status,message,created FROM market_near_issues WHERE order_id=? ORDER BY id DESC LIMIT 1',(rec['id'],)).fetchone()
        result['issue']=dict(issue) if issue else None
        result['seller_user_id']=result.pop('owner_id',None)
        return result
    @router.get('/orders/{oid}')
    def get_details(oid:int,u=Depends(current)):
        with conn() as db:return details(db,get_order(db,oid,u['id']))
    @router.post('/orders/{oid}/approve')
    def approve(oid:int,u=Depends(current)):
        with conn() as db:
            rec=get_order(db,oid,u['id'])
            if rec['buyer_id']!=u['id']:raise HTTPException(403,'Only the buyer approves payment')
            if rec['payment_status']!='REVIEW':raise HTTPException(409,'Order no longer awaiting approval')
            db.execute("UPDATE market_near_orders SET status='APPROVED',approved_at=? WHERE order_id=?",(int(time.time()),oid))
            db.execute("UPDATE marketplace_orders SET status='NEAR_AWAITING_TRANSFER' WHERE id=?",(oid,))
            db.execute('INSERT INTO market_near_events(order_id,event,actor_id,created) VALUES(?,?,?,?)',(oid,'APPROVED',u['id'],int(time.time())))
            return details(db,get_order(db,oid,u['id']))
    @router.post('/orders/{oid}/verify')
    async def verify(oid:int,body:Proof,u=Depends(current)):
        if not TX_HASH.fullmatch(body.tx_hash):raise HTTPException(422,'Invalid NEAR transaction hash')
        if not NEAR_ACCOUNT.fullmatch(body.signer_account_id):raise HTTPException(422,'Sender must be a testnet account')
        with conn() as db:
            rec=get_order(db,oid,u['id'])
            if rec['buyer_id']!=u['id']:raise HTTPException(403,'Only the buyer submits payment evidence')
            if rec['payment_status']!='APPROVED':raise HTTPException(409,'Buyer approval required or payment is already verified')
            expected=rec['amount_yocto'];recipient=rec['recipient']
            if db.execute('SELECT 1 FROM market_near_orders WHERE tx_hash=?',(body.tx_hash,)).fetchone() or db.execute('SELECT 1 FROM near_proofs WHERE tx_hash=?',(body.tx_hash,)).fetchone():
                raise HTTPException(409,'NEAR transaction hash has already been used')
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response=await client.post(RPC,json={'jsonrpc':'2.0','id':'avora-market-near','method':'tx',
                    'params':{'tx_hash':body.tx_hash,'sender_account_id':body.signer_account_id,'wait_until':'FINAL'}})
                response.raise_for_status();data=response.json()
            except (httpx.HTTPError,ValueError):raise HTTPException(503,'NEAR RPC temporarily unavailable; try verification again')
        if data.get('error'):raise HTTPException(422,'NEAR did not confirm the supplied hash')
        result=data.get('result') or {};tx=result.get('transaction') or {};status=result.get('status') or {}
        if tx.get('hash')!=body.tx_hash or tx.get('signer_id')!=body.signer_account_id or tx.get('receiver_id')!=recipient:
            raise HTTPException(422,'Transaction signer, recipient or hash does not match approved checkout')
        transfers=[a['Transfer'].get('deposit') for a in tx.get('actions',[]) if isinstance(a,dict) and isinstance(a.get('Transfer'),dict)]
        if transfers!=[expected]:raise HTTPException(422,'On-chain NEAR transfer amount does not match approved checkout')
        if result.get('final_execution_status')!='FINAL' or not isinstance(status,dict) or not ('SuccessValue' in status or 'SuccessReceiptId' in status) or not (result.get('transaction_outcome') or {}).get('outcome'):
            raise HTTPException(422,'NEAR transaction is not yet finalized successfully')
        with conn() as db:
            latest=get_order(db,oid,u['id'])
            if latest['payment_status']!='APPROVED' or latest['recipient']!=recipient or latest['amount_yocto']!=expected:
                raise HTTPException(409,'Payment terms have changed; no receipt recorded')
            if db.execute('SELECT 1 FROM market_near_orders WHERE tx_hash=?',(body.tx_hash,)).fetchone() or db.execute('SELECT 1 FROM near_proofs WHERE tx_hash=?',(body.tx_hash,)).fetchone():
                raise HTTPException(409,'NEAR transaction already claimed')
            db.execute("UPDATE market_near_orders SET status='VERIFIED',tx_hash=?,signer=?,verified_at=? WHERE order_id=? AND status='APPROVED'",
                (body.tx_hash,body.signer_account_id,int(time.time()),oid))
            db.execute("UPDATE marketplace_orders SET status='NEAR_VERIFIED' WHERE id=?",(oid,))
            # Chain settlement is authoritative. If stock changed after checkout,
            # keep the payment verified but flag seller resolution rather than hide a paid order.
            lines=db.execute('SELECT listing_id,quantity FROM marketplace_order_lines WHERE order_id=?',(oid,)).fetchall()
            stock_ok=True
            for line in lines:
                available=db.execute('SELECT stock FROM listings WHERE id=?',(line['listing_id'],)).fetchone()
                if not available or available['stock']<line['quantity']: stock_ok=False
            if stock_ok:
                for line in lines:
                    db.execute('UPDATE listings SET stock=stock-? WHERE id=?',(line['quantity'],line['listing_id']))
            fulfillment='AWAITING_FULFILLMENT' if stock_ok else 'SELLER_REVIEW_REQUIRED'
            db.execute('INSERT INTO market_near_fulfillment(order_id,status,updated) VALUES(?,?,?) ON CONFLICT(order_id) DO UPDATE SET status=excluded.status,updated=excluded.updated',(oid,fulfillment,int(time.time())))
            db.execute('INSERT INTO market_near_events(order_id,event,actor_id,detail,created) VALUES(?,?,?,?,?)',(oid,'VERIFIED',u['id'],body.tx_hash,int(time.time())))
            if not stock_ok:
                db.execute('INSERT INTO market_near_events(order_id,event,actor_id,detail,created) VALUES(?,?,?,?,?)',(oid,'STOCK_ATTENTION',u['id'],'Availability changed after order creation',int(time.time())))
            return details(db,get_order(db,oid,u['id']))
    @router.post('/orders/{oid}/cancel')
    def cancel_unapproved(oid:int,u=Depends(current)):
        with conn() as db:
            rec=get_order(db,oid,u['id'])
            if rec['buyer_id']!=u['id']:raise HTTPException(403,'Only the buyer can cancel')
            if rec['payment_status']!='REVIEW':
                raise HTTPException(409,'Only orders not yet approved for payment may be cancelled')
            db.execute("UPDATE market_near_orders SET status='CANCELLED' WHERE order_id=? AND status='REVIEW'",(oid,))
            db.execute("UPDATE marketplace_orders SET status='NEAR_CANCELLED' WHERE id=?",(oid,))
            db.execute("UPDATE market_near_fulfillment SET status='CANCELLED',updated=? WHERE order_id=?",(int(time.time()),oid))
            db.execute('INSERT INTO market_near_events(order_id,event,actor_id,created) VALUES(?,?,?,?)',(oid,'CANCELLED',u['id'],int(time.time())))
            return details(db,get_order(db,oid,u['id']))

    @router.post('/orders/{oid}/fulfill')
    def fulfill(oid:int,body:FulfillmentUpdate,u=Depends(current)):
        with conn() as db:
            rec=get_order(db,oid,u['id'])
            if rec['owner_id']!=u['id']:raise HTTPException(403,'Only the selling provider can mark an order fulfilled')
            if rec['payment_status']!='VERIFIED':raise HTTPException(409,'On-chain payment must be verified first')
            current_status=db.execute('SELECT status FROM market_near_fulfillment WHERE order_id=?',(oid,)).fetchone()
            if current_status and current_status['status']=='FULFILLED':raise HTTPException(409,'Order already fulfilled')
            db.execute('INSERT INTO market_near_fulfillment(order_id,status,note,updated) VALUES(?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET status=excluded.status,note=excluded.note,updated=excluded.updated',(oid,'FULFILLED',body.note,int(time.time())))
            db.execute('INSERT INTO market_near_events(order_id,event,actor_id,detail,created) VALUES(?,?,?,?,?)',(oid,'FULFILLED',u['id'],body.note,int(time.time())))
            return details(db,get_order(db,oid,u['id']))

    @router.post('/orders/{oid}/issue')
    def report_issue(oid:int,body:IssueReport,u=Depends(current)):
        with conn() as db:
            rec=get_order(db,oid,u['id'])
            if rec['buyer_id']!=u['id']:raise HTTPException(403,'Only the buyer can report a purchase issue')
            if rec['payment_status']!='VERIFIED':raise HTTPException(409,'Only verified paid orders can be reported here')
            existing=db.execute("SELECT id FROM market_near_issues WHERE order_id=? AND status='OPEN'",(oid,)).fetchone()
            if existing:raise HTTPException(409,'There is already an open issue for this order')
            db.execute('INSERT INTO market_near_issues(order_id,buyer_id,message,created) VALUES(?,?,?,?)',(oid,u['id'],body.message,int(time.time())))
            db.execute('INSERT INTO market_near_events(order_id,event,actor_id,created) VALUES(?,?,?,?)',(oid,'ISSUE_REPORTED',u['id'],int(time.time())))
            return details(db,get_order(db,oid,u['id']))

    app.include_router(router)
