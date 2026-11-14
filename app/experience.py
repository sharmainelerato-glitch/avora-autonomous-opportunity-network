"""Profile management, consent-first enquiries, and grounded request recommendations.
Local prototype: media on disk and data in SQLite. Public media are not identity verification.
"""
from __future__ import annotations
import base64, binascii, io, os, secrets, time
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from PIL import Image, ImageOps, UnidentifiedImageError

ROOT=Path(__file__).resolve().parents[1]
IMAGE_DIR=ROOT/'static'/'user-media'
IMAGE_DIR.mkdir(parents=True,exist_ok=True)

class BusinessEdit(BaseModel):
    name:str=Field(min_length=2,max_length=70)
    category:str=Field(min_length=2,max_length=70)
    kind:str=Field(pattern='^(Services|Digital services|Local services|Remote services|Products)$')
    city:str=Field(min_length=2,max_length=70)
    country:str=Field(min_length=2,max_length=70)
    remote:bool=False
    bio:str=Field(min_length=10,max_length=900)
    skills:str=Field(min_length=2,max_length=300)
    price:int=Field(ge=0,le=1000000)
    capacity:int=Field(ge=1,le=100000)
    website:str=Field(default='',max_length=200)
    service_area:str=Field(default='',max_length=150)
    delivery_info:str=Field(default='',max_length=250)
    booking_info:str=Field(default='',max_length=250)

class AccountEdit(BaseModel):
    name:str=Field(min_length=2,max_length=80)
    bio:str=Field(default='',max_length=420)
    city:str=Field(default='',max_length=80)

class ImageData(BaseModel):
    data:str=Field(min_length=100,max_length=3100000)

class ThreadDecision(BaseModel):
    decision:str=Field(pattern='^(accepted|declined)$')


