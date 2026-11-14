from uuid import uuid4
from io import BytesIO
from PIL import Image
import base64
from fastapi.testclient import TestClient
from app.main import app,_attempts,_attempt_lock

c=TestClient(app)
def auth(name):
    with _attempt_lock:_attempts.clear()
    email=f'{name}-{uuid4().hex}@example.test'
    r=c.post('/api/auth/register',json={'name':name,'email':email,'password':'StrongExamplePassword!2026'})
    assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['token']}
def business(h,name='North Side Web Studio'):
    r=c.post('/api/providers',headers=h,json={'name':name,'category':'Web development','kind':'Digital services','city':'Johannesburg','country':'South Africa','remote':True,'bio':'Responsive sites and accessibility-friendly interfaces.','skills':'web,website,development,react','price':20,'capacity':4,'booking_info':'By appointment'})
    assert r.status_code==200,r.text
    return r.json()['id']
def photo():
    im=Image.new('RGB',(32,32),(230,225,220));buffer=BytesIO();im.save(buffer,format='PNG')
    return {'data':base64.b64encode(buffer.getvalue()).decode()}

def test_private_message_requests_require_acceptance():
    buyer=auth('BuyerConsent');seller=auth('SellerConsent');outsider=auth('OutsiderConsent')
    pid=business(seller)
    r=c.post(f'/api/providers/{pid}/enquiries',headers=buyer,json={'subject':'New web project','message':'Are you available for a website next month?'})
    assert r.status_code==200,r.text;eid=r.json()['id']
    assert c.get(f'/api/enquiries/{eid}',headers=buyer).json()['status']=='pending'
    assert c.post(f'/api/enquiries/{eid}/messages',headers=buyer,json={'body':'Hello again'}).status_code==409
    assert c.post(f'/api/experience/enquiries/{eid}/decision',headers=buyer,json={'decision':'accepted'}).status_code==403
    assert c.post(f'/api/experience/enquiries/{eid}/decision',headers=outsider,json={'decision':'accepted'}).status_code==403
    assert c.post(f'/api/experience/enquiries/{eid}/decision',headers=seller,json={'decision':'accepted'}).status_code==200
    assert c.post(f'/api/enquiries/{eid}/messages',headers=seller,json={'body':'Yes, we can schedule a call.'}).status_code==200
    assert c.post(f'/api/experience/enquiries/{eid}/decision',headers=seller,json={'decision':'declined'}).status_code==409

def test_decline_prevents_followup():
    buyer=auth('BuyerDecline');seller=auth('SellerDecline');pid=business(seller,'Decline Website Studio')
    r=c.post(f'/api/providers/{pid}/enquiries',headers=buyer,json={'subject':'New website job','message':'Please let me know if you have a space.'})
    eid=r.json()['id']
    assert c.post(f'/api/experience/enquiries/{eid}/decision',headers=seller,json={'decision':'declined'}).status_code==200
    assert c.post(f'/api/enquiries/{eid}/messages',headers=buyer,json={'body':'Retry'}).status_code==409

def test_provider_edit_photo_and_account():
    seller=auth('SellerProfile');outsider=auth('OtherProfile');pid=business(seller,'Aster Web Studio')
    payload={'name':'Aster Digital','category':'Web development','kind':'Digital services','city':'Cape Town','country':'South Africa','remote':True,'bio':'Responsive inclusive business apps and client portfolios.','skills':'React, websites, design','price':40,'capacity':7,'website':'https://example.org','service_area':'Global remote','delivery_info':'','booking_info':'Two week projects'}
    assert c.put(f'/api/experience/providers/{pid}',headers=outsider,json=payload).status_code==403
    assert c.put(f'/api/experience/providers/{pid}',headers=seller,json=payload).status_code==200
    assert c.get(f'/api/providers/{pid}').json()['website']=='https://example.org'
    assert c.post(f'/api/experience/images/provider-avatar/{pid}',headers=outsider,json=photo()).status_code==403
    r=c.post(f'/api/experience/images/provider-avatar/{pid}',headers=seller,json=photo())
    assert r.status_code==200,r.text
    assert c.get(r.json()['url']).status_code==200
    assert c.put('/api/experience/me',headers=seller,json={'name':'Seller Updated','bio':'I build digital products.','city':'Cape Town'}).status_code==200
    assert c.get('/api/me',headers=seller).json()['city']=='Cape Town'
    seller_user_id=c.get('/api/me',headers=seller).json()['id']
    r=c.post(f'/api/experience/images/user-avatar/{seller_user_id}',headers=outsider,json=photo())
    assert r.status_code==403

def test_request_matches_and_provider_responses():
    buyer=auth('BuyerMatch');seller=auth('SellerMatch');outsider=auth('OtherMatch');pid=business(seller,'New Web Agency')
    r=c.post('/api/requests',headers=buyer,json={'title':'Need website development','description':'We need a responsive website for a company and contact forms.','category':'Web development','budget':100,'quantity':1,'city':'Johannesburg','remote':True})
    assert r.status_code==200;rid=r.json()['id']
    assert c.get(f'/api/experience/requests/{rid}/suggestions',headers=outsider).status_code==403
    rec=c.get(f'/api/experience/requests/{rid}/suggestions',headers=buyer)
    assert rec.status_code==200
    assert any(p['id']==pid for p in rec.json()['providers'])
    assert c.post(f'/api/requests/{rid}/proposals',headers=outsider,json={'provider_id':pid,'amount':55,'note':'I can do that'}).status_code==403
    assert c.post(f'/api/requests/{rid}/proposals',headers=seller,json={'provider_id':pid,'amount':55,'note':'We can build a mobile-friendly site.'}).status_code==200
    assert any(p['provider_id']==pid for p in c.get(f'/api/requests/{rid}',headers=buyer).json()['proposals'])
