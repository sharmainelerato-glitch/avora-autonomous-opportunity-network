"""Human-approved opportunity coalitions and NEAR testnet transfer proof.

Onchain transfer is conducted by the user's own wallet; this service NEVER holds wallet keys,
creates a fake receipt, or pretends to provide escrow or a contract deployment.
"""
from __future__ import annotations
import json
import os
import re
import time
from decimal import Decimal, InvalidOperation
from typing import List, Optional

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

NEAR_RPC = os.getenv("NEAR_TESTNET_RPC", "https://rpc.testnet.near.org")
NEAR_ACCOUNT = re.compile(r"^(?=.{2,64}$)[a-z0-9][a-z0-9_.-]*\.testnet$")
TX_HASH = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{40,48}$")
YOCTO = 10**24

class CreateOpportunity(BaseModel):
    request_id: int = Field(gt=0)
    provider_ids: List[int] = Field(min_length=1,max_length=6)
    # This is a testnet transfer amount PER provider, deliberately not a fiat conversion.
    amount_near_each: str = Field(default="0.01",max_length=40)

class Respond(BaseModel):
    accept: bool
    payout_account: str = Field(default="",max_length=64)

class ReplaceProvider(BaseModel):
    outgoing_provider_id: int = Field(gt=0)
    incoming_provider_id: int = Field(gt=0)

class PaymentAttempt(BaseModel):
    provider_id: int = Field(gt=0)

class AttemptUpdate(BaseModel):
    status: str = Field(pattern=r'^(wallet_rejected|wallet_returned|rpc_pending|failed|needs_review)$')
    tx_hash: Optional[str] = Field(default=None,max_length=48)

class VerifyProof(BaseModel):
    provider_id: int = Field(gt=0)
    tx_hash: str = Field(min_length=40,max_length=48)
    signer_account_id: str = Field(min_length=4,max_length=64)


def amount_yocto(value: str) -> str:
    try: n=Decimal(value)
    except (InvalidOperation,ValueError):raise HTTPException(422,'Invalid testnet NEAR amount')
    if not n.is_finite() or n<=0 or n>Decimal('1') or n.as_tuple().exponent < -24:
        raise HTTPException(422,'Use a positive testnet amount at most 1 NEAR with up to 24 decimals')
    return str(int(n*YOCTO))


def now():return int(time.time())

