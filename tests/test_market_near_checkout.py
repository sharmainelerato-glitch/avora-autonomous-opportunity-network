"""Direct NEAR testnet product checkout — independent of demonstration orders."""
import uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app, _attempts, _attempt_lock

c=TestClient(app)

def user(prefix):
    with _attempt_lock:_attempts.clear()
    r=c.post('/api/auth/register',json={'name':prefix,'email':f'{prefix}-{uuid.uuid4().hex}@example.test','password':'this-is-a-local-test-password-1234'})
    assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['token']}

def setup():
    seller=user('near-seller');buyer=user('near-buyer');outsider=user('near-outsider')
    business=c.post('/api/providers',headers=seller,json={'name':'Test NEAR Artisan '+uuid.uuid4().hex[:6], 'category':'Gifts','kind':'Products','city':'Durban','country':'South Africa','remote':False,'bio':'Real provider-owned example for testnet order checks.', 'skills':'gifts,design','price':30,'capacity':15})
    assert business.status_code==200,business.text
    pid=business.json()['id']
    item=c.post(f'/api/marketplace/providers/{pid}/listings',headers=seller,json={'title':'Handmade Gift Pack','description':'An illustrative original handmade bundle for testing.', 'price':35,'stock':9,'kind':'Products'})
    assert item.status_code==200,item.text
    return seller,buyer,outsider,pid,item.json()['id']

def test_near_checkout_buyer_consent_and_seller_setup():
    seller,buyer,outsider,pid,lid=setup()
    data={'lines':[{'listing_id':lid,'quantity':2}], 'note':'Testnet demo only'}
    assert c.post('/api/marketplace/near/orders',headers=buyer,json=data).status_code==422
    assert c.put(f'/api/marketplace/near/providers/{pid}/payout',headers=outsider,json={'account':'seller.testnet'}).status_code==403
    assert c.put(f'/api/marketplace/near/providers/{pid}/payout',headers=seller,json={'account':'seller.testnet'}).status_code==200
    assert c.post('/api/marketplace/near/orders',headers=buyer,json=data).status_code==422
    assert c.put(f'/api/marketplace/near/providers/{pid}/listings/{lid}/price',headers=outsider,json={'amount_near':'0.002'}).status_code==403
    assert c.put(f'/api/marketplace/near/providers/{pid}/listings/{lid}/price',headers=seller,json={'amount_near':'0.002'}).status_code==200
    quote=c.post('/api/marketplace/near/preview',headers=buyer,json=data)
    assert quote.status_code==200,quote.text
    assert quote.json()['amount_near']=='0.004'
    assert quote.json()['recipient']=='seller.testnet'
    assert c.post('/api/marketplace/near/orders',headers=seller,json=data).status_code==403
    r=c.post('/api/marketplace/near/orders',headers=buyer,json=data)
    assert r.status_code==200,r.text
    oid=r.json()['order_id']
    assert r.json()['status']=='NEAR_REVIEW'
    assert c.get(f'/api/marketplace/near/orders/{oid}',headers=outsider).status_code==403
    assert c.post(f'/api/marketplace/near/orders/{oid}/approve',headers=seller).status_code==403
    assert c.post(f'/api/marketplace/near/orders/{oid}/approve',headers=buyer).status_code==200
    assert c.post(f'/api/marketplace/near/orders/{oid}/approve',headers=buyer).status_code==409
    o=c.get(f'/api/marketplace/near/orders/{oid}',headers=buyer).json()
    assert o['status']=='NEAR_AWAITING_TRANSFER'
    assert o['tx_hash'] is None
    assert any(x['id']==oid and x['status']=='NEAR_AWAITING_TRANSFER' for x in c.get('/api/marketplace/orders',headers=seller).json())


def test_demo_storefront_cannot_receive_near():
    buyer=user('near-demo-buyer')
    p=next(x for x in c.get('/api/providers').json() if x['name']=='Naledi Bakes')
    l=next(x for x in c.get('/api/marketplace/listings',params={'provider_id':p['id']}).json() if x['title']=='Chocolate Celebration Cake')
    resp=c.post('/api/marketplace/near/orders',headers=buyer,json={'lines':[{'listing_id':l['id'],'quantity':1}]})
    assert resp.status_code==422


def test_near_verify_rejects_unapproved_and_wrong_proof(monkeypatch):
    import app.market_near as mod
    seller,buyer,other,pid,lid=setup()
    c.put(f'/api/marketplace/near/providers/{pid}/payout',headers=seller,json={'account':'seller.testnet'})
    c.put(f'/api/marketplace/near/providers/{pid}/listings/{lid}/price',headers=seller,json={'amount_near':'0.001'})
    order=c.post('/api/marketplace/near/orders',headers=buyer,json={'lines':[{'listing_id':lid,'quantity':1}]}).json()
    oid=order['order_id'];txhash='E'*43
    body={'tx_hash':txhash,'signer_account_id':'buyer.testnet'}
    assert c.post(f'/api/marketplace/near/orders/{oid}/verify',headers=buyer,json=body).status_code==409
    c.post(f'/api/marketplace/near/orders/{oid}/approve',headers=buyer)
    result={'transaction':{'hash':txhash,'signer_id':'buyer.testnet','receiver_id':'wrong.testnet','actions':[{'Transfer':{'deposit':order['amount_yocto']}}]},'transaction_outcome':{'outcome':{'status':{'SuccessValue':''}}},'status':{'SuccessValue':''},'final_execution_status':'FINAL'}
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'result':result}
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,*args,**kwargs):return Response()
    monkeypatch.setattr(mod.httpx,'AsyncClient',Client)
    resp=c.post(f'/api/marketplace/near/orders/{oid}/verify',headers=buyer,json=body)
    assert resp.status_code==422
    assert c.get(f'/api/marketplace/near/orders/{oid}',headers=buyer).json()['status']=='NEAR_AWAITING_TRANSFER'
    result['transaction']['receiver_id']='seller.testnet'
    assert c.post(f'/api/marketplace/near/orders/{oid}/verify',headers=other,json=body).status_code==403
    verified=c.post(f'/api/marketplace/near/orders/{oid}/verify',headers=buyer,json=body)
    assert verified.status_code==200,verified.text
    assert verified.json()['status']=='NEAR_VERIFIED'
    assert verified.json()['tx_hash']==txhash
    assert c.post(f'/api/marketplace/near/orders/{oid}/verify',headers=buyer,json=body).status_code==409
    assert c.get(f'/api/marketplace/near/orders/{oid}',headers=seller).status_code==200


