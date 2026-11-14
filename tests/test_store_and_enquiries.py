from fastapi.testclient import TestClient
from app.main import app
from uuid import uuid4

client=TestClient(app)

def new_user(prefix):
    unique=uuid4().hex[:10]
    response=client.post('/api/auth/register',json={'name':prefix,'email':f'{prefix.lower()}{unique}@example.org','password':'strong-fake-password-123'})
    assert response.status_code==200,response.text
    return {'Authorization':'Bearer '+response.json()['token']}

def test_velora_fashion_gallery_and_images():
    providers=client.get('/api/providers').json()
    velora=next(p for p in providers if p['name']=='VELORA FASHION')
    detail=client.get(f'/api/providers/{velora["id"]}').json()
    assert len(detail['listings'])>=4
    assert any('Dress' in l['title'] for l in detail['listings'])
    assert client.get('/static/media/velora-dress-1.jpg').status_code==200
    assert client.get('/static/media/velora-bag-1.jpg').status_code==200
    assert client.get('/static/app.js').status_code==200


def test_private_provider_enquiries():
    buyer=new_user('BuyerFashion')
    provider=new_user('ProviderService')
    stranger=new_user('StrangerService')
    created=client.post('/api/providers',headers=provider,json={'name':'Live Tailoring Studio','category':'Tailoring','kind':'Services','city':'Johannesburg','country':'South Africa','remote':True,'bio':'Dress alterations and custom formalwear for events.','skills':'tailoring,alterations,design','price':40,'capacity':4})
    assert created.status_code==200,created.text
    pid=created.json()['id']
    demo=next(x for x in client.get('/api/providers').json() if x['name']=='VELORA FASHION')
    assert client.post(f'/api/providers/{demo["id"]}/enquiries',headers=buyer,json={'subject':'Question about a dress','message':'Could I order a dress?'}).status_code==409
    assert client.post(f'/api/providers/{pid}/enquiries',headers=provider,json={'subject':'Test question','message':'Can I message myself?'}).status_code==403
    resp=client.post(f'/api/providers/{pid}/enquiries',headers=buyer,json={'subject':'Custom dress inquiry','message':'Can you make a dress for an event next week?'})
    assert resp.status_code==200,resp.text
    eid=resp.json()['id']
    assert client.get(f'/api/enquiries/{eid}',headers=stranger).status_code==403
    assert client.post(f'/api/enquiries/{eid}/messages',headers=stranger,json={'body':'Not allowed'}).status_code==403
    assert not any(x['id']==eid for x in client.get('/api/enquiries',headers=stranger).json())
    assert any(x['id']==eid for x in client.get('/api/enquiries',headers=buyer).json())
    assert any(x['id']==eid for x in client.get('/api/enquiries',headers=provider).json())
    assert client.post(f'/api/enquiries/{eid}/messages',headers=provider,json={'body':'Pending'}).status_code==409
    assert client.post(f'/api/experience/enquiries/{eid}/decision',headers=provider,json={'decision':'accepted'}).status_code==200
    posted=client.post(f'/api/enquiries/{eid}/messages',headers=provider,json={'body':'Yes, please send your measurements.'})
    assert posted.status_code==200,posted.text
    thread=client.get(f'/api/enquiries/{eid}',headers=buyer).json()
    assert len(thread['messages'])==2
    assert thread['messages'][-1]['body']=='Yes, please send your measurements.'