def install_near_workflows(app, conn, current):
    with conn() as db:
        db.executescript('''
CREATE TABLE IF NOT EXISTS near_opportunities (
 id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL REFERENCES requests(id), buyer_id INTEGER NOT NULL REFERENCES users(id),
 revision INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'invited',
 amount_yocto TEXT NOT NULL, created INTEGER NOT NULL, approved INTEGER);
CREATE TABLE IF NOT EXISTS near_participants (
 opportunity_id INTEGER NOT NULL REFERENCES near_opportunities(id),
 provider_id INTEGER NOT NULL REFERENCES providers(id),
 status TEXT NOT NULL DEFAULT 'invited', payout_account TEXT,
 PRIMARY KEY(opportunity_id,provider_id));
CREATE TABLE IF NOT EXISTS near_proofs (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES near_opportunities(id),
 provider_id INTEGER NOT NULL REFERENCES providers(id),
 tx_hash TEXT NOT NULL UNIQUE, signer_account TEXT NOT NULL,
 receiver_account TEXT NOT NULL, verified_at INTEGER NOT NULL, revision INTEGER NOT NULL,
 amount_yocto TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS near_audit (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES near_opportunities(id),
 actor_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL, info TEXT NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS near_payment_attempts (
 id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES near_opportunities(id),
 provider_id INTEGER NOT NULL REFERENCES providers(id), buyer_id INTEGER NOT NULL REFERENCES users(id),
 revision INTEGER NOT NULL, recipient TEXT NOT NULL, amount_yocto TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'initiated', tx_hash TEXT, created INTEGER NOT NULL, updated INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS near_attempts_opp_idx ON near_payment_attempts(opportunity_id,created);
''')

    from app.avora_autonomy import check_policy

    def event(db,oid,uid,action,info):
        db.execute('INSERT INTO near_audit(opportunity_id,actor_id,action,info,created) VALUES(?,?,?,?,?)',
                   (oid,uid,action,json.dumps(info,sort_keys=True),now()))

    def get(db,oid,uid):
        record=db.execute('SELECT * FROM near_opportunities WHERE id=?',(oid,)).fetchone()
        if not record:raise HTTPException(404,'Opportunity not found')
        involved=(record['buyer_id']==uid or db.execute('''SELECT 1 FROM near_participants np JOIN providers p ON p.id=np.provider_id
          WHERE np.opportunity_id=? AND p.owner_id=?''',(oid,uid)).fetchone())
        if not involved:raise HTTPException(403,'Only invited participants may see this opportunity')
        return record

    def details(db,record):
        oid=record['id']
        participants=[dict(r) for r in db.execute('''SELECT np.provider_id,p.name,p.owner_id,np.status,np.payout_account
                    FROM near_participants np JOIN providers p ON p.id=np.provider_id WHERE np.opportunity_id=? ORDER BY np.provider_id''',(oid,))]
        proofs=[dict(r) for r in db.execute('SELECT provider_id,tx_hash,signer_account,receiver_account,verified_at,revision,amount_yocto FROM near_proofs WHERE opportunity_id=?',(oid,))]
        audit=[dict(r) for r in db.execute('SELECT action,info,created FROM near_audit WHERE opportunity_id=? ORDER BY id DESC LIMIT 30',(oid,))]
        attempts=[dict(r) for r in db.execute('SELECT id,provider_id,status,tx_hash,created,updated,revision FROM near_payment_attempts WHERE opportunity_id=? ORDER BY id DESC LIMIT 40',(oid,))]
        return {**dict(record),'participants':participants,'proofs':proofs,'attempts':attempts,'audit':audit,'network':'testnet',
                'amount_near_each':str(Decimal(record['amount_yocto'])/YOCTO),
                'onchain_verified_count':len(proofs),
                'settlement':{'total_payees':len(participants),'verified_payees':len({r['provider_id'] for r in proofs}),
                  'pending_payees':len(participants)-len({r['provider_id'] for r in proofs}),
                  'verified_yocto':str(len(proofs)*int(record['amount_yocto'])),
                  'approved_total_yocto':str(len(participants)*int(record['amount_yocto']))}}

    @app.get('/api/near/config')
    def near_config():
        return {'network':'testnet','rpc':NEAR_RPC,'wallet_secret_required':False,'mechanism':'user-approved external or optional browser wallet transfer + RPC proof',
                'limitations':'No deployed escrow contract, no stablecoin, no real-money merchant settlement'}

    @app.get('/api/near/opportunities')
    def my_opportunities(u=Depends(current)):
        with conn() as db:
            items=db.execute('''SELECT DISTINCT o.* FROM near_opportunities o LEFT JOIN near_participants np ON np.opportunity_id=o.id
            LEFT JOIN providers p ON p.id=np.provider_id WHERE o.buyer_id=? OR p.owner_id=? ORDER BY o.id DESC LIMIT 50''',(u['id'],u['id']))
            return [details(db,r) for r in items]

    @app.post('/api/near/opportunities')
    def create(x:CreateOpportunity,u=Depends(current)):
        amount=amount_yocto(x.amount_near_each)
        ids=list(dict.fromkeys(x.provider_ids))
        if len(ids)!=len(x.provider_ids):raise HTTPException(422,'Duplicate providers')
        with conn() as db:
            request=db.execute('SELECT * FROM requests WHERE id=?',(x.request_id,)).fetchone()
            if not request:raise HTTPException(404,'Request not found')
            if request['buyer_id']!=u['id']:raise HTTPException(403,'Only request owner can invite a coalition')
            if request['status']!='open':raise HTTPException(409,'Request is not open')
            check_policy(db,u['id'],ids,amount)
            for pid in ids:
                p=db.execute('SELECT id,owner_id FROM providers WHERE id=?',(pid,)).fetchone()
                if not p or p['owner_id'] is None or p['owner_id']==u['id']:
                    raise HTTPException(422,'Only independent registered provider accounts can be invited')
            cur=db.execute('INSERT INTO near_opportunities(request_id,buyer_id,amount_yocto,created) VALUES(?,?,?,?)',
                           (x.request_id,u['id'],amount,now()))
            oid=cur.lastrowid
            for pid in ids:db.execute('INSERT INTO near_participants(opportunity_id,provider_id) VALUES(?,?)',(oid,pid))
            event(db,oid,u['id'],'coalition_invited',{'provider_ids':ids,'per_provider_testnet_yocto':amount})
            return details(db,db.execute('SELECT * FROM near_opportunities WHERE id=?',(oid,)).fetchone())

    @app.get('/api/near/opportunities/{oid}')
    def read(oid:int,u=Depends(current)):
        with conn() as db:return details(db,get(db,oid,u['id']))

    @app.get('/api/near/opportunities/{oid}/payment-instructions')
    def payment_instructions(oid:int,u=Depends(current)):
        '''Grounded, read-only instructions. Never signs or broadcasts any transfer.'''
        with conn() as db:
            record=get(db,oid,u['id'])
            if record['buyer_id']!=u['id']:raise HTTPException(403,'Only buyer can see payment instructions')
            if record['status'] not in ('approved','partially_verified','verified'):
                raise HTTPException(409,'Providers must accept and buyer must approve terms first')
            participants=[dict(row) for row in db.execute('''SELECT np.provider_id,p.name,np.status,np.payout_account
                 FROM near_participants np JOIN providers p ON p.id=np.provider_id
                 WHERE np.opportunity_id=? ORDER BY np.provider_id''',(oid,))]
            proofs={row['provider_id']:row['tx_hash'] for row in db.execute('SELECT provider_id,tx_hash FROM near_proofs WHERE opportunity_id=?',(oid,))}
            return {'network':'testnet','opportunity_id':oid,'revision':record['revision'],
                    'payer_must_sign_in_external_wallet':True,'testnet_only':True,
                    'payees':[{'provider_id':r['provider_id'],'name':r['name'],'recipient':r['payout_account'],
                        'amount_near':str(Decimal(record['amount_yocto'])/YOCTO),
                        'amount_yocto':record['amount_yocto'], 'verified':r['provider_id'] in proofs,
                        'verified_tx_hash':proofs.get(r['provider_id'])} for r in participants],
                    'instructions':'Using a NEAR TESTNET wallet, send one ordinary NEAR transfer per pending provider exactly as shown. Verify the destination, testnet network and amount before you sign. Copy transaction hash after signing and submit it in AVORA for independent RPC verification.',
                    'warnings':['No escrow or automatic payouts','Do not use mainnet funds','AVORA never requests your seed phrase or private key']}

    @app.post('/api/near/opportunities/{oid}/payment-attempts')
    def payment_attempt(oid:int,x:PaymentAttempt,u=Depends(current)):
        # A wallet-attempt journal; never proof of payment or authorization to spend.
        with conn() as db:
            record=get(db,oid,u['id'])
            if record['buyer_id']!=u['id']:raise HTTPException(403,'Buyer-only payment action')
            if record['status'] not in ('approved','partially_verified'):
                raise HTTPException(409,'Approve all provider terms before starting wallet payment')
            row=db.execute('SELECT * FROM near_participants WHERE opportunity_id=? AND provider_id=?',(oid,x.provider_id)).fetchone()
            if not row or row['status']!='accepted' or not row['payout_account']:
                raise HTTPException(422,'Provider has not accepted a testnet receiving account')
            if db.execute('SELECT 1 FROM near_proofs WHERE opportunity_id=? AND provider_id=?',(oid,x.provider_id)).fetchone():
                raise HTTPException(409,'Provider already paid and verified; duplicate payment blocked')
            unresolved=db.execute('''SELECT id,status FROM near_payment_attempts WHERE opportunity_id=? AND provider_id=? AND revision=?
                AND status IN ('initiated','wallet_returned','rpc_pending','needs_review') ORDER BY id DESC LIMIT 1''',(oid,x.provider_id,record['revision'])).fetchone()
            if unresolved:
                raise HTTPException(409,'Previous wallet attempt is not resolved. Check your wallet and verify its hash before starting another transfer.')
            check_policy(db,u['id'],[r['provider_id'] for r in db.execute('SELECT provider_id FROM near_participants WHERE opportunity_id=?',(oid,))],record['amount_yocto'])
            t=now()
            attempt_id=db.execute('''INSERT INTO near_payment_attempts(opportunity_id,provider_id,buyer_id,revision,recipient,amount_yocto,status,created,updated)
                VALUES(?,?,?,?,?,?,?,?,?)''',(oid,x.provider_id,u['id'],record['revision'],row['payout_account'],record['amount_yocto'],'initiated',t,t)).lastrowid
            event(db,oid,u['id'],'wallet_payment_attempt',{'provider_id':x.provider_id,'attempt_id':attempt_id,'payment_status':'not_verified'})
            return {'attempt_id':attempt_id,'status':'initiated','network':'testnet','recipient':row['payout_account'],
                    'amount_yocto':record['amount_yocto'],'revision':record['revision'],
                    'message':'This record is an attempt only, not an executed transaction or receipt.'}

    @app.post('/api/near/opportunities/{oid}/payment-attempts/{aid}/status')
    def payment_attempt_status(oid:int,aid:int,x:AttemptUpdate,u=Depends(current)):
        with conn() as db:
            record=get(db,oid,u['id'])
            if record['buyer_id']!=u['id']:raise HTTPException(403,'Buyer-only payment attempt')
            attempt=db.execute('SELECT * FROM near_payment_attempts WHERE id=? AND opportunity_id=? AND buyer_id=?',(aid,oid,u['id'])).fetchone()
            if not attempt:raise HTTPException(404,'Payment attempt not found')
            if attempt['revision']!=record['revision']:raise HTTPException(409,'Attempt belongs to outdated agreement')
            if attempt['status']=='verified':raise HTTPException(409,'Verified attempt cannot be changed')
            if x.tx_hash and not TX_HASH.fullmatch(x.tx_hash):raise HTTPException(422,'Invalid NEAR transaction hash')
            db.execute('UPDATE near_payment_attempts SET status=?,tx_hash=COALESCE(?,tx_hash),updated=? WHERE id=?',
                       (x.status,x.tx_hash,now(),aid))
            event(db,oid,u['id'],'wallet_attempt_status',{'attempt_id':aid,'status':x.status})
            return {'status':x.status,'verified':False,'warning':'Wallet callback status is not on-chain verification.'}

    @app.get('/api/near/opportunities/{oid}/settlement')
    def settlement(oid:int,u=Depends(current)):
        with conn() as db:
            record=get(db,oid,u['id']); view=details(db,record)
            return {'network':'testnet','opportunity_id':oid,'revision':record['revision'],
                    'status':record['status'],'settlement':view['settlement'],
                    'allocations':[{'provider_id':pr['provider_id'],'name':pr['name'],'recipient':pr['payout_account'],
                                    'amount_yocto':record['amount_yocto'],
                                    'verified_tx_hash':next((proof['tx_hash'] for proof in view['proofs'] if proof['provider_id']==pr['provider_id']),None)}
                                   for pr in view['participants']],
                    'attempts':view['attempts'],
                    'disclaimer':'Payments are external NEAR testnet transfers. Only verified RPC proofs count as settled.'}

    @app.post('/api/near/opportunities/{oid}/respond')
    def respond(oid:int,x:Respond,u=Depends(current)):
        if x.accept and not NEAR_ACCOUNT.fullmatch(x.payout_account):
            raise HTTPException(422,'Provide your receiving account ending in .testnet')
        with conn() as db:
            record=get(db,oid,u['id'])
            if record['status'] not in ('invited','ready'):raise HTTPException(409,'Invitations are closed')
            matching=[r for r in db.execute('''SELECT np.provider_id,np.status FROM near_participants np JOIN providers p ON p.id=np.provider_id
                     WHERE np.opportunity_id=? AND p.owner_id=?''',(oid,u['id']))]
            if not matching:raise HTTPException(403,'Only an invited provider can respond')
            if len(matching)!=1:raise HTTPException(409,'One provider business per account in this coalition demo')
            pid=matching[0]['provider_id']
            if matching[0]['status'] not in ('invited','accepted'):raise HTTPException(409,'Invitation already declined or replaced')
            db.execute('UPDATE near_participants SET status=?,payout_account=? WHERE opportunity_id=? AND provider_id=?',
                       ('accepted' if x.accept else 'declined',x.payout_account if x.accept else None,oid,pid))
            statuses=[r['status'] for r in db.execute('SELECT status FROM near_participants WHERE opportunity_id=?',(oid,))]
            status='needs_rescue' if 'declined' in statuses else 'ready' if all(s=='accepted' for s in statuses) else 'invited'
            db.execute('UPDATE near_opportunities SET status=? WHERE id=?',(status,oid))
            event(db,oid,u['id'],'provider_accepted' if x.accept else 'provider_declined',{'provider_id':pid})
            return details(db,db.execute('SELECT * FROM near_opportunities WHERE id=?',(oid,)).fetchone())

    @app.post('/api/near/opportunities/{oid}/replace')
    def replace(oid:int,x:ReplaceProvider,u=Depends(current)):
        with conn() as db:
            record=get(db,oid,u['id'])
            if record['buyer_id']!=u['id']:raise HTTPException(403,'Only buyer may change a coalition')
            if record['status'] not in ('invited','ready','needs_rescue'):raise HTTPException(409,'Cannot replace an approved or paid coalition')
            if db.execute('SELECT 1 FROM near_proofs WHERE opportunity_id=?',(oid,)).fetchone():raise HTTPException(409,'Cannot rewrite verified payouts')
            old=db.execute('SELECT status FROM near_participants WHERE opportunity_id=? AND provider_id=?',(oid,x.outgoing_provider_id)).fetchone()
            new=db.execute('SELECT owner_id FROM providers WHERE id=?',(x.incoming_provider_id,)).fetchone()
            if not old:raise HTTPException(404,'Outgoing provider not in coalition')
            if not new or new['owner_id'] is None or new['owner_id']==u['id']:raise HTTPException(422,'Replacement must be independent registered provider')
            if db.execute('SELECT 1 FROM near_participants WHERE opportunity_id=? AND provider_id=?',(oid,x.incoming_provider_id)).fetchone():raise HTTPException(409,'Already in coalition')
            db.execute('DELETE FROM near_participants WHERE opportunity_id=? AND provider_id=?',(oid,x.outgoing_provider_id))
            db.execute('INSERT INTO near_participants(opportunity_id,provider_id) VALUES(?,?)',(oid,x.incoming_provider_id))
            # Revoke all previously gathered approvals when terms change.
            db.execute('UPDATE near_participants SET status="invited", payout_account=NULL WHERE opportunity_id=?',(oid,))
            db.execute('UPDATE near_opportunities SET revision=revision+1,status="invited",approved=NULL WHERE id=?',(oid,))
            event(db,oid,u['id'],'opportunity_rescued',{'replaced':x.outgoing_provider_id,'with':x.incoming_provider_id,'approvals_reset':True})
            return details(db,db.execute('SELECT * FROM near_opportunities WHERE id=?',(oid,)).fetchone())

    @app.post('/api/near/opportunities/{oid}/approve')
    def approve(oid:int,u=Depends(current)):
        with conn() as db:
            record=get(db,oid,u['id'])
            if record['buyer_id']!=u['id']:raise HTTPException(403,'Only buyer can approve financial terms')
            if record['status']!='ready':raise HTTPException(409,'All providers must accept first')
            part_ids=[r['provider_id'] for r in db.execute('SELECT provider_id FROM near_participants WHERE opportunity_id=?',(oid,))]
            check_policy(db,u['id'],part_ids,record['amount_yocto'])
            db.execute("UPDATE near_opportunities SET status='approved',approved=? WHERE id=?",(now(),oid))
            event(db,oid,u['id'],'buyer_approved',{'revision':record['revision'],'testnet_amount_yocto':record['amount_yocto']})
            return details(db,db.execute('SELECT * FROM near_opportunities WHERE id=?',(oid,)).fetchone())

    async def lookup_near_tx(hash_,signer):
        # No private key is handled by the backend.
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response=await client.post(NEAR_RPC,json={'jsonrpc':'2.0','id':'avora-near-proof','method':'tx',
                    'params':{'tx_hash':hash_,'sender_account_id':signer,'wait_until':'FINAL'}})
                response.raise_for_status(); payload=response.json()
            except (httpx.HTTPError,ValueError):raise HTTPException(503,'NEAR testnet RPC unavailable; retry')
        if 'error' in payload:raise HTTPException(422,'Transaction not confirmed by NEAR RPC')
        return payload.get('result') or {}

    @app.post('/api/near/opportunities/{oid}/verify-transfer')
    async def verify_transfer(oid:int,x:VerifyProof,u=Depends(current)):
        if not TX_HASH.fullmatch(x.tx_hash):raise HTTPException(422,'Invalid transaction hash')
        if not NEAR_ACCOUNT.fullmatch(x.signer_account_id):raise HTTPException(422,'Use a .testnet payer account')
        # Read expected amount and beneficiary before any network request.
        with conn() as db:
            record=get(db,oid,u['id'])
            if record['buyer_id']!=u['id']:raise HTTPException(403,'Only buyer can submit payout proof')
            if record['status'] not in ('approved','partially_verified'):raise HTTPException(409,'Buyer approval required before transfer verification')
            part=db.execute('SELECT * FROM near_participants WHERE opportunity_id=? AND provider_id=?',(oid,x.provider_id)).fetchone()
            if not part or part['status']!='accepted' or not part['payout_account']:raise HTTPException(422,'Payee has not accepted an account')
            expected=record['amount_yocto'];receiver=part['payout_account'];revision=record['revision']
            if db.execute('SELECT 1 FROM near_proofs WHERE tx_hash=?',(x.tx_hash,)).fetchone():raise HTTPException(409,'Transaction proof already used')
            if db.execute('SELECT 1 FROM near_proofs WHERE opportunity_id=? AND provider_id=?',(oid,x.provider_id)).fetchone():raise HTTPException(409,'Provider already has a verified proof')
        data=await lookup_near_tx(x.tx_hash,x.signer_account_id)
        tx=data.get('transaction') or {}
        outcome=data.get('transaction_outcome') or {}
        status=data.get('status') or {}
        if tx.get('hash')!=x.tx_hash or tx.get('signer_id')!=x.signer_account_id or tx.get('receiver_id')!=receiver:
            raise HTTPException(422,'Onchain signer, hash or beneficiary mismatch')
        actions=tx.get('actions') or []
        deposits=[a['Transfer'].get('deposit') for a in actions if isinstance(a,dict) and isinstance(a.get('Transfer'),dict)]
        if deposits != [expected]:raise HTTPException(422,'Transfer amount does not match approved testnet terms')
        if data.get('final_execution_status') != 'FINAL' or not isinstance(status,dict) or not any(k in status for k in ('SuccessValue','SuccessReceiptId')):
            raise HTTPException(422,'NEAR has not confirmed a successful transaction')
        if not outcome.get('outcome'):raise HTTPException(422,'Transaction outcome is missing')
        with conn() as db:
            latest=get(db,oid,u['id'])
            part=db.execute('SELECT * FROM near_participants WHERE opportunity_id=? AND provider_id=?',(oid,x.provider_id)).fetchone()
            if latest['revision']!=revision or latest['amount_yocto']!=expected or latest['status'] not in ('approved','partially_verified') or not part or part['payout_account']!=receiver:
                raise HTTPException(409,'Opportunity terms changed during verification')
            if db.execute('SELECT 1 FROM near_proofs WHERE tx_hash=? OR (opportunity_id=? AND provider_id=?)',(x.tx_hash,oid,x.provider_id)).fetchone():raise HTTPException(409,'Duplicate payout proof')
            db.execute('INSERT INTO near_proofs(opportunity_id,provider_id,tx_hash,signer_account,receiver_account,verified_at,revision,amount_yocto) VALUES(?,?,?,?,?,?,?,?)',
                       (oid,x.provider_id,x.tx_hash,x.signer_account_id,receiver,now(),revision,expected))
            db.execute('UPDATE near_payment_attempts SET status=?,tx_hash=?,updated=? WHERE opportunity_id=? AND provider_id=? AND revision=?',
                       ('verified',x.tx_hash,now(),oid,x.provider_id,revision))
            received=db.execute('SELECT COUNT(*) FROM near_proofs WHERE opportunity_id=?',(oid,)).fetchone()[0]
            total=db.execute('SELECT COUNT(*) FROM near_participants WHERE opportunity_id=?',(oid,)).fetchone()[0]
            db.execute('UPDATE near_opportunities SET status=? WHERE id=?',('verified' if received==total else 'partially_verified',oid))
            event(db,oid,u['id'],'testnet_transfer_verified',{'provider_id':x.provider_id,'tx_hash':x.tx_hash,'network':'testnet'})
            return details(db,db.execute('SELECT * FROM near_opportunities WHERE id=?',(oid,)).fetchone())
