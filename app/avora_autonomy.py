"""AVORA bounded agent orchestration and testnet treasury observability.

No autonomous signing, money custody, or fictional LLM output. Every financial
recommendation is advisory; actual funds move only in an external user wallet.
"""
from __future__ import annotations
import json
from decimal import Decimal
from typing import Optional
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from app.near_workflows import amount_yocto, YOCTO

MAX_CAP_YOCTO = 2 * YOCTO

class PolicyIn(BaseModel):
    max_total_near: str = Field(default='0.25', max_length=40)
    max_provider_near: str = Field(default='0.10', max_length=40)
    max_participants: int = Field(default=4, ge=1, le=6)
    requires_human_approval: bool = True

class AgentPlanIn(BaseModel):
    request_id: int = Field(gt=0)
    target_near_each: str = Field(default='0.01',max_length=40)


def money(n):
    return str(Decimal(int(n))/YOCTO)


def load_policy(db,uid):
    row=db.execute('SELECT * FROM avora_policies WHERE user_id=?',(uid,)).fetchone()
    if row:return dict(row)
    return {'user_id':uid,'max_total_yocto':str(int(Decimal('0.25')*YOCTO)),
            'max_provider_yocto':str(int(Decimal('0.10')*YOCTO)),'max_participants':4,'requires_human_approval':1}


def check_policy(db,uid,pids,amount):
    policy=load_policy(db,uid)
    if len(pids)>policy['max_participants']:
        raise HTTPException(422,'Provider count exceeds buyer treasury policy')
    if int(amount)>int(policy['max_provider_yocto']):
        raise HTTPException(422,'Per-provider NEAR amount exceeds buyer treasury policy')
    total=int(amount)*len(pids)
    if total>int(policy['max_total_yocto']):
        raise HTTPException(422,'Proposed NEAR allocation exceeds buyer treasury policy')
    return policy


