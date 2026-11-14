"""Business-operation regression: ownership, booking consent, notifications, and no fake refunds."""
from uuid import uuid4
from datetime import datetime,timedelta,timezone
from fastapi.testclient import TestClient
from app.main import app,_attempts,_attempt_lock

client=TestClient(app)

def auth(tag):
    with _attempt_lock:_attempts.clear()
    r=client.post('/api/auth/register',json={'name':tag,'email':tag+uuid4().hex+'@example.test','password':'temporary-Strong-Pass!2026'})
    assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['token']}

def new_provider(headers):
    r=client.post('/api/providers',headers=headers,json={'name':'Booking Web '+uuid4().hex[:8],'category':'Web development','kind':'Digital services','city':'Johannesburg','country':'South Africa','remote':True,'bio':'We design accessible websites and offer service appointments.','skills':'web,developer,accessibility','price':10,'capacity':5})
    assert r.status_code==200,r.text
    return r.json()['id']

def test_booking_and_consent_notifications():
    buyer=auth('BookBuyer');seller=auth('BookSeller');outsider=auth('BookOther')
    pid=new_provider(seller)
    listings=client.get('/api/marketplace/listings',params={'provider_id':pid}).json()
    lid=next(x['id'] for x in listings if x['kind']!='Products')
    when=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
    bad=client.post('/api/operations/bookings',headers=buyer,json={'provider_id':pid,'listing_id':lid,'requested_start':'2020-01-01','note':'Need a website consult'})
    assert bad.status_code==422
    r=client.post('/api/operations/bookings',headers=buyer,json={'provider_id':pid,'listing_id':lid,'requested_start':when,'note':'Need a website consultation'})
    assert r.status_code==200,r.text; bid=r.json()['id']
    assert r.json()['funds_moved'] is False
    assert client.get('/api/operations/bookings',headers=outsider).json()==[]
    alerts=client.get('/api/operations/notifications',headers=seller)
    assert alerts.status_code==200 and alerts.json()['unread']>=1
    nid=alerts.json()['items'][0]['id']
    assert client.post('/api/operations/notifications/'+str(nid)+'/read',headers=buyer).status_code==404
    assert client.post('/api/operations/notifications/'+str(nid)+'/read',headers=seller).status_code==200
    assert client.post(f'/api/operations/bookings/{bid}/decision',headers=buyer,json={'status':'ACCEPTED'}).status_code==409
    assert client.post(f'/api/operations/bookings/{bid}/decision',headers=outsider,json={'status':'ACCEPTED'}).status_code==403
    assert client.post(f'/api/operations/bookings/{bid}/decision',headers=seller,json={'status':'ACCEPTED'}).status_code==200
    assert client.post(f'/api/operations/bookings/{bid}/decision',headers=seller,json={'status':'ACCEPTED'}).status_code==409
    assert client.post(f'/api/operations/bookings/{bid}/decision',headers=seller,json={'status':'COMPLETED'}).status_code==200
    assert client.post(f'/api/operations/bookings/{bid}/decision',headers=buyer,json={'status':'CANCELLED'}).status_code==409

def test_no_delivery_or_refund_without_verified_near_order():
    buyer=auth('RefundBuyer');seller=auth('RefundSeller');pid=new_provider(seller)
    assert client.post('/api/operations/orders/999999/refund-request',headers=buyer,json={'reason':'Product never arrived and was never delivered'}).status_code==404
    assert client.put('/api/operations/orders/999999/delivery',headers=seller,json={'status':'DELIVERED'}).status_code==404
    assert client.get('/api/operations/refund-requests',headers=buyer).json()==[]