def test_cancel_only_before_approval_and_only_by_buyer():
    seller,buyer,outsider,pid,lid=setup()
    c.put(f'/api/marketplace/near/providers/{pid}/payout',headers=seller,json={'account':'seller.testnet'})
    c.put(f'/api/marketplace/near/providers/{pid}/listings/{lid}/price',headers=seller,json={'amount_near':'0.001'})
    o=c.post('/api/marketplace/near/orders',headers=buyer,json={'lines':[{'listing_id':lid,'quantity':1}]}).json()
    oid=o['order_id']
    assert c.post(f'/api/marketplace/near/orders/{oid}/cancel',headers=seller).status_code==403
    cancelled=c.post(f'/api/marketplace/near/orders/{oid}/cancel',headers=buyer)
    assert cancelled.status_code==200,cancelled.text
    assert cancelled.json()['payment_status']=='CANCELLED'
    assert c.post(f'/api/marketplace/near/orders/{oid}/approve',headers=buyer).status_code==409
    assert c.post(f'/api/marketplace/near/orders/{oid}/cancel',headers=buyer).status_code==409


def test_after_verified_stock_fulfillment_and_issue(monkeypatch):
    import app.market_near as mod
    seller,buyer,outsider,pid,lid=setup()
    c.put(f'/api/marketplace/near/providers/{pid}/payout',headers=seller,json={'account':'seller.testnet'})
    c.put(f'/api/marketplace/near/providers/{pid}/listings/{lid}/price',headers=seller,json={'amount_near':'0.001'})
    o=c.post('/api/marketplace/near/orders',headers=buyer,json={'lines':[{'listing_id':lid,'quantity':2}]}).json()
    oid=o['order_id']; txhash='G'*43
    body={'tx_hash':txhash,'signer_account_id':'buyer.testnet'}
    assert c.post(f'/api/marketplace/near/orders/{oid}/fulfill',headers=seller,json={'note':'Sent'}).status_code==409
    assert c.post(f'/api/marketplace/near/orders/{oid}/issue',headers=buyer,json={'message':'I need delivery details'}).status_code==409
    c.post(f'/api/marketplace/near/orders/{oid}/approve',headers=buyer)
    assert c.post(f'/api/marketplace/near/orders/{oid}/cancel',headers=buyer).status_code==409
    result={'transaction':{'hash':txhash,'signer_id':'buyer.testnet','receiver_id':'seller.testnet','actions':[{'Transfer':{'deposit':o['amount_yocto']}}]},'transaction_outcome':{'outcome':{'status':{'SuccessValue':''}}},'status':{'SuccessValue':''},'final_execution_status':'FINAL'}
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'result':result}
    class Client:
        def __init__(self,**kw):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*x):pass
        async def post(self,*x,**kw):return Response()
    monkeypatch.setattr(mod.httpx,'AsyncClient',Client)
    ver=c.post(f'/api/marketplace/near/orders/{oid}/verify',headers=buyer,json=body)
    assert ver.status_code==200,ver.text
    assert ver.json()['fulfillment']['status']=='AWAITING_FULFILLMENT'
    assert any(ev['event']=='VERIFIED' for ev in ver.json()['events'])
    product=c.get(f'/api/marketplace/listings/{lid}').json()
    assert product['stock']==7
    assert c.post(f'/api/marketplace/near/orders/{oid}/fulfill',headers=buyer,json={'note':'No'}).status_code==403
    fulfilled=c.post(f'/api/marketplace/near/orders/{oid}/fulfill',headers=seller,json={'note':'Dispatched for delivery'})
    assert fulfilled.status_code==200,fulfilled.text
    assert fulfilled.json()['fulfillment']['status']=='FULFILLED'
    assert c.post(f'/api/marketplace/near/orders/{oid}/fulfill',headers=seller,json={'note':'Again'}).status_code==409
    assert c.post(f'/api/marketplace/near/orders/{oid}/issue',headers=outsider,json={'message':'This is a fake report'}).status_code==403
    issue=c.post(f'/api/marketplace/near/orders/{oid}/issue',headers=buyer,json={'message':'The product arrived damaged.'})
    assert issue.status_code==200,issue.text
    assert issue.json()['issue']['status']=='OPEN'
    assert c.post(f'/api/marketplace/near/orders/{oid}/issue',headers=buyer,json={'message':'A second issue report here.'}).status_code==409
    assert c.get(f'/api/marketplace/near/orders/{oid}',headers=seller).json()['issue'] is not None
