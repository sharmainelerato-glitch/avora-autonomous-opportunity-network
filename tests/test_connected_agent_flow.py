"""Connected AI-plan -> human-invite -> acceptance -> approved payment instructions.
Offline tests intentionally do NOT simulate a real blockchain payment as success evidence.
"""
from uuid import uuid4
from test_app import client, auth
from test_near import provider, create_request


def unique_provider(headers,suffix):
    p=client.post('/api/providers',headers=headers,json={'name':'Zirconia'+suffix,'category':'Zirconia'+suffix,'kind':'Digital services','city':'Johannesburg','country':'South Africa','remote':True,'bio':'Zirconia'+suffix+' Zirconia'+suffix+' Zirconia'+suffix,'skills':'Zirconia'+suffix,'price':20,'capacity':5})
    assert p.status_code==200,p.text
    return p.json()['id']

def unique_request(headers,suffix):
    r=client.post('/api/requests',headers=headers,json={'title':'Zirconia'+suffix,'description':'Zirconia'+suffix+' Zirconia'+suffix,'category':'Zirconia'+suffix,'city':'Johannesburg','budget':500,'quantity':1})
    assert r.status_code==200,r.text
    return r.json()['id']


def test_agent_reviewed_plan_invites_and_payment_instructions():
    suffix=uuid4().hex[:12].translate(str.maketrans('0123456789','abcdefghij'))
    buyer=auth('Connected Buyer',f'connected-buyer-{suffix}@avora.test')
    seller=auth('Connected Seller',f'connected-seller-{suffix}@avora.test')
    outsider=auth('Connected Outsider',f'connected-out-{suffix}@avora.test')
    pid=unique_provider(seller, suffix)
    rid=unique_request(buyer, suffix)
    p=client.post('/api/near/agent/plan',headers=buyer,json={'request_id':rid,'target_near_each':'0.01'})
    assert p.status_code==200,p.text
    plan=p.json(); assert pid in plan['plan']['provider_ids']
    url=f"/api/near/agent/plans/{plan['plan_id']}/invite"
    assert client.post(url,headers=outsider).status_code==404
    activated=client.post(url,headers=buyer)
    assert activated.status_code==200,activated.text
    oid=activated.json()['opportunity_id']
    assert activated.json()['money_transferred'] is False
    assert client.post(url,headers=buyer).status_code==409
    pay=f'/api/near/opportunities/{oid}/payment-instructions'
    assert client.get(pay,headers=outsider).status_code==403
    assert client.get(pay,headers=buyer).status_code==409
    rescue=f'/api/near/opportunities/{oid}/rescue-suggestions'
    assert client.get(rescue,headers=outsider).status_code==403
    suggestion=client.get(rescue,headers=buyer)
    assert suggestion.status_code==200
    assert suggestion.json()['requires_human_action'] is True
    assert client.post(f'/api/near/opportunities/{oid}/respond',headers=seller,json={'accept':True,'payout_account':'joined-payee.testnet'}).status_code==200
    assert client.get(pay,headers=buyer).status_code==409
    assert client.post(f'/api/near/opportunities/{oid}/approve',headers=buyer).status_code==200
    instructions=client.get(pay,headers=buyer)
    assert instructions.status_code==200,instructions.text
    data=instructions.json()
    assert data['network']=='testnet'
    assert data['payer_must_sign_in_external_wallet'] is True
    assert data['payees'][0]['recipient']=='joined-payee.testnet'
    assert data['payees'][0]['amount_near']=='0.01'
    assert data['payees'][0]['verified'] is False
    assert not client.get(f'/api/near/opportunities/{oid}',headers=buyer).json()['proofs']


def test_invite_rechecks_policy_at_time_of_user_approval():
    suffix=uuid4().hex[:12].translate(str.maketrans('0123456789','abcdefghij'))
    buyer=auth('Policy Change Buyer',f'policy-change-{suffix}@avora.test')
    seller=auth('Policy Change Seller',f'policy-seller-{suffix}@avora.test')
    pid=unique_provider(seller, suffix)
    rid=unique_request(buyer, suffix)
    draft=client.post('/api/near/agent/plan',headers=buyer,json={'request_id':rid,'target_near_each':'0.01'})
    assert draft.status_code==200
    assert pid in draft.json()['plan']['provider_ids']
    client.put('/api/near/policy',headers=buyer,json={'max_total_near':'0.005','max_provider_near':'0.005','max_participants':4,'requires_human_approval':True})
    denied=client.post(f"/api/near/agent/plans/{draft.json()['plan_id']}/invite",headers=buyer)
    assert denied.status_code==422,denied.text