def install_avora_autonomy(app,conn,current,assemble,ai_explain,candidate_score):
    with conn() as db:
        db.executescript('''
CREATE TABLE IF NOT EXISTS avora_policies (
 user_id INTEGER PRIMARY KEY REFERENCES users(id), max_total_yocto TEXT NOT NULL,
 max_provider_yocto TEXT NOT NULL,max_participants INTEGER NOT NULL,
 requires_human_approval INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS avora_agent_plans (
 id INTEGER PRIMARY KEY, buyer_id INTEGER NOT NULL REFERENCES users(id),
 request_id INTEGER NOT NULL REFERENCES requests(id), provider_ids_json TEXT NOT NULL,
 target_yocto TEXT NOT NULL, projected_total_yocto TEXT NOT NULL,
 analysis_json TEXT NOT NULL, created INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'proposed');
''')

    @app.get('/api/near/policy')
    def policy(u=Depends(current)):
        with conn() as db:p=load_policy(db,u['id'])
        return {'max_total_near':money(p['max_total_yocto']),
                'max_provider_near':money(p['max_provider_yocto']),
                'max_participants':p['max_participants'],
                'requires_human_approval':True,'mode':'noncustodial_testnet'}

    @app.put('/api/near/policy')
    def update_policy(x:PolicyIn,u=Depends(current)):
        if not x.requires_human_approval:
            raise HTTPException(422,'Human approval cannot be disabled in this MVP')
        total=amount_yocto(x.max_total_near);single=amount_yocto(x.max_provider_near)
        if int(total)>MAX_CAP_YOCTO:raise HTTPException(422,'Total testnet cap is 2 NEAR')
        if int(single)>int(total):raise HTTPException(422,'Per-provider cap cannot exceed total cap')
        with conn() as db:
            db.execute('''INSERT INTO avora_policies(user_id,max_total_yocto,max_provider_yocto,max_participants,requires_human_approval)
                        VALUES(?,?,?,?,1) ON CONFLICT(user_id) DO UPDATE SET max_total_yocto=excluded.max_total_yocto,
                        max_provider_yocto=excluded.max_provider_yocto,max_participants=excluded.max_participants''',
                        (u['id'],total,single,x.max_participants))
        return policy(u)

    @app.get('/api/near/treasury')
    def treasury(u=Depends(current)):
        with conn() as db:
            p=load_policy(db,u['id'])
            agreements=[dict(r) for r in db.execute('''SELECT id, status, amount_yocto, revision,created
              FROM near_opportunities WHERE buyer_id=? ORDER BY id DESC LIMIT 100''',(u['id'],))]
            payouts=[dict(r) for r in db.execute('''SELECT pr.opportunity_id,pr.provider_id,pr.tx_hash,pr.receiver_account,
                pr.amount_yocto,pr.verified_at FROM near_proofs pr
                JOIN near_opportunities op ON op.id=pr.opportunity_id WHERE op.buyer_id=?
                ORDER BY pr.verified_at DESC LIMIT 100''',(u['id'],))]
        settled=sum(int(r['amount_yocto']) for r in payouts)
        pending=sum(int(o['amount_yocto']) for o in agreements if o['status'] in ('invited','ready','needs_rescue','approved','partially_verified'))
        return {'network':'testnet','custodied_balance_near':'0', 'verified_outgoing_near':money(settled),
                'proposed_per_provider_near':money(pending),'transactions':[{**v,'amount_near':money(v['amount_yocto'])} for v in payouts],
                'agreements':[{**a,'amount_near_each':money(a['amount_yocto'])} for a in agreements],
                'disclosure':'Transaction history is RPC-verified outgoing testnet transfers; this application never holds funds. Proposed amounts are not balances.'}

    @app.post('/api/near/agent/plan')
    async def agent_plan(x:AgentPlanIn,u=Depends(current)):
        from time import time
        target=amount_yocto(x.target_near_each)
        with conn() as db:
            req=db.execute('SELECT * FROM requests WHERE id=?',(x.request_id,)).fetchone()
            if not req:raise HTTPException(404,'Request not found')
            if req['buyer_id']!=u['id']:raise HTTPException(403,'Only buyer can request an operating plan')
            if req['status']!='open':raise HTTPException(409,'Request no longer open')
            # No seeded/unowned or self-owned provider can receive invitations.
            people=[dict(r) for r in db.execute('SELECT * FROM providers WHERE owner_id IS NOT NULL AND owner_id !=?',(u['id'],))]
            ranked=assemble(dict(req),people)
            policy=load_policy(db,u['id'])
            ids=[p['provider_id'] for p in ranked['plan']][:policy['max_participants']]
            if ids:check_policy(db,u['id'],ids,target)
            plan={'request_id':x.request_id,'provider_ids':ids,'proposed_near_each':money(target),
                  'proposed_total_near':money(int(target)*len(ids)),'needs_human_approval':True,
                  'covered_units':sum(p['units'] for p in ranked['plan'] if p['provider_id'] in ids),
                  'requested_units':req['quantity'],'estimated_fiat_usd':ranked['estimated_total_usd'],
                  'fiat_budget_usd':req['budget'],'fiat_exchange_warning':'USD plan and testnet NEAR demonstration amounts are independent; no conversion or price equivalence is claimed.',
                  'ranked_providers':[{'provider_id':p['provider_id'],'name':p['name'],'units':p['units'],'match_score':p['fit']} for p in ranked['plan'] if p['provider_id'] in ids],
                  'constraints':['Registered independent providers only','Capacity and locality filters','Per-party and total testnet limits','Human acceptance and buyer approval required','No onchain action performed']}
            # Grounded explanation is optional. The rules-only result never pretends to be model output.
            explanation=await ai_explain('You are AVORA autonomous-business planning analyst. Compare sales fulfilment, procurement matching, capacity, risk and contingency. Only discuss supplied evidence. Do not imply money was moved.',plan)
            cur=db.execute('''INSERT INTO avora_agent_plans(buyer_id,request_id,provider_ids_json,target_yocto,projected_total_yocto,analysis_json,created)
                        VALUES(?,?,?,?,?,?,?)''',(u['id'],x.request_id,json.dumps(ids),target,str(int(target)*len(ids)),json.dumps({'plan':plan,'assistant':explanation}),int(time())))
            return {'plan_id':cur.lastrowid,'plan':plan,'assistant':explanation,'committed':False}

    @app.post('/api/near/agent/plans/{plan_id}/invite')
    def activate_reviewed_plan(plan_id:int,u=Depends(current)):
        '''Promote a saved draft into real invitations only after a buyer click.

        Revalidate provider ownership, current availability, budget policy and request
        state at commit time. A repeated click cannot create another coalition.
        '''
        from app.near_workflows import now
        with conn() as db:
            plan=db.execute('SELECT * FROM avora_agent_plans WHERE id=? AND buyer_id=?',(plan_id,u['id'])).fetchone()
            if not plan:raise HTTPException(404,'Owned agent plan not found')
            if plan['status']!='proposed':raise HTTPException(409,'This plan has already been activated')
            req=db.execute('SELECT * FROM requests WHERE id=?',(plan['request_id'],)).fetchone()
            if not req or req['buyer_id']!=u['id'] or req['status']!='open':raise HTTPException(409,'Request no longer open')
            ids=json.loads(plan['provider_ids_json'])
            if not ids or len(ids)>6 or len(set(ids))!=len(ids):raise HTTPException(422,'Plan has no valid independent providers')
            check_policy(db,u['id'],ids,plan['target_yocto'])
            for pid in ids:
                p=db.execute('SELECT owner_id FROM providers WHERE id=?',(pid,)).fetchone()
                if not p or p['owner_id'] is None or p['owner_id']==u['id']:
                    raise HTTPException(409,'One of the proposed providers is no longer eligible')
            cur=db.execute('INSERT INTO near_opportunities(request_id,buyer_id,amount_yocto,created) VALUES(?,?,?,?)',
                           (plan['request_id'],u['id'],plan['target_yocto'],now()))
            oid=cur.lastrowid
            for pid in ids:db.execute('INSERT INTO near_participants(opportunity_id,provider_id) VALUES(?,?)',(oid,pid))
            db.execute("UPDATE avora_agent_plans SET status='invited' WHERE id=?",(plan_id,))
            db.execute('INSERT INTO near_audit(opportunity_id,actor_id,action,info,created) VALUES(?,?,?,?,?)',
                (oid,u['id'],'reviewed_agent_plan_invited',json.dumps({'plan_id':plan_id,'provider_ids':ids,'amount_yocto_each':plan['target_yocto']}),now()))
            return {'opportunity_id':oid,'plan_id':plan_id,'status':'invited','provider_ids':ids,
                    'amount_near_each':money(plan['target_yocto']), 'money_transferred':False,
                    'message':'Invitations created. Each provider must accept; buyer must separately approve payment terms.'}

    @app.get('/api/near/agent/plans')
    def my_plans(u=Depends(current)):
        with conn() as db:
            records=db.execute('SELECT * FROM avora_agent_plans WHERE buyer_id=? ORDER BY id DESC LIMIT 15',(u['id'],))
            return [{**dict(r),'analysis':json.loads(r['analysis_json'])} for r in records]

    @app.get('/api/near/opportunities/{oid}/rescue-suggestions')
    def rescue_suggestions(oid:int,u=Depends(current)):
        """Human-reviewed, data-grounded alternatives for a disrupted coalition."""
        with conn() as db:
            o=db.execute('SELECT * FROM near_opportunities WHERE id=?',(oid,)).fetchone()
            if not o:raise HTTPException(404,'Opportunity not found')
            if o['buyer_id']!=u['id']:raise HTTPException(403,'Only the buyer can review replacement options')
            if o['status'] not in ('invited','ready','needs_rescue'):
                raise HTTPException(409,'Rescue is no longer available for approved or paid coalitions')
            req=db.execute('SELECT * FROM requests WHERE id=?',(o['request_id'],)).fetchone()
            existing={row['provider_id'] for row in db.execute('SELECT provider_id FROM near_participants WHERE opportunity_id=?',(oid,))}
            declined=[row['provider_id'] for row in db.execute("SELECT provider_id FROM near_participants WHERE opportunity_id=? AND status='declined'",(oid,))]
            providers=[dict(row) for row in db.execute('SELECT * FROM providers WHERE owner_id IS NOT NULL AND owner_id<>?',(u['id'],))]
            alternatives=[]
            for p in providers:
                if p['id'] in existing or p['capacity']<=0:continue
                score,eligible,overlap=candidate_score(p,dict(req))
                if eligible and overlap>0:
                    alternatives.append({'provider_id':p['id'],'name':p['name'],'score':round(score,2),
                        'available_capacity':p['capacity'],'price_usd_illustrative':p['price'],
                        'evidence':f'{overlap} keyword overlaps; capacity {p["capacity"]}; location or remote eligibility confirmed'})
            alternatives.sort(key=lambda x:(-x['score'],-x['available_capacity']))
            return {'opportunity_id':oid,'status':o['status'],'declined_provider_ids':declined,
                'suggestions':alternatives[:5], 'automatic_replacement':False,
                'requires_human_action':True,
                'disclaimer':'Provider capacity and prices are self-declared. Invitations require buyer action and renewed provider consent.'}

    @app.get('/api/near/opportunities/{oid}/agent-review')
    def agent_review(oid:int,u=Depends(current)):
        with conn() as db:
            o=db.execute('SELECT * FROM near_opportunities WHERE id=?',(oid,)).fetchone()
            if not o:raise HTTPException(404,'Opportunity not found')
            if o['buyer_id']!=u['id']:raise HTTPException(403,'Only buyer can run financial review')
            parts=[dict(r) for r in db.execute('SELECT * FROM near_participants WHERE opportunity_id=?',(oid,))]
            p=load_policy(db,u['id']); total=int(o['amount_yocto'])*len(parts)
            declined=[v['provider_id'] for v in parts if v['status']=='declined']
            pending=[v['provider_id'] for v in parts if v['status']=='invited']
            reasons=[]
            if declined:reasons.append('Provider declined; rescue required before approval')
            if pending:reasons.append('Provider acceptance outstanding')
            if total>int(p['max_total_yocto']):reasons.append('Treasury allocation exceeds policy')
            if int(o['amount_yocto'])>int(p['max_provider_yocto']):reasons.append('Provider amount exceeds policy')
            if len(parts)>p['max_participants']:reasons.append('Number of providers exceeds policy')
            return {'opportunity_id':oid,'safe_to_request_approval':not reasons and o['status']=='ready',
                    'reasons':reasons or (['Status does not allow approval'] if o['status']!='ready' else []),
                    'rescue_required':bool(declined),'pending_acceptances':pending,'total_testnet_near':money(total),
                    'status':o['status'],'human_approval_always_required':True,
                    'revenue_allocation':[{'provider_id':v['provider_id'],'testnet_near':money(o['amount_yocto']),'status':v['status']} for v in parts]}
