"""AVORA interactive marketplace MVP: seller-owned listings, image uploads, demo order requests.
All checkout records are UNPAID demonstrations; no on-chain transfer or card charge is implied.
"""
from __future__ import annotations
import base64, binascii, json, secrets, time
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

ROOT=Path(__file__).resolve().parents[1]
MEDIA=ROOT/'static'/'user-media'
MEDIA.mkdir(parents=True, exist_ok=True)

PROVIDER_COVERS={
 'Mpho Woodworks':'provider-mpho-cover.jpg',
 'Anele Digital':'provider-anele-cover.jpg',
 'Thabo Visuals':'provider-thabo-cover.jpg',
 'Naledi Bakes':'provider-naledi-cover.jpg',
 'BrightPath Plumbing':'provider-brightpath-cover.jpg',
 'Pixel Harbor':'provider-pixel-cover.jpg',
 'Sefako Prints':'provider-sefako-cover.jpg',
 'Nala Community Courier':'provider-nala-cover.jpg',
 'Dineo Home Care':'provider-dineo-cover.jpg',
 'Tumi Learning':'provider-tumi-cover.jpg',
}

EXAMPLES={
 'Mpho Woodworks':[
 ('Handcrafted Oak Coffee Table','Solid-wood coffee table, made to order.',180,'Products','mpho-coffee-table.jpg',8),
 ('Custom Kitchen Cabinet Installation','Consultation, measurements and custom kitchen fitting.',420,'Services','mpho-kitchen-cabinet.jpg',5),
 ('Furniture Restoration','Careful repair and restoration of wooden furniture.',95,'Services','mpho-restoration.jpg',12)],
 'Anele Digital':[
 ('Small Business Website','Responsive brochure website with contact form.',280,'Digital services','anele-website.jpg',10),
 ('E-commerce Store Setup','Online storefront setup with product categories.',390,'Digital services','anele-ecommerce.jpg',6),
 ('Website Accessibility Review','Audit of usability and accessible design.',120,'Digital services','anele-accessibility.jpg',15)],
 'Thabo Visuals':[
 ('Brand Photography Session','Creative photography for products and campaigns.',140,'Services','thabo-photography.jpg',12),
 ('Logo and Identity Design','Brand identity concept and practical design assets.',210,'Digital services','thabo-logo.jpg',8),
 ('Product Photo Editing','Post-production package for catalogue photos.',75,'Digital services','thabo-editing.jpg',15)],
 'Naledi Bakes':[
 ('Chocolate Celebration Cake','Rich chocolate sponge with chocolate frosting; example 8-inch cake.',38,'Products','cake-chocolate.jpg',15),
 ('Vanilla Birthday Cake','Classic vanilla sponge cake with custom decoration.',42,'Products','cake-vanilla.jpg',14),
 ('Assorted Cupcake Box','Box of 12 assorted baked cupcakes.',24,'Products','cake-cupcakes.jpg',25),
 ('Event Dessert Table','Dessert and catering consultation for celebrations.',145,'Services','cake-event.jpg',6)],
 'BrightPath Plumbing':[
 ('Leaking Tap Repair','Inspection and repair of a leaking household tap.',50,'Services','brightpath-tap.jpg',14),
 ('Bathroom Plumbing Consultation','Assessment and quote for bathroom fixtures.',65,'Services','brightpath-bathroom.jpg',8),
 ('Pipe Maintenance Visit','On-site plumbing maintenance service.',90,'Services','brightpath-maintenance.jpg',6)],
 'Pixel Harbor':[
 ('Responsive Landing Page','Frontend build for a modern business landing page.',300,'Digital services','pixel-landing-page.jpg',7),
 ('Design System Starter','Accessible components for a product team.',380,'Digital services','pixel-design-system.jpg',5),
 ('Frontend Debug Session','Remote troubleshooting and code review.',85,'Digital services','pixel-debug.jpg',15)],
 'Sefako Prints':[
 ('Custom Branded Gift Boxes','Sample pack of 10 printed gift boxes.',45,'Products','sefako-gift-boxes.jpg',30),
 ('Event Invitation Printing','50 printed invitations on premium cardstock.',32,'Products','sefako-invitations.jpg',40),
 ('Packaging Design Consultation','Brand-aligned packaging concept and print advice.',80,'Services','sefako-packaging.jpg',10)],
 'Nala Community Courier':[
 ('Local Parcel Delivery','Same-city courier service consultation.',25,'Services','nala-parcel.jpg',35),
 ('Small Business Delivery Plan','Recurring route coordination for local shops.',95,'Services','nala-plan.jpg',12),
 ('Event Collection Run','Scheduled collection and delivery planning.',60,'Services','nala-event-run.jpg',15)],
 'Dineo Home Care':[
 ('Apartment Deep Clean','Example deep cleaning package for an apartment.',85,'Services','dineo-apartment-clean.jpg',15),
 ('Office Cleaning Session','One-off professional office cleaning visit.',110,'Services','dineo-office-clean.jpg',10),
 ('Move-out Cleaning','End-of-lease cleaning quotation and scheduling.',145,'Services','dineo-moveout.jpg',7)],
 'Tumi Learning':[
 ('One-hour Maths Tutoring','Individual online mathematics lesson.',30,'Remote services','tumi-maths.jpg',40),
 ('Science Exam Preparation','Online science revision and study strategy session.',45,'Remote services','tumi-science.jpg',28),
 ('Four-lesson Study Bundle','A four-session learning support programme.',120,'Remote services','tumi-study-bundle.jpg',12)]
}

