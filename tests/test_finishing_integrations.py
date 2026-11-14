"""Regression tests for real refund-proof semantics, private calendar export, and evidence reviews."""
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from test_market_near_checkout import setup as near_setup, c
from test_operations import auth,new_provider


def test_calendar_export_requires_accepted_appointment():
    buyer=auth('CalBuyer');seller=auth('CalSeller');other=auth('CalOther');pid=new_provider(seller)
    listings=c.get('/api/marketplace/listings',params={'provider_id':pid}).json()
    lid=next(x['id'] for x in listings if x['kind']!='Products')
    payload={'provider_id':pid,'listing_id':lid,'requested_start':(datetime.now(timezone.utc)+timedelta(days=3)).isoformat(),'note':'Consult about my business site'}
    bid=c.post('/api/operations/bookings',headers=buyer,json=payload).json()['id']
    path=f'/api/operations/bookings/{bid}/calendar.ics'
    assert c.get(path,headers=other).status_code==403
    assert c.get(path,headers=buyer).status_code==409
    assert c.post(f'/api/operations/bookings/{bid}/decision',headers=seller,json={'status':'ACCEPTED'}).status_code==200
    r=c.get(path,headers=buyer)
    assert r.status_code==200
    assert 'text/calendar' in r.headers['content-type']
    assert 'BEGIN:VCALENDAR' in r.text and 'UID:avora-booking-' in r.text
    assert 'DTSTART:' in r.text and 'DTEND:' in r.text


def test_business_review_is_pending_not_identity_verification(monkeypatch):
    seller=auth('ReviewOwner');outsider=auth('ReviewOther');pid=new_provider(seller)
    endpoint=f'/api/operations/verification/{pid}'
    payload={'registry_reference':'CIPC demo reference','public_evidence_url':'https://example.org/public/business/123','note':'Review public business info only'}
    assert c.post(endpoint,headers=outsider,json=payload).status_code==403
    assert c.post(endpoint,headers=seller,json={**payload,'public_evidence_url':'http://example.com'}).status_code==422
    assert c.post(endpoint,headers=seller,json=payload).json()['status']=='PENDING'
    status=c.get(endpoint,headers=seller).json()
    assert status['independently_identity_verified'] is False
    assert status['review']['status']=='PENDING'
    monkeypatch.delenv('AVORA_VERIFICATION_OPERATOR_TOKEN',raising=False)
    assert c.post(endpoint+'/operator-review',json={'status':'REVIEWED'}).status_code==403
    monkeypatch.setenv('AVORA_VERIFICATION_OPERATOR_TOKEN','only-testing-operator-secret-ABC-9876')
    assert c.post(endpoint+'/operator-review',json={'status':'REVIEWED'},headers={'x-avora-operator-token':'wrong'}).status_code==403
    reviewed=c.post(endpoint+'/operator-review',json={'status':'REVIEWED','note':'Reviewed public link'},headers={'x-avora-operator-token':'only-testing-operator-secret-ABC-9876'})
    assert reviewed.status_code==200,reviewed.text
    assert reviewed.json()['independently_identity_verified'] is False
    assert c.get(endpoint,headers=seller).json()['review']['status']=='REVIEWED'


