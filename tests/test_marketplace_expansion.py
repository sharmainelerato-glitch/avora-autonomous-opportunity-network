from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app, _attempts, _attempt_lock

client=TestClient(app)

def account(kind):
    # Isolate the deliberately strict shared-IP registration limiter in local TestClient.
    with _attempt_lock: _attempts.clear()
    email=f'{kind}-{uuid4().hex}@example.test'
    response=client.post('/api/auth/register',json={'name':kind,'email':email,'password':'temporary-local-demo-pass-321'})
    assert response.status_code==200,response.text
    return {'Authorization':'Bearer '+response.json()['token']}

def test_sample_bakery_catalogue_and_images():
    p=next(p for p in client.get('/api/providers').json() if p['name']=='Naledi Bakes')
    items=client.get('/api/marketplace/listings',params={'provider_id':p['id']}).json()
    assert any('Chocolate Celebration Cake'==l['title'] for l in items)
    assert any('Cupcake' in l['title'] for l in items)
    assert all(l['is_demo'] for l in items)
    expected={
        'Chocolate Celebration Cake':'cake-chocolate.jpg',
        'Vanilla Birthday Cake':'cake-vanilla.jpg',
        'Assorted Cupcake Box':'cake-cupcakes.jpg',
        'Event Dessert Table':'cake-event.jpg',
    }
    for title,filename in expected.items():
        entry=next(l for l in items if l['title']==title)
        assert entry['image_url']=='/static/media/'+filename
        assert client.get(entry['image_url']).status_code==200
    assert len({next(l for l in items if l['title']==title)['image_url'] for title in expected})==4
    assert client.get('/static/marketplace.js').status_code==200



def test_demo_catalogues_use_distinct_listing_images():
    names=['Mpho Woodworks','Anele Digital','Thabo Visuals','Naledi Bakes','BrightPath Plumbing','Pixel Harbor','Sefako Prints','Nala Community Courier','Dineo Home Care','Tumi Learning']
    providers={p['name']:p for p in client.get('/api/providers').json() if p['name'] in names}
    for name in names:
        items=client.get('/api/marketplace/listings',params={'provider_id':providers[name]['id']}).json()
        assert len(items) >= 3
        urls=[i['image_url'] for i in items]
        assert all(url and url.startswith('/static/media/') for url in urls)
        assert len(urls) == len(set(urls)), f"Duplicate image detected for {name}: {urls}"
        for url in urls:
            assert client.get(url).status_code == 200


def test_owner_listing_upload_and_private_access():
    seller=account('SellerMarket')
    buyer=account('BuyerMarket')
    other=account('OtherMarket')
    reg=client.post('/api/providers',headers=seller,json={'name':'Riverside Artisan Bakery','category':'Food','kind':'Products','city':'Cape Town','country':'South Africa','remote':False,'bio':'Small batches of fresh breads and celebration cakes.','skills':'cakes,bread,bakery','price':35,'capacity':20})
    assert reg.status_code==200,reg.text
    pid=reg.json()['id']
    data={'title':'Blueberry Muffin Box','description':'Box of six hand-baked blueberry muffins.','price':28,'stock':10,'kind':'Products','image':'bakery.webp'}
    assert client.post(f'/api/marketplace/providers/{pid}/listings',headers=buyer,json=data).status_code==403
    listing=client.post(f'/api/marketplace/providers/{pid}/listings',headers=seller,json=data)
    assert listing.status_code==200,listing.text
    lid=listing.json()['id']
    res=client.get(f'/api/marketplace/listings/{lid}')
    assert res.status_code==200 and res.json()['owner_id'] is not None
    assert client.put(f'/api/marketplace/providers/{pid}/listings/{lid}',headers=other,json=data).status_code==403
    invalid=client.post(f'/api/marketplace/providers/{pid}/listings/{lid}/photo',headers=seller,json={'data':'not an image'*20})
    assert invalid.status_code==422
    order=client.post('/api/marketplace/demo-checkout',headers=buyer,json={'lines':[{'listing_id':lid,'quantity':2}],'note':'Please call before delivery'})
    assert order.status_code==200,order.text
    assert order.json()['status']=='UNPAID_DEMO'
    assert order.json()['total_usd']==56
    assert client.post('/api/marketplace/demo-checkout',headers=seller,json={'lines':[{'listing_id':lid,'quantity':1}]}).status_code==403
    assert client.post('/api/marketplace/demo-checkout',headers=buyer,json={'lines':[{'listing_id':lid,'quantity':11}]}).status_code==422
    oid=order.json()['order_id']
    assert any(o['id']==oid for o in client.get('/api/marketplace/orders',headers=buyer).json())
    assert any(o['id']==oid for o in client.get('/api/marketplace/orders',headers=seller).json())
    assert not any(o['id']==oid for o in client.get('/api/marketplace/orders',headers=other).json())


def test_services_are_not_checkoutable_and_nonowners_cannot_edit():
    buyer=account('BuyerService')
    p=next(p for p in client.get('/api/providers').json() if p['name']=='Mpho Woodworks')
    listing=next(l for l in client.get('/api/marketplace/listings',params={'provider_id':p['id']}).json() if l['kind']=='Services')
    resp=client.post('/api/marketplace/demo-checkout',headers=buyer,json={'lines':[{'listing_id':listing['id'],'quantity':1}]})
    assert resp.status_code==422
    assert client.post(f'/api/marketplace/providers/{p["id"]}/listings',headers=buyer,json={'title':'fake edit','description':'Should never be published','price':12,'stock':3,'kind':'Products'}).status_code==403

def test_owned_photo_upload_round_trip():
    import base64
    seller=account('UploadMarket')
    p=client.post('/api/providers',headers=seller,json={'name':'Neighbourhood Cakes Studio','category':'Baking','kind':'Products','city':'Pretoria','country':'South Africa','remote':False,'bio':'A small original bakery for testing legitimate photo uploads.','skills':'baking,cakes','price':20,'capacity':8})
    assert p.status_code==200
    pid=p.json()['id']
    listing=client.post(f'/api/marketplace/providers/{pid}/listings',headers=seller,json={'title':'Fresh Bakery Bread','description':'Fresh bread baked every morning for customers.','price':15,'stock':9,'kind':'Products'})
    assert listing.status_code==200
    lid=listing.json()['id']
    # A valid 1x1 PNG; no image-processing dependency required.
    raw=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==')
    payload={'data':base64.b64encode(raw).decode()}
    upload=client.post(f'/api/marketplace/providers/{pid}/listings/{lid}/photo',headers=seller,json=payload)
    assert upload.status_code==200,upload.text
    url=upload.json()['image_url']
    assert url.startswith('/static/user-media/upload-')
    assert client.get(url).status_code==200
    assert client.get(f'/api/marketplace/listings/{lid}').json()['image_url']==url