class ListingCreate(BaseModel):
    title:str=Field(min_length=3,max_length=120)
    description:str=Field(min_length=10,max_length=1400)
    price:int=Field(ge=1,le=1000000)
    kind:str=Field(pattern=r'^(Products|Services|Digital services|Local services|Remote services)$')
    stock:int=Field(ge=0,le=100000)
    image:str=Field(default='',max_length=180)

class PhotoIn(BaseModel):
    data:str=Field(min_length=40,max_length=1900000)

class OrderLine(BaseModel):
    listing_id:int=Field(gt=0)
    quantity:int=Field(ge=1,le=10)

class DemoOrderIn(BaseModel):
    lines:list[OrderLine]=Field(min_length=1,max_length=20)
    note:str=Field(default='',max_length=400)

ALLOWED_IMAGES={'carpentry.webp','web.webp','digital-1.jpg','bakery.webp','beauty.webp','hair-1.jpg','tutoring.webp','delivery.webp','bag-1.jpg','velora-dress-1.jpg','velora-bag-1.jpg','velora-sneakers-1.jpg','cake-chocolate.jpg','cake-vanilla.jpg','cake-cupcakes.jpg','cake-event.jpg','mpho-coffee-table.jpg','mpho-kitchen-cabinet.jpg','mpho-restoration.jpg','anele-website.jpg','anele-ecommerce.jpg','anele-accessibility.jpg','thabo-photography.jpg','thabo-logo.jpg','thabo-editing.jpg','brightpath-tap.jpg','brightpath-bathroom.jpg','brightpath-maintenance.jpg','pixel-landing-page.jpg','pixel-design-system.jpg','pixel-debug.jpg','sefako-gift-boxes.jpg','sefako-invitations.jpg','sefako-packaging.jpg','nala-parcel.jpg','nala-plan.jpg','nala-event-run.jpg','dineo-apartment-clean.jpg','dineo-office-clean.jpg','dineo-moveout.jpg','tumi-maths.jpg','tumi-science.jpg','tumi-study-bundle.jpg','provider-mpho-cover.jpg','provider-anele-cover.jpg','provider-thabo-cover.jpg','provider-naledi-cover.jpg','provider-brightpath-cover.jpg','provider-pixel-cover.jpg','provider-sefako-cover.jpg','provider-nala-cover.jpg','provider-dineo-cover.jpg','provider-tumi-cover.jpg'}

