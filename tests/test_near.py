"""NEAR coordination authorization, rescue, and mocked truthful RPC proof checks.
Mocked responses here are TEST FIXTURES, never evidence of a live blockchain transaction.
"""
from test_app import client, auth
from unittest.mock import patch
from app.near_workflows import amount_yocto


def provider(headers,name):
    r=client.post('/api/providers',headers=headers,json={
        'name':name,'category':'Carpentry','city':'Johannesburg','country':'South Africa',
        'bio':'Custom artisan furniture and repairs made locally','skills':'carpentry furniture repair',
        'price':100,'capacity':2})
    assert r.status_code==200,r.text
    return r.json()['id']


def create_request(headers):
    r=client.post('/api/requests',headers=headers,json={
        'title':'Community workshop shelving','description':'Need shelf construction and installation at a community workshop',
        'category':'Carpentry','city':'Johannesburg','budget':800,'quantity':3})
    assert r.status_code==200,r.text
    return r.json()['id']


def test_near_consent_rescue_and_proofs():
    buyer=auth('NEAR Buyer','nearbuyer@avora.test')
    a=auth('Provider A','near-a@avora.test')
    b=auth('Provider B','near-b@avora.test')
    c=auth('Provider C','near-c@avora.test')
    stranger=auth('Outsider','near-out@avora.test')
    aid=provider(a,'AVORA Carpentry A')
    bid=provider(b,'AVORA Carpentry B')
    cid=provider(c,'AVORA Carpentry C')
    rid=create_request(buyer)
    x={'request_id':rid,'provider_ids':[aid,bid],'amount_near_each':'0.01'}
    assert client.post('/api/near/opportunities',headers=stranger,json=x).status_code==403
    assert client.post('/api/near/opportunities',headers=buyer,json={**x,'provider_ids':[aid,aid]}).status_code==422
    assert client.post('/api/near/opportunities',headers=buyer,json={**x,'amount_near_each':'500'}).status_code==422
    result=client.post('/api/near/opportunities',headers=buyer,json=x)
    assert result.status_code==200,result.text
    oid=result.json()['id']
    url=f'/api/near/opportunities/{oid}'
    assert client.get(url,headers=stranger).status_code==403
    assert client.post(url+'/approve',headers=buyer).status_code==409
    assert client.post(url+'/respond',headers=stranger,json={'accept':True,'payout_account':'out.testnet'}).status_code==403
    assert client.post(url+'/respond',headers=a,json={'accept':True,'payout_account':'a.testnet'}).status_code==200
    declined=client.post(url+'/respond',headers=b,json={'accept':False})
    assert declined.status_code==200 and declined.json()['status']=='needs_rescue'
    assert client.post(url+'/approve',headers=buyer).status_code==409
    assert client.post(url+'/replace',headers=a,json={'outgoing_provider_id':bid,'incoming_provider_id':cid}).status_code==403
    rescue=client.post(url+'/replace',headers=buyer,json={'outgoing_provider_id':bid,'incoming_provider_id':cid})
    assert rescue.status_code==200,rescue.text
    assert rescue.json()['revision']==2 and all(p['status']=='invited' for p in rescue.json()['participants'])
    assert client.post(url+'/respond',headers=a,json={'accept':True,'payout_account':'a.testnet'}).status_code==200
    assert client.post(url+'/respond',headers=c,json={'accept':True,'payout_account':'c.testnet'}).json()['status']=='ready'
    assert client.post(url+'/approve',headers=a).status_code==403
    assert client.post(url+'/approve',headers=buyer).json()['status']=='approved'
    assert client.post(url+'/replace',headers=buyer,json={'outgoing_provider_id':aid,'incoming_provider_id':bid}).status_code==409
    wrong_hash='0'*44
    assert client.post(url+'/verify-transfer',headers=buyer,json={'provider_id':aid,'tx_hash':wrong_hash,'signer_account_id':'buyer.testnet'}).status_code==422
    good_hash='3'*44
    proof={'provider_id':aid,'tx_hash':good_hash,'signer_account_id':'buyer.testnet'}
    fake_data={'result':{'final_execution_status':'FINAL','status':{'SuccessValue':''},'transaction':{
        'hash':good_hash,'signer_id':'buyer.testnet','receiver_id':'a.testnet',
        'actions':[{'Transfer':{'deposit':amount_yocto('0.01')}}]},
        'transaction_outcome':{'outcome':{'status':{'SuccessReceiptId':'x'}}}}}
    class FakeResponse:
        def raise_for_status(self):pass
        def json(self):return fake_data
    class FakeClient:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,*args,**kwargs):return FakeResponse()
    with patch('app.near_workflows.httpx.AsyncClient',FakeClient):
        # Wrong recipient cannot be accepted.
        fake_data['result']['transaction']['receiver_id']='wrong.testnet'
        assert client.post(url+'/verify-transfer',headers=buyer,json=proof).status_code==422
        fake_data['result']['transaction']['receiver_id']='a.testnet'
        fake_data['result']['transaction']['actions'][0]['Transfer']['deposit']=amount_yocto('0.02')
        assert client.post(url+'/verify-transfer',headers=buyer,json=proof).status_code==422
        fake_data['result']['transaction']['actions'][0]['Transfer']['deposit']=amount_yocto('0.01')
        verified=client.post(url+'/verify-transfer',headers=buyer,json=proof)
        assert verified.status_code==200,verified.text
        assert verified.json()['status']=='partially_verified'
        assert client.post(url+'/verify-transfer',headers=buyer,json=proof).status_code==409
    assert client.get(url,headers=buyer).json()['onchain_verified_count']==1
