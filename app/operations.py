"""AVORA local prototype operations: bookings, manual delivery status, refund requests and inbox.
No external courier integration, identity verification, automatic refunds or blockchain signing.
"""
from __future__ import annotations
import time,os,re,html
from datetime import datetime, timezone
from decimal import Decimal
import httpx
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import Response
from app.near_workflows import TX_HASH,NEAR_ACCOUNT,YOCTO
from pydantic import BaseModel, Field

class BookingCreate(BaseModel):
    provider_id:int=Field(gt=0)
    listing_id:int=Field(gt=0)
    requested_start:str=Field(min_length=10,max_length=40)
    note:str=Field(min_length=5,max_length=500)

class BookingDecision(BaseModel):
    status:str=Field(pattern='^(ACCEPTED|DECLINED|CANCELLED|COMPLETED)$')

class ShipmentUpdate(BaseModel):
    status:str=Field(pattern='^(PREPARING|DISPATCHED|DELIVERED)$')
    carrier:str=Field(default='',max_length=100)
    reference:str=Field(default='',max_length=120)
    note:str=Field(default='',max_length=500)

class RefundCreate(BaseModel):
    reason:str=Field(min_length=12,max_length=1200)

class RefundProof(BaseModel):
    tx_hash:str=Field(min_length=40,max_length=48)
    signer_account_id:str=Field(min_length=4,max_length=64)

class VerificationApplication(BaseModel):
    registry_reference:str=Field(min_length=3,max_length=100)
    public_evidence_url:str=Field(min_length=10,max_length=350)
    note:str=Field(default='',max_length=500)

class VerificationDecision(BaseModel):
    status:str=Field(pattern='^(REVIEWED|REJECTED)$')
    note:str=Field(default='',max_length=600)

class RefundDecision(BaseModel):
    decision:str=Field(pattern='^(APPROVED_MANUAL|DECLINED)$')
    note:str=Field(default='',max_length=600)