def install(app,conn,current,candidate_score):
    with conn() as db:
        def add_column(table,name,decl):
            columns={r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
            if name not in columns:db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {decl}')
        for name,decl in [('website',"TEXT NOT NULL DEFAULT ''"),('service_area',"TEXT NOT NULL DEFAULT ''"),('delivery_info',"TEXT NOT NULL DEFAULT ''"),('booking_info',"TEXT NOT NULL DEFAULT ''"),('avatar_url',"TEXT NOT NULL DEFAULT ''"),('cover_url',"TEXT NOT NULL DEFAULT ''")]:add_column('providers',name,decl)
        for name,decl in [('avatar_url',"TEXT NOT NULL DEFAULT ''"),('bio',"TEXT NOT NULL DEFAULT ''"),('city',"TEXT NOT NULL DEFAULT ''")]:add_column('users',name,decl)
        old_enquiries_status='status' not in {r['name'] for r in db.execute('PRAGMA table_info(provider_enquiries)')}
        add_column('provider_enquiries','status',"TEXT NOT NULL DEFAULT 'pending'")
        add_column('provider_enquiries','decided_at',"INTEGER")
        # Historical conversations predate consent gates. Preserve them as accepted.
        if old_enquiries_status:db.execute("UPDATE provider_enquiries SET status='accepted'")
    router=APIRouter(prefix='/api/experience',tags=['Marketplace experience'])

    def owned(db,pid,uid):
        p=db.execute('SELECT * FROM providers WHERE id=? AND owner_id=?',(pid,uid)).fetchone()
        if not p:raise HTTPException(403,'Only the owner can change this business')
        return p

    @router.put('/me')
    def edit_me(payload:AccountEdit,user=Depends(current)):
        with conn() as db:
            db.execute('UPDATE users SET name=?,bio=?,city=? WHERE id=?',(payload.name.strip(),payload.bio.strip(),payload.city.strip(),user['id']))
            return dict(db.execute('SELECT id,name,email,bio,city,avatar_url FROM users WHERE id=?',(user['id'],)).fetchone())

    @router.put('/providers/{pid}')
    def edit_provider(pid:int,payload:BusinessEdit,user=Depends(current)):
        with conn() as db:
            owned(db,pid,user['id'])
            if payload.website and not payload.website.startswith(('https://','http://')):raise HTTPException(422,'Website must start with https:// or http://')
            db.execute('''UPDATE providers SET name=?,category=?,kind=?,city=?,country=?,remote=?,bio=?,skills=?,price=?,capacity=?,website=?,service_area=?,delivery_info=?,booking_info=? WHERE id=?''',
                (payload.name.strip(),payload.category.strip(),payload.kind,payload.city.strip(),payload.country.strip(),int(payload.remote),payload.bio.strip(),payload.skills.strip(),payload.price,payload.capacity,payload.website.strip(),payload.service_area.strip(),payload.delivery_info.strip(),payload.booking_info.strip(),pid))
            return {'saved':True,'id':pid}

    @router.post('/images/{kind}/{owner_id}')
    def image_upload(kind:str,owner_id:int,payload:ImageData,user=Depends(current)):
        if kind not in ('user-avatar','provider-avatar','provider-cover'):raise HTTPException(422,'Unsupported image type')
        with conn() as db:
            if kind=='user-avatar':
                if owner_id!=user['id']:raise HTTPException(403,'You can only edit your own profile photo')
            else:owned(db,owner_id,user['id'])
        try:
            data=base64.b64decode(payload.data,validate=True)
            if len(data)>2200000:raise HTTPException(413,'Image is too large (2.2MB maximum)')
            with Image.open(io.BytesIO(data)) as im:
                if im.format not in ('JPEG','PNG','WEBP'):raise HTTPException(422,'Upload a JPG, PNG, or WebP photograph')
                if im.width*im.height>22000000:raise HTTPException(413,'Image dimensions too large')
                im=ImageOps.exif_transpose(im).convert('RGB')
                if kind.endswith('avatar'):
                    edge=min(im.size);x=(im.width-edge)//2;y=(im.height-edge)//2
                    im=im.crop((x,y,x+edge,y+edge));im.thumbnail((640,640))
                else:im.thumbnail((1600,900))
                stream=io.BytesIO();im.save(stream,'WEBP',quality=85,method=4)
        except HTTPException:raise
        except (ValueError,binascii.Error,UnidentifiedImageError,OSError):raise HTTPException(422,'Invalid image data')
        filename='profile-'+secrets.token_hex(18)+'.webp'
        target=IMAGE_DIR/filename
        target.write_bytes(stream.getvalue())
        url='/static/user-media/'+filename
        with conn() as db:
            if kind=='user-avatar': db.execute('UPDATE users SET avatar_url=? WHERE id=?',(url,owner_id))
            else:
                col='avatar_url' if kind=='provider-avatar' else 'cover_url'
                db.execute(f'UPDATE providers SET {col}=? WHERE id=?',(url,owner_id))
        return {'url':url}

    @router.post('/enquiries/{eid}/decision')
    def decide_enquiry(eid:int,payload:ThreadDecision,user=Depends(current)):
        with conn() as db:
            thread=db.execute('''SELECT e.*,p.owner_id FROM provider_enquiries e JOIN providers p ON p.id=e.provider_id WHERE e.id=?''',(eid,)).fetchone()
            if not thread:raise HTTPException(404,'Conversation not found')
            if thread['owner_id']!=user['id']:raise HTTPException(403,'Only the receiving provider can accept or decline this request')
            if thread['status']!='pending':raise HTTPException(409,'Message request has already been decided')
            db.execute('UPDATE provider_enquiries SET status=?,decided_at=?,updated=? WHERE id=? AND status=?',(payload.decision,int(time.time()),int(time.time()),eid,'pending'))
            db.execute('INSERT INTO avora_notifications(recipient_id,title,body,link,created) VALUES(?,?,?,?,?)',(thread['buyer_id'],'Message request '+payload.decision,'The provider reviewed your conversation request.','/enquiry/'+str(eid),int(time.time())))
            return {'status':payload.decision}

    @router.get('/requests/{rid}/suggestions')
    def suggestions(rid:int,user=Depends(current)):
        with conn() as db:
            request=db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()
            if not request:raise HTTPException(404,'Request not found')
            if request['buyer_id']!=user['id']:raise HTTPException(403,'Only the requester can view private matching suggestions')
            people=db.execute('SELECT * FROM providers WHERE owner_id IS NOT NULL AND owner_id<>?',(user['id'],)).fetchall()
        matches=[]
        for p in people:
            score,eligible,overlap=candidate_score(p,request)
            if eligible and overlap>0:
                matches.append({'id':p['id'],'name':p['name'],'category':p['category'],'city':p['city'],'country':p['country'],'remote':bool(p['remote']),'avatar_url':p['avatar_url'],'cover_url':p['cover_url'],'match_score':round(score,2),'reasons':['Relevant category and skill keywords','Available remotely' if p['remote'] else 'Local availability']})
        matches.sort(key=lambda row:(-row['match_score'],row['id']))
        return {'mode':'rules_only','note':'Recommendations are deterministic until an AI API key is configured. No provider is automatically invited.', 'providers':matches[:12]}

    @router.get('/enquiries/counts')
    def enquiry_counts(user=Depends(current)):
        with conn() as db:
            pending=db.execute('''SELECT COUNT(*) FROM provider_enquiries e JOIN providers p ON p.id=e.provider_id WHERE p.owner_id=? AND e.status='pending' ''',(user['id'],)).fetchone()[0]
            return {'incoming_pending':pending}

    app.include_router(router)
