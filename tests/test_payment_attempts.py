"""Payment attempt logs are not proofs; wallet custody and automatic settlement are excluded."""
from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app, _attempts, _attempt_lock

client=TestClient(app)

def make_user(tag):
    with _attempt_lock:_attempts.clear()
    name=f'{tag}-{uuid4().hex[:8]}'
    res=client.post('/api/auth/register',json={'name':name,'email':f'{name}@example.test','password':'testing-wallet-custody-1234'})
    assert res.status_code==200,res.text
    return {'Authorization':'Bearer '+res.json()['token']}

def make_provider(headers):
    res=client.post('/api/providers',headers=headers,json={
        'name':'Wallet Test Provider '+uuid4().hex[:6],'category':'Digital services',
        'kind':'Digital services','city':'Johannesburg','country':'South Africa',
        'remote':True,'bio':'Independent provider for opportunity testnet payments.',
        'skills':'frontend,design,services','price':30,'capacity':2})
    assert res.status_code==200,res.text
    return res.json()['id']

def test_wallet_attempt_requires_approval_and_never_marks_paid():
    buyer=make_user('paybuyer')
    seller=make_user('payseller')
    stranger=make_user('payoutsider')
    pid=make_provider(seller)
    req=client.post('/api/requests',headers=buyer,json={
        'title':'Build storefront with NEAR','description':'Build a shop for local small businesses with payment design',
        'category':'Digital services','city':'Johannesburg','budget':900,'quantity':1})
    assert req.status_code==200,req.text
    opp=client.post('/api/near/opportunities',headers=buyer,json={
        'request_id':req.json()['id'],'provider_ids':[pid],'amount_near_each':'0.01'})
    assert opp.status_code==200,opp.text
    oid=opp.json()['id']
    url=f'/api/near/opportunities/{oid}'
    attempt_url=url+'/payment-attempts'
    assert client.post(attempt_url,headers=buyer,json={'provider_id':pid}).status_code==409
    accepted=client.post(url+'/respond',headers=seller,json={'accept':True,'payout_account':'example.testnet'})
    assert accepted.status_code==200,accepted.text
    assert client.post(attempt_url,headers=buyer,json={'provider_id':pid}).status_code==409
    assert client.post(url+'/approve',headers=buyer).status_code==200
    assert client.post(attempt_url,headers=stranger,json={'provider_id':pid}).status_code==403
    assert client.post(attempt_url,headers=seller,json={'provider_id':pid}).status_code==403
    a=client.post(attempt_url,headers=buyer,json={'provider_id':pid})
    assert a.status_code==200,a.text
    assert a.json()['status']=='initiated'
    assert a.json()['network']=='testnet'
    assert a.json()['recipient']=='example.testnet'
    assert client.post(attempt_url,headers=buyer,json={'provider_id':pid}).status_code==409
    status=client.post(attempt_url+f"/{a.json()['attempt_id']}/status",headers=buyer,json={'status':'wallet_returned'})
    assert status.status_code==200 and status.json()['verified'] is False
    ledger=client.get(url+'/settlement',headers=buyer)
    assert ledger.status_code==200,ledger.text
    assert ledger.json()['settlement']['verified_payees']==0
    assert ledger.json()['settlement']['pending_payees']==1
    assert ledger.json()['attempts'][0]['status']=='wallet_returned'
    assert client.get(url+'/settlement',headers=stranger).status_code==403
    assert client.post(attempt_url,headers=buyer,json={'provider_id':pid}).status_code==409
    assert client.post(attempt_url+f"/{a.json()['attempt_id']}/status",headers=stranger,json={'status':'failed'}).status_code==403
    failed=client.post(attempt_url+f"/{a.json()['attempt_id']}/status",headers=buyer,json={'status':'wallet_rejected'})
    assert failed.status_code==200
    retry=client.post(attempt_url,headers=buyer,json={'provider_id':pid})
    assert retry.status_code==200,retry.text
    assert retry.json()['attempt_id'] != a.json()['attempt_id']
    assert client.get(url,headers=buyer).json()['onchain_verified_count']==0