def install(app,conn,current):
    with conn() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS avora_bookings(
            id INTEGER PRIMARY KEY, buyer_id INTEGER NOT NULL REFERENCES users(id),
            provider_id INTEGER NOT NULL REFERENCES providers(id), listing_id INTEGER NOT NULL REFERENCES listings(id),
            requested_start TEXT NOT NULL, note TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'REQUESTED',
            created INTEGER NOT NULL, updated INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS avora_bookings_provider ON avora_bookings(provider_id,status);
        CREATE TABLE IF NOT EXISTS avora_deliveries(
            order_id INTEGER PRIMARY KEY REFERENCES marketplace_orders(id),status TEXT NOT NULL DEFAULT 'PREPARING',
            carrier TEXT NOT NULL DEFAULT '',reference TEXT NOT NULL DEFAULT '',note TEXT NOT NULL DEFAULT '',updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS avora_refund_requests(
            id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES marketplace_orders(id),
            buyer_id INTEGER NOT NULL REFERENCES users(id),reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'REQUESTED',response_note TEXT NOT NULL DEFAULT '',
            created INTEGER NOT NULL,updated INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS avora_refunds_order ON avora_refund_requests(order_id);
        CREATE TABLE IF NOT EXISTS avora_refund_proofs(
            refund_id INTEGER PRIMARY KEY REFERENCES avora_refund_requests(id),
            tx_hash TEXT NOT NULL UNIQUE,signer_account TEXT NOT NULL,
            recipient_account TEXT NOT NULL,amount_yocto TEXT NOT NULL,verified_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS avora_business_reviews(
            provider_id INTEGER PRIMARY KEY REFERENCES providers(id),
            registry_reference TEXT NOT NULL,public_evidence_url TEXT NOT NULL,
            note TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'PENDING',
            reviewer_note TEXT NOT NULL DEFAULT '',created INTEGER NOT NULL,updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS avora_notifications(
            id INTEGER PRIMARY KEY,recipient_id INTEGER NOT NULL REFERENCES users(id),
            title TEXT NOT NULL,body TEXT NOT NULL,link TEXT NOT NULL,
            created INTEGER NOT NULL,read_at INTEGER);
        CREATE INDEX IF NOT EXISTS avora_notifications_user ON avora_notifications(recipient_id,created);
        ''')
    router=APIRouter(prefix='/api/operations',tags=['Marketplace operations'])
    def notify(db,uid,title,body,link):
        if uid is not None:db.execute('INSERT INTO avora_notifications(recipient_id,title,body,link,created) VALUES(?,?,?,?,?)',
                                    (uid,title,body,link,int(time.time())))
    def order(db,oid,uid):
        r=db.execute('''SELECT o.id,o.buyer_id,p.owner_id seller_id,m.status payment_status
             FROM marketplace_orders o JOIN providers p ON p.id=o.provider_id
             JOIN market_near_orders m ON m.order_id=o.id WHERE o.id=?''',(oid,)).fetchone()
        if not r:raise HTTPException(404,'NEAR order not found')
        if uid not in (r['buyer_id'],r['seller_id']):raise HTTPException(403,'Private order')
        return r
    def booking(db,bid,uid):
        r=db.execute('''SELECT b.*,p.owner_id seller_id,p.name provider_name,l.title listing_title
         FROM avora_bookings b JOIN providers p ON p.id=b.provider_id
         JOIN listings l ON l.id=b.listing_id WHERE b.id=?''',(bid,)).fetchone()
        if not r:raise HTTPException(404,'Booking not found')
        if uid not in (r['buyer_id'],r['seller_id']):raise HTTPException(403,'Private booking')
        return r
    @router.post('/bookings')
    def create_booking(data:BookingCreate,u=Depends(current)):
        try:
            start=datetime.fromisoformat(data.requested_start.replace('Z','+00:00'))
            if start.tzinfo is None:raise ValueError()
            if not (time.time()+300 < start.timestamp() < time.time()+366*86400):raise ValueError()
        except (ValueError,OverflowError):raise HTTPException(422,'Choose a future date and time including timezone (ISO 8601)')
        with conn() as db:
            p=db.execute('SELECT id,owner_id FROM providers WHERE id=?',(data.provider_id,)).fetchone()
            l=db.execute('SELECT provider_id,kind FROM listings WHERE id=?',(data.listing_id,)).fetchone()
            if not p or not p['owner_id']:raise HTTPException(422,'Booking requires a registered real provider account')
            if p['owner_id']==u['id']:raise HTTPException(403,'Cannot book your own service')
            if not l or l['provider_id']!=data.provider_id or l['kind']=='Products':raise HTTPException(422,'Choose a service from this provider')
            ts=int(time.time())
            bid=db.execute('INSERT INTO avora_bookings(buyer_id,provider_id,listing_id,requested_start,note,created,updated) VALUES(?,?,?,?,?,?,?)',
                (u['id'],data.provider_id,data.listing_id,start.astimezone(timezone.utc).isoformat(),data.note,ts,ts)).lastrowid
            notify(db,p['owner_id'],'New booking request','A buyer requested a service appointment.','/operations')
            return {'id':bid,'status':'REQUESTED','funds_moved':False}
    @router.get('/bookings')
    def bookings(u=Depends(current)):
        with conn() as db:return [dict(x) for x in db.execute('''SELECT b.*,p.name provider_name,p.owner_id seller_id,l.title listing_title
         FROM avora_bookings b JOIN providers p ON p.id=b.provider_id JOIN listings l ON l.id=b.listing_id
         WHERE b.buyer_id=? OR p.owner_id=? ORDER BY b.id DESC LIMIT 100''',(u['id'],u['id']))]
    @router.post('/bookings/{bid}/decision')
    def decide_booking(bid:int,data:BookingDecision,u=Depends(current)):
        with conn() as db:
            r=booking(db,bid,u['id'])
            valid=(r['status']=='REQUESTED' and data.status in ('ACCEPTED','DECLINED') and r['seller_id']==u['id']) or \
                  (r['status']=='REQUESTED' and data.status=='CANCELLED' and r['buyer_id']==u['id']) or \
                  (r['status']=='ACCEPTED' and data.status=='COMPLETED' and r['seller_id']==u['id']) or \
                  (r['status']=='ACCEPTED' and data.status=='CANCELLED' and u['id'] in (r['buyer_id'],r['seller_id']))
            if not valid:raise HTTPException(409,'This booking transition is not permitted')
            if data.status=='ACCEPTED':
                other=db.execute('''SELECT 1 FROM avora_bookings WHERE provider_id=? AND id<>? AND status='ACCEPTED' AND requested_start=?''',(r['provider_id'],bid,r['requested_start'])).fetchone()
                if other:raise HTTPException(409,'Provider already has an accepted appointment at this time')
            db.execute('UPDATE avora_bookings SET status=?,updated=? WHERE id=?',(data.status,int(time.time()),bid))
            receiver=r['buyer_id'] if r['seller_id']==u['id'] else r['seller_id']
            notify(db,receiver,'Booking '+data.status.lower(),'Your booking status was updated.','/operations')
            return {'id':bid,'status':data.status,'payment_status':'NOT_CHARGED'}
    @router.get('/orders/{oid}/delivery')
    def delivery(oid:int,u=Depends(current)):
        with conn() as db:
            r=order(db,oid,u['id'])
            d=db.execute('SELECT status,carrier,reference,note,updated FROM avora_deliveries WHERE order_id=?',(oid,)).fetchone()
            return {'order_id':oid,'payment_status':r['payment_status'],'delivery':dict(d) if d else None,'tracking_type':'seller_entered_not_carrier_verified'}
    @router.get('/orders/{oid}/carrier-lookup')
    async def carrier_lookup(oid:int,u=Depends(current)):
        # Optional EasyPost tracking. Never claim a seller-entered update is carrier verified.
        with conn() as db:
            r=order(db,oid,u['id'])
            shipment=db.execute('SELECT carrier,reference FROM avora_deliveries WHERE order_id=?',(oid,)).fetchone()
            if not shipment or not shipment['reference']:
                raise HTTPException(409,'No carrier tracking reference supplied by seller')
            carrier=shipment['carrier'].strip();tracking=shipment['reference'].strip()
            if not re.fullmatch(r'[A-Za-z0-9_-]{3,80}',tracking) or (carrier and not re.fullmatch(r'[A-Za-z0-9_-]{2,50}',carrier)):
                raise HTTPException(422,'Carrier name or reference is not compatible with API lookup')
        key=os.getenv('EASYPOST_API_KEY','')
        if not key:raise HTTPException(503,'Live courier tracking is not configured; seller-reported tracking remains available')
        params={'tracking_codes':tracking,'page_size':10}
        if carrier:params['carrier']=carrier
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response=await client.get('https://api.easypost.com/v2/trackers',params=params,auth=(key,''))
                response.raise_for_status();payload=response.json()
        except (httpx.HTTPError,ValueError):raise HTTPException(503,'Courier tracking provider unavailable; seller report is unchanged')
        matches=[t for t in payload.get('trackers',[]) if t.get('tracking_code')==tracking and (not carrier or (t.get('carrier') or '').casefold()==carrier.casefold())]
        if not matches:raise HTTPException(404,'EasyPost has no matching tracker; not a confirmed delivery')
        record=matches[0]
        latest=(record.get('tracking_details') or [])[-1:] or [{}]
        return {'order_id':oid,'source':'EasyPost API','mode':record.get('mode','unknown'),
                'carrier':record.get('carrier'),'tracking_code':tracking,
                'status':record.get('status','unknown'),
                'last_carrier_event':{'message':str(latest[0].get('message') or '')[:300],
                                      'timestamp':latest[0].get('datetime')},
                'carrier_data_available':True,
                'notice':'Carrier-reported via EasyPost; availability and tracking quality depend on the courier. Test-mode data is not proof of a physical delivery.'}

    @router.put('/orders/{oid}/delivery')
    def update_delivery(oid:int,data:ShipmentUpdate,u=Depends(current)):
        with conn() as db:
            r=order(db,oid,u['id'])
            if r['seller_id']!=u['id']:raise HTTPException(403,'Only the seller can update delivery')
            if r['payment_status']!='VERIFIED':raise HTTPException(409,'Verified NEAR payment required before fulfilment')
            old=db.execute('SELECT status FROM avora_deliveries WHERE order_id=?',(oid,)).fetchone()
            sequence={'PREPARING':0,'DISPATCHED':1,'DELIVERED':2}
            if old and sequence[data.status] < sequence[old['status']]:raise HTTPException(409,'Delivery status cannot move backwards')
            db.execute('''INSERT INTO avora_deliveries(order_id,status,carrier,reference,note,updated) VALUES(?,?,?,?,?,?)
            ON CONFLICT(order_id) DO UPDATE SET status=excluded.status,carrier=excluded.carrier,reference=excluded.reference,note=excluded.note,updated=excluded.updated''',
            (oid,data.status,data.carrier,data.reference,data.note,int(time.time())))
            notify(db,r['buyer_id'],'Delivery update','Seller marked order #'+str(oid)+' as '+data.status.lower(),'/market-order/'+str(oid))
            return {'order_id':oid,'status':data.status,'tracking_type':'seller_entered_not_carrier_verified'}
    @router.post('/orders/{oid}/refund-request')
    def request_refund(oid:int,data:RefundCreate,u=Depends(current)):
        with conn() as db:
            r=order(db,oid,u['id'])
            if r['buyer_id']!=u['id']:raise HTTPException(403,'Only buyer may request refund')
            if r['payment_status']!='VERIFIED':raise HTTPException(409,'Refund request requires verified payment')
            if db.execute("SELECT 1 FROM avora_refund_requests WHERE order_id=? AND status IN ('REQUESTED','APPROVED_MANUAL')",(oid,)).fetchone():raise HTTPException(409,'An active refund request already exists')
            ts=int(time.time());rid=db.execute('INSERT INTO avora_refund_requests(order_id,buyer_id,reason,created,updated) VALUES(?,?,?,?,?)',(oid,u['id'],data.reason,ts,ts)).lastrowid
            notify(db,r['seller_id'],'Refund request','Buyer opened refund request for order #'+str(oid),'/operations')
            return {'id':rid,'status':'REQUESTED','funds_returned':False}
    @router.get('/refund-requests')
    def refunds(u=Depends(current)):
        with conn() as db:
            return [dict(x) for x in db.execute('''SELECT f.*,p.owner_id seller_id,p.name provider_name,pr.tx_hash verified_refund_hash,pr.verified_at refund_verified_at
             FROM avora_refund_requests f JOIN marketplace_orders o ON o.id=f.order_id JOIN providers p ON p.id=o.provider_id
             LEFT JOIN avora_refund_proofs pr ON pr.refund_id=f.id
             WHERE f.buyer_id=? OR p.owner_id=? ORDER BY f.id DESC LIMIT 100''',(u['id'],u['id']))]
    @router.post('/refund-requests/{rid}/decision')
    def refund_decision(rid:int,data:RefundDecision,u=Depends(current)):
        with conn() as db:
            r=db.execute('''SELECT f.*,p.owner_id seller_id FROM avora_refund_requests f JOIN marketplace_orders o ON o.id=f.order_id JOIN providers p ON p.id=o.provider_id WHERE f.id=?''',(rid,)).fetchone()
            if not r:raise HTTPException(404,'Refund request not found')
            if r['seller_id']!=u['id']:raise HTTPException(403,'Only seller may respond')
            if r['status']!='REQUESTED':raise HTTPException(409,'Refund request already decided')
            db.execute('UPDATE avora_refund_requests SET status=?,response_note=?,updated=? WHERE id=?',(data.decision,data.note,int(time.time()),rid))
            notify(db,r['buyer_id'],'Refund request reviewed','Seller responded to your refund request; no blockchain refund was executed.','/operations')
            return {'id':rid,'status':data.decision,'funds_returned':False,'note':'This decision does not execute a refund on NEAR.'}

    @router.get('/bookings/{bid}/calendar.ics')
    def calendar_export(bid:int,u=Depends(current)):
        with conn() as db:
            b=booking(db,bid,u['id'])
            if b['status'] not in ('ACCEPTED','COMPLETED'):
                raise HTTPException(409,'Appointment must be accepted before exporting a calendar event')
            start=datetime.fromisoformat(b['requested_start'].replace('Z','+00:00')).astimezone(timezone.utc)
            from datetime import timedelta
            end=start+timedelta(hours=1)
            def safe(v):
                return str(v).replace('\\','\\\\').replace('\n','\\n').replace(',','\\,').replace(';','\\;')[:800]
            date=lambda t:t.strftime('%Y%m%dT%H%M%SZ')
            event='\r\n'.join([
                'BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//AVORA//Service Appointments//EN','CALSCALE:GREGORIAN',
                'METHOD:PUBLISH','BEGIN:VEVENT','UID:avora-booking-'+str(bid)+'@avora.local',
                'DTSTAMP:'+date(datetime.now(timezone.utc)),
                'DTSTART:'+date(start),'DTEND:'+date(end),
                'SUMMARY:'+safe(b['listing_title']+' — '+b['provider_name']),
                'DESCRIPTION:'+safe('AVORA booking #'+str(bid)+'; '+b['note']),
                'STATUS:'+('CONFIRMED' if b['status']=='ACCEPTED' else 'COMPLETED'),
                'END:VEVENT','END:VCALENDAR',''])
            return Response(content=event,media_type='text/calendar; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="avora-booking-{bid}.ics"','Cache-Control':'no-store'})

    @router.get('/refund-requests/{rid}/instructions')
    def refund_instructions(rid:int,u=Depends(current)):
        with conn() as db:
            record=db.execute('''SELECT f.*,p.owner_id seller_id,o.buyer_id,m.signer original_payer,m.recipient original_payee,m.amount_yocto,m.status payment_status,
                                pr.tx_hash refund_hash FROM avora_refund_requests f
                                JOIN marketplace_orders o ON o.id=f.order_id
                                JOIN providers p ON p.id=o.provider_id
                                JOIN market_near_orders m ON m.order_id=o.id
                                LEFT JOIN avora_refund_proofs pr ON pr.refund_id=f.id WHERE f.id=?''',(rid,)).fetchone()
            if not record:raise HTTPException(404,'Refund request not found')
            if u['id'] not in (record['buyer_id'],record['seller_id']):raise HTTPException(403,'Private refund request')
            if record['status'] not in ('APPROVED_MANUAL','REFUNDED_VERIFIED'):
                raise HTTPException(409,'Seller must approve a refund first')
            if record['payment_status']!='VERIFIED' or not record['original_payer']:
                raise HTTPException(409,'Original verified payer is missing')
            return {'refund_id':rid,'order_id':record['order_id'],'status':record['status'],
                    'network':'testnet','from_account':record['original_payee'],
                    'to_account':record['original_payer'],
                    'amount_near':str(Decimal(record['amount_yocto'])/YOCTO),
                    'verified_refund_tx_hash':record['refund_hash'],
                    'disclaimer':'A refund is a new, separately signed NEAR testnet transfer. AVORA never moves wallet funds automatically.'}

    @router.post('/refund-requests/{rid}/verify')
    async def verify_refund(rid:int,data:RefundProof,u=Depends(current)):
        if not TX_HASH.fullmatch(data.tx_hash) or not NEAR_ACCOUNT.fullmatch(data.signer_account_id):
            raise HTTPException(422,'Enter a valid testnet transaction hash and signer')
        with conn() as db:
            r=db.execute('''SELECT f.*,p.owner_id seller_id,o.buyer_id,m.signer original_payer,
                           m.recipient original_payee,m.amount_yocto,m.status payment_status
                           FROM avora_refund_requests f JOIN marketplace_orders o ON o.id=f.order_id
                           JOIN providers p ON p.id=o.provider_id JOIN market_near_orders m ON m.order_id=o.id
                           WHERE f.id=?''',(rid,)).fetchone()
            if not r:raise HTTPException(404,'Refund request not found')
            if u['id'] not in (r['seller_id'],r['buyer_id']):raise HTTPException(403,'Private refund request')
            if r['status']!='APPROVED_MANUAL' or r['payment_status']!='VERIFIED':raise HTTPException(409,'Refund not awaiting on-chain verification')
            sender=r['original_payee'];recipient=r['original_payer'];amount=r['amount_yocto']
            if data.signer_account_id!=sender:raise HTTPException(422,'Refund must come from the original receiving account')
            if not recipient or sender==recipient:raise HTTPException(409,'Original payer and payee must be distinct verified accounts')
            if (db.execute('SELECT 1 FROM avora_refund_proofs WHERE tx_hash=?',(data.tx_hash,)).fetchone() or
                db.execute('SELECT 1 FROM near_proofs WHERE tx_hash=?',(data.tx_hash,)).fetchone() or
                db.execute('SELECT 1 FROM market_near_orders WHERE tx_hash=?',(data.tx_hash,)).fetchone()):
                raise HTTPException(409,'Transaction already claimed')
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response=await client.post(os.getenv('NEAR_TESTNET_RPC','https://rpc.testnet.near.org'),
                  json={'jsonrpc':'2.0','id':'avora-refund-proof','method':'tx',
                        'params':{'tx_hash':data.tx_hash,'sender_account_id':sender,'wait_until':'FINAL'}})
                response.raise_for_status();payload=response.json()
            except (httpx.HTTPError,ValueError):raise HTTPException(503,'NEAR testnet RPC temporarily unavailable')
        if payload.get('error'):raise HTTPException(422,'Refund transaction not confirmed by RPC')
        result=payload.get('result') or {};tx=result.get('transaction') or {};status=result.get('status') or {}
        if tx.get('hash')!=data.tx_hash or tx.get('signer_id')!=sender or tx.get('receiver_id')!=recipient:
            raise HTTPException(422,'Refund signer, recipient or transaction hash mismatch')
        deposits=[a['Transfer'].get('deposit') for a in tx.get('actions',[]) if isinstance(a,dict) and isinstance(a.get('Transfer'),dict)]
        if deposits!=[amount] or result.get('final_execution_status')!='FINAL' or not isinstance(status,dict) or not any(x in status for x in ('SuccessValue','SuccessReceiptId')) or not (result.get('transaction_outcome') or {}).get('outcome'):
            raise HTTPException(422,'Refund amount or final success does not match approved return terms')
        with conn() as db:
            latest=db.execute('SELECT status FROM avora_refund_requests WHERE id=?',(rid,)).fetchone()
            if not latest or latest['status']!='APPROVED_MANUAL':raise HTTPException(409,'Refund status changed')
            if (db.execute('SELECT 1 FROM avora_refund_proofs WHERE tx_hash=?',(data.tx_hash,)).fetchone() or
                db.execute('SELECT 1 FROM near_proofs WHERE tx_hash=?',(data.tx_hash,)).fetchone() or
                db.execute('SELECT 1 FROM market_near_orders WHERE tx_hash=?',(data.tx_hash,)).fetchone()):raise HTTPException(409,'Transaction already claimed')
            ts=int(time.time())
            db.execute('INSERT INTO avora_refund_proofs(refund_id,tx_hash,signer_account,recipient_account,amount_yocto,verified_at) VALUES(?,?,?,?,?,?)',
                       (rid,data.tx_hash,sender,recipient,amount,ts))
            db.execute("UPDATE avora_refund_requests SET status='REFUNDED_VERIFIED',updated=? WHERE id=?",(ts,rid))
            notify(db,r['buyer_id'],'Refund independently verified','NEAR testnet repayment verified for order #'+str(r['order_id']),'/operations')
            if r['seller_id'] is not None:notify(db,r['seller_id'],'Refund verification complete','NEAR testnet repayment verified for order #'+str(r['order_id']),'/operations')
            return {'refund_id':rid,'status':'REFUNDED_VERIFIED','funds_returned_verified':True,
                    'transaction_hash':data.tx_hash,'network':'testnet',
                    'amount_near':str(Decimal(amount)/YOCTO),
                    'explorer_url':'https://testnet.nearblocks.io/txns/'+data.tx_hash}

    @router.get('/verification/{pid}')
    def verification_status(pid:int,u=Depends(current)):
        with conn() as db:
            p=db.execute('SELECT owner_id FROM providers WHERE id=?',(pid,)).fetchone()
            if not p or p['owner_id']!=u['id']:raise HTTPException(403,'Only owner can see business review details')
            r=db.execute('SELECT registry_reference,public_evidence_url,note,status,reviewer_note,updated FROM avora_business_reviews WHERE provider_id=?',(pid,)).fetchone()
            return {'provider_id':pid,'review':dict(r) if r else None,
                    'independently_identity_verified':False,
                    'note':'This workflow records owner-submitted public evidence and optional manual operator review. It is not independent government-ID verification.'}

    @router.post('/verification/{pid}')
    def submit_verification(pid:int,data:VerificationApplication,u=Depends(current)):
        from urllib.parse import urlsplit
        url=urlsplit(data.public_evidence_url)
        try: valid_port=url.port in (None,443)
        except ValueError: valid_port=False
        if url.scheme!='https' or not url.hostname or url.username or url.password or not valid_port:
            raise HTTPException(422,'Enter a public HTTPS business registry or website link')
        with conn() as db:
            p=db.execute('SELECT owner_id FROM providers WHERE id=?',(pid,)).fetchone()
            if not p or p['owner_id']!=u['id']:raise HTTPException(403,'Only owner can submit business evidence')
            ts=int(time.time())
            db.execute('''INSERT INTO avora_business_reviews(provider_id,registry_reference,public_evidence_url,note,status,created,updated) VALUES(?,?,?,?,?,?,?)
                        ON CONFLICT(provider_id) DO UPDATE SET registry_reference=excluded.registry_reference,public_evidence_url=excluded.public_evidence_url,note=excluded.note,status='PENDING',reviewer_note='',updated=excluded.updated''',
                      (pid,data.registry_reference,data.public_evidence_url,data.note,'PENDING',ts,ts))
            return {'provider_id':pid,'status':'PENDING','verified':False}

    @router.post('/verification/{pid}/operator-review')
    def operator_review(pid:int,data:VerificationDecision,x_avora_operator_token:str=Header(default='')):
        import hmac
        token=os.getenv('AVORA_VERIFICATION_OPERATOR_TOKEN','')
        if not token or len(token)<24 or not hmac.compare_digest(token,x_avora_operator_token):
            raise HTTPException(403,'Manual review access not configured or denied')
        with conn() as db:
            record=db.execute('SELECT r.status,r.provider_id,p.owner_id FROM avora_business_reviews r JOIN providers p ON p.id=r.provider_id WHERE r.provider_id=?',(pid,)).fetchone()
            if not record or record['status']!='PENDING':raise HTTPException(409,'No pending business evidence')
            db.execute('UPDATE avora_business_reviews SET status=?,reviewer_note=?,updated=? WHERE provider_id=?',(data.status,data.note,int(time.time()),pid))
            notify(db,record['owner_id'],'Business evidence reviewed','A reviewer updated your public business evidence status. Identity was not independently verified.','/operations')
            return {'provider_id':pid,'status':data.status,'independently_identity_verified':False}

    @router.get('/ai/status')
    async def ai_status(u=Depends(current)):
        # A non-secret health check. Never return a token or its length.
        key=os.getenv('AI_API_KEY') or os.getenv('GROQ_API_KEY')
        base=os.getenv('AI_BASE_URL') or ('https://api.groq.com/openai/v1' if os.getenv('GROQ_API_KEY') or (key or '').startswith('gsk_') else '')
        model=os.getenv('AI_MODEL') or ('openai/gpt-oss-120b' if os.getenv('GROQ_API_KEY') else '')
        return {'configured':bool(key),'provider':'groq' if 'groq.com' in base else 'other',
                'model':model or 'not configured','network_test_performed':False,
                'note':'Use a real AI request from the Operating Desk to verify actual model output; configured does not mean the model call succeeds.'}

    @router.get('/notifications')
    def notifications(u=Depends(current)):
        with conn() as db:
            items=[dict(x) for x in db.execute('SELECT * FROM avora_notifications WHERE recipient_id=? ORDER BY id DESC LIMIT 60',(u['id'],))]
            return {'unread':sum(1 for x in items if not x['read_at']),'items':items}
    @router.post('/notifications/{nid}/read')
    def read_notification(nid:int,u=Depends(current)):
        with conn() as db:
            result=db.execute('UPDATE avora_notifications SET read_at=? WHERE id=? AND recipient_id=? AND read_at IS NULL',(int(time.time()),nid,u['id']))
            if result.rowcount!=1:raise HTTPException(404,'Unread notification not found')
            return {'read':True}
    app.include_router(router)
