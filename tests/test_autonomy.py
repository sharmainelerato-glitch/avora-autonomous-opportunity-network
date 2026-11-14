"""Autonomous Business agent planning and financial guardrails (offline tests)."""
from test_app import client, auth
from test_near import provider, create_request


def test_agent_plan_limits_treasury_review_and_authorization():
    buyer=auth('Treasury Buyer','treasury-buyer@avora.test')
    seller=auth('Treasury Provider','treasury-provider@avora.test')
    outsider=auth('Treasury Stranger','treasury-other@avora.test')
    pid=provider(seller,'Workshop shelving and carpentry')
    rid=create_request(buyer)
    assert client.get('/api/near/policy',headers=outsider).status_code==200
    assert client.post('/api/near/agent/plan',headers=outsider,json={'request_id':rid}).status_code==403
    plan=client.post('/api/near/agent/plan',headers=buyer,json={'request_id':rid,'target_near_each':'0.01'})
    assert plan.status_code==200,plan.text
    assert pid in plan.json()['plan']['provider_ids']
    assert plan.json()['assistant']['mode'] in ('rules_only','ai_unavailable','llm')
    assert plan.json()['committed'] is False
    assert client.get('/api/near/agent/plans',headers=outsider).json()==[]
    assert len(client.get('/api/near/agent/plans',headers=buyer).json())==1
    assert client.put('/api/near/policy',headers=buyer,json={
        'max_total_near':'0.5','max_provider_near':'0.1',
        'max_participants':2,'requires_human_approval':False}).status_code==422
    assert client.put('/api/near/policy',headers=buyer,json={
        'max_total_near':'0.02','max_provider_near':'0.01',
        'max_participants':1,'requires_human_approval':True}).status_code==200
    assert client.post('/api/near/opportunities',headers=buyer,json={
        'request_id':rid,'provider_ids':[pid],'amount_near_each':'0.02'}).status_code==422
    result=client.post('/api/near/opportunities',headers=buyer,json={
        'request_id':rid,'provider_ids':[pid],'amount_near_each':'0.01'})
    assert result.status_code==200,result.text
    oid=result.json()['id']
    assert client.get(f'/api/near/opportunities/{oid}/agent-review',headers=outsider).status_code==403
    review=client.get(f'/api/near/opportunities/{oid}/agent-review',headers=buyer).json()
    assert review['safe_to_request_approval'] is False
    assert review['pending_acceptances']==[pid]
    assert client.post(f'/api/near/opportunities/{oid}/respond',headers=seller,json={'accept':True,'payout_account':'treasury-provider.testnet'}).status_code==200
    review=client.get(f'/api/near/opportunities/{oid}/agent-review',headers=buyer).json()
    assert review['safe_to_request_approval'] is True
    # Tightening policy requires a fresh review: buyer cannot approve outside budget.
    client.put('/api/near/policy',headers=buyer,json={
        'max_total_near':'0.005','max_provider_near':'0.005','max_participants':1,'requires_human_approval':True})
    assert client.post(f'/api/near/opportunities/{oid}/approve',headers=buyer).status_code==422
    treasury=client.get('/api/near/treasury',headers=buyer).json()
    assert treasury['custodied_balance_near']=='0'
    assert treasury['verified_outgoing_near']=='0'
    assert treasury['agreements'] and not treasury['transactions']