def test_refund_requires_actual_reverse_onchain_payment(monkeypatch):
    import app.market_near as market
    import app.operations as operations
    seller,buyer,outsider,pid,lid=near_setup()
    assert c.put(f'/api/marketplace/near/providers/{pid}/payout',headers=seller,json={'account':'seller.testnet'}).status_code==200
    assert c.put(f'/api/marketplace/near/providers/{pid}/listings/{lid}/price',headers=seller,json={'amount_near':'0.001'}).status_code==200
    creation=c.post('/api/marketplace/near/orders',headers=buyer,json={'lines':[{'listing_id':lid,'quantity':1}]}).json()
    oid=creation['order_id']
    c.post(f'/api/marketplace/near/orders/{oid}/approve',headers=buyer)
    tx1='F'*43;tx2='J'*43; amount=creation['amount_yocto']
    state={'hash':tx1,'signer':'buyer.testnet','recipient':'seller.testnet','amount':amount}
    class Response:
        def raise_for_status(self):pass
        def json(self):
            return {'result':{'transaction':{'hash':state['hash'],'signer_id':state['signer'],'receiver_id':state['recipient'],'actions':[{'Transfer':{'deposit':state['amount']}}]},
                              'transaction_outcome':{'outcome':{'status':{'SuccessValue':''}}},'status':{'SuccessValue':''},'final_execution_status':'FINAL'}}
    class Client:
        def __init__(self,**kw):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def post(self,*a,**kw):return Response()
    monkeypatch.setattr(market.httpx,'AsyncClient',Client)
    assert c.post(f'/api/marketplace/near/orders/{oid}/verify',headers=buyer,json={'tx_hash':tx1,'signer_account_id':'buyer.testnet'}).status_code==200
    rid=c.post(f'/api/operations/orders/{oid}/refund-request',headers=buyer,json={'reason':'Received damaged products, requesting full refund'}).json()['id']
    proof=f'/api/operations/refund-requests/{rid}/verify'
    res0=c.post(proof,headers=buyer,json={'tx_hash':tx2,'signer_account_id':'seller.testnet'});assert res0.status_code==409,res0.text
    assert c.post(f'/api/operations/refund-requests/{rid}/decision',headers=seller,json={'decision':'APPROVED_MANUAL'}).status_code==200
    instructions=c.get(f'/api/operations/refund-requests/{rid}/instructions',headers=buyer).json()
    assert instructions['from_account']=='seller.testnet'
    assert instructions['to_account']=='buyer.testnet'
    assert instructions['amount_near']=='0.001'
    assert c.get(f'/api/operations/refund-requests/{rid}/instructions',headers=outsider).status_code==403
    assert c.post(proof,headers=outsider,json={'tx_hash':tx2,'signer_account_id':'seller.testnet'}).status_code==403
    assert c.post(proof,headers=seller,json={'tx_hash':tx2,'signer_account_id':'buyer.testnet'}).status_code==422
    state.update(hash=tx2,signer='seller.testnet',recipient='buyer.testnet',amount='999')
    assert c.post(proof,headers=seller,json={'tx_hash':tx2,'signer_account_id':'seller.testnet'}).status_code==422
    state['amount']=amount
    verified=c.post(proof,headers=seller,json={'tx_hash':tx2,'signer_account_id':'seller.testnet'})
    assert verified.status_code==200,verified.text
    assert verified.json()['status']=='REFUNDED_VERIFIED'
    assert verified.json()['funds_returned_verified'] is True
    assert c.post(proof,headers=seller,json={'tx_hash':tx2,'signer_account_id':'seller.testnet'}).status_code==409


def test_courier_lookup_requires_ownership_and_real_api_key(monkeypatch):
    import app.operations as op
    from app.main import conn
    seller,buyer,other,pid,lid=near_setup()
    # Create a real order record through ordinary checkout, then mark it paid in test DB only.
    c.put(f'/api/marketplace/near/providers/{pid}/payout',headers=seller,json={'account':'seller.testnet'})
    c.put(f'/api/marketplace/near/providers/{pid}/listings/{lid}/price',headers=seller,json={'amount_near':'0.001'})
    order_id=c.post('/api/marketplace/near/orders',headers=buyer,json={'lines':[{'listing_id':lid,'quantity':1}]}).json()['order_id']
    with conn() as db:
        db.execute("UPDATE market_near_orders SET status='VERIFIED' WHERE order_id=?",(order_id,))
    c.put(f'/api/operations/orders/{order_id}/delivery',headers=seller,json={'status':'DISPATCHED','carrier':'USPS','reference':'EZ1000000001','note':'Sample parcel tracking'} )
    endpoint=f'/api/operations/orders/{order_id}/carrier-lookup'
    assert c.get(endpoint,headers=other).status_code==403
    monkeypatch.delenv('EASYPOST_API_KEY',raising=False)
    assert c.get(endpoint,headers=buyer).status_code==503
    monkeypatch.setenv('EASYPOST_API_KEY','test-key')
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'trackers':[{'tracking_code':'EZ1000000001','carrier':'USPS','status':'in_transit','mode':'test','tracking_details':[{'message':'Sample USPS scan','datetime':'2026-11-15T10:00:00Z'}]}]}
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def get(self,url,**kwargs):
            assert url=='https://api.easypost.com/v2/trackers'
            assert kwargs['auth']==('test-key','')
            return Response()
    monkeypatch.setattr(op.httpx,'AsyncClient',Client)
    result=c.get(endpoint,headers=buyer)
    assert result.status_code==200,result.text
    assert result.json()['source']=='EasyPost API'
    assert result.json()['mode']=='test'
    assert result.json()['status']=='in_transit'