def install(app, conn, current):
    with conn() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS marketplace_media(listing_id INTEGER PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE, filename TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS marketplace_orders(id INTEGER PRIMARY KEY,buyer_id INTEGER NOT NULL REFERENCES users(id),provider_id INTEGER NOT NULL REFERENCES providers(id),status TEXT NOT NULL DEFAULT 'UNPAID_DEMO',total_usd INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '',created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS marketplace_order_lines(id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES marketplace_orders(id),listing_id INTEGER NOT NULL REFERENCES listings(id),title TEXT NOT NULL,unit_price_usd INTEGER NOT NULL,quantity INTEGER NOT NULL);
        ''')
        for name,samples in EXAMPLES.items():
            p=db.execute('SELECT id,owner_id,category FROM providers WHERE name=? AND owner_id IS NULL',(name,)).fetchone()
            if not p:continue
            for title,description,price,kind,image,stock in samples:
                listed=db.execute('SELECT id FROM listings WHERE provider_id=? AND title=?',(p['id'],title)).fetchone()
                if listed:lid=listed['id']
                else:
                    lid=db.execute('INSERT INTO listings(provider_id,title,description,price,kind,stock) VALUES(?,?,?,?,?,?)',(p['id'],title,description,price,kind,stock)).lastrowid
                db.execute('INSERT OR IGNORE INTO marketplace_media(listing_id,filename) VALUES(?,?)',(lid,image))
                # Keep seeded demo listings visually rich and distinct.
                # These records belong to ownerless example providers only, so updating
                # their catalogue artwork is safe and does not overwrite a signed-in user's uploads.
                db.execute('UPDATE marketplace_media SET filename=? WHERE listing_id=?',(image,lid))
            placeholder_title=f"{name} · {p['category']}"
            placeholder=db.execute('SELECT id FROM listings WHERE provider_id=? AND title=?',(p['id'],placeholder_title)).fetchone()
            if placeholder:
                cover=PROVIDER_COVERS.get(name, samples[0][4] if samples else 'web.webp')
                db.execute('INSERT OR IGNORE INTO marketplace_media(listing_id,filename) VALUES(?,?)',(placeholder['id'],cover))
                db.execute('UPDATE marketplace_media SET filename=? WHERE listing_id=?',(cover,placeholder['id']))
    router=APIRouter(prefix='/api/marketplace')

    def listing_row(db, r):
        row=dict(r)
        image=row.pop('image_file',None)
        if image and ('/' in image or '\\' in image or '..' in image): image=None
        row['image_url']='/static/'+('user-media/' if image and image.startswith('upload-') else 'media/')+image if image else None
        row['is_demo']=row['owner_id'] is None
        row['can_message']=row['owner_id'] is not None
        return row

    @router.get('/listings')
    def browse_listings(q:str='',kind:str='',provider_id:Optional[int]=None):
        if len(q)>100:raise HTTPException(400,'Search is too long')
        sql='''SELECT l.*,p.name provider_name,p.category provider_category,p.owner_id,p.city,im.filename image_file
                 FROM listings l JOIN providers p ON p.id=l.provider_id LEFT JOIN marketplace_media im ON im.listing_id=l.id WHERE 1=1'''
        args=[]
        if provider_id is not None:sql+=' AND l.provider_id=?';args.append(provider_id)
        if kind:sql+=' AND l.kind LIKE ?';args.append('%'+kind+'%')
        if q:sql+=' AND (l.title LIKE ? OR l.description LIKE ? OR p.name LIKE ? OR p.category LIKE ?)';args.extend(['%'+q+'%']*4)
        with conn() as db:return [listing_row(db,r) for r in db.execute(sql+' ORDER BY l.id DESC LIMIT 250',args).fetchall()]

    @router.get('/listings/{lid}')
    def listing_detail(lid:int):
        with conn() as db:
            row=db.execute('''SELECT l.*,p.name provider_name,p.category provider_category,p.owner_id,p.city,im.filename image_file
            FROM listings l JOIN providers p ON p.id=l.provider_id LEFT JOIN marketplace_media im ON im.listing_id=l.id WHERE l.id=?''',(lid,)).fetchone()
            if not row:raise HTTPException(404,'Listing not found')
            return listing_row(db,row)

    def owns(db,pid,uid):
        p=db.execute('SELECT id FROM providers WHERE id=? AND owner_id=?',(pid,uid)).fetchone()
        if not p:raise HTTPException(403,'Only the business owner can edit this storefront')

    @router.post('/providers/{pid}/listings')
    def add_listing(pid:int,data:ListingCreate,u=Depends(current)):
        with conn() as db:
            owns(db,pid,u['id'])
            lid=db.execute('INSERT INTO listings(provider_id,title,description,price,kind,stock) VALUES(?,?,?,?,?,?)',(pid,data.title,data.description,data.price,data.kind,data.stock)).lastrowid
            if data.image in ALLOWED_IMAGES:db.execute('INSERT INTO marketplace_media(listing_id,filename) VALUES(?,?)',(lid,data.image))
            return {'id':lid,'saved':True}

    @router.put('/providers/{pid}/listings/{lid}')
    def edit_listing(pid:int,lid:int,data:ListingCreate,u=Depends(current)):
        with conn() as db:
            owns(db,pid,u['id'])
            if not db.execute('SELECT id FROM listings WHERE provider_id=? AND id=?',(pid,lid)).fetchone():raise HTTPException(404,'Listing not found')
            db.execute('UPDATE listings SET title=?,description=?,price=?,kind=?,stock=? WHERE id=? AND provider_id=?',(data.title,data.description,data.price,data.kind,data.stock,lid,pid))
            if data.image in ALLOWED_IMAGES:db.execute('INSERT OR REPLACE INTO marketplace_media(listing_id,filename) VALUES(?,?)',(lid,data.image))
            return {'saved':True}

    @router.post('/providers/{pid}/listings/{lid}/photo')
    def upload_photo(pid:int,lid:int,payload:PhotoIn,u=Depends(current)):
        with conn() as db:
            owns(db,pid,u['id'])
            if not db.execute('SELECT id FROM listings WHERE id=? AND provider_id=?',(lid,pid)).fetchone():raise HTTPException(404,'Listing not found')
        try: blob=base64.b64decode(payload.data,validate=True)
        except (binascii.Error,ValueError):raise HTTPException(422,'Invalid image')
        if len(blob)>1200000:raise HTTPException(413,'Maximum image size is 1.2MB')
        if blob.startswith(b'\xff\xd8\xff'):suffix='jpg'
        elif blob.startswith(b'\x89PNG\r\n\x1a\n'):suffix='png'
        elif blob.startswith(b'RIFF') and blob[8:12]==b'WEBP':suffix='webp'
        else:raise HTTPException(422,'Upload a JPG, PNG or WebP image')
        fname='upload-'+secrets.token_hex(16)+'.'+suffix
        (MEDIA/fname).write_bytes(blob)
        with conn() as db:
            current_img=db.execute('SELECT filename FROM marketplace_media WHERE listing_id=?',(lid,)).fetchone()
            db.execute('INSERT OR REPLACE INTO marketplace_media(listing_id,filename) VALUES(?,?)',(lid,fname))
        if current_img and current_img['filename'].startswith('upload-'):(MEDIA/current_img['filename']).unlink(missing_ok=True)
        return {'image_url':'/static/user-media/'+fname}

    @router.post('/demo-checkout')
    def demo_checkout(payload:DemoOrderIn,u=Depends(current)):
        # No financial capture, no wallet debit, no inventory decrement.
        seen=set()
        with conn() as db:
            items=[];pid=None;total=0
            for line in payload.lines:
                if line.listing_id in seen:raise HTTPException(422,'Duplicate listing')
                seen.add(line.listing_id)
                item=db.execute('''SELECT l.*,p.owner_id FROM listings l JOIN providers p ON p.id=l.provider_id WHERE l.id=?''',(line.listing_id,)).fetchone()
                if not item:raise HTTPException(404,'Listing not found')
                if 'product' not in item['kind'].lower():raise HTTPException(422,'Services require an enquiry, not checkout')
                if item['owner_id']==u['id']:raise HTTPException(403,'Cannot order from your own store')
                if item['stock']<line.quantity:raise HTTPException(409,'Not enough example stock available')
                if pid is None:pid=item['provider_id']
                if pid!=item['provider_id']:raise HTTPException(422,'Checkout one business at a time')
                items.append((item,line.quantity));total+=item['price']*line.quantity
            order=db.execute('INSERT INTO marketplace_orders(buyer_id,provider_id,status,total_usd,note,created) VALUES(?,?,?,?,?,?)',(u['id'],pid,'UNPAID_DEMO',total,payload.note,int(time.time()))).lastrowid
            for item,qty in items:
                db.execute('INSERT INTO marketplace_order_lines(order_id,listing_id,title,unit_price_usd,quantity) VALUES(?,?,?,?,?)',(order,item['id'],item['title'],item['price'],qty))
            return {'order_id':order,'status':'UNPAID_DEMO','total_usd':total,'message':'Example checkout recorded. No payment was requested or collected.'}

    @router.get('/orders')
    def my_orders(u=Depends(current)):
        with conn() as db:
            orders=rows(db.execute('''SELECT o.*,p.name provider_name FROM marketplace_orders o JOIN providers p ON p.id=o.provider_id
                WHERE o.buyer_id=? OR p.owner_id=? ORDER BY o.id DESC LIMIT 100''',(u['id'],u['id'])))
            for order in orders:
                order['items']=rows(db.execute('SELECT title,unit_price_usd,quantity FROM marketplace_order_lines WHERE order_id=?',(order['id'],)))
            return orders

    app.include_router(router)
    from app.market_near import install as install_market_near
    install_market_near(app,conn,current)

# Reference to existing helpers is supplied by the host app to avoid changing auth or DB semantics.
def rows(cursor):return [dict(x) for x in cursor.fetchall()]
