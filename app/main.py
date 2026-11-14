"""AVORA Hackathon application. Payment outcomes are never simulated as paid."""
from __future__ import annotations
import os, sqlite3, secrets, hashlib, hmac, json, time, re, math, uuid, threading, ipaddress
from collections import defaultdict, deque
from pathlib import Path
from contextlib import contextmanager
from typing import Optional
from urllib.parse import urlencode
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
DB = Path(os.getenv('LAPENG_DB', str(ROOT/'avora.sqlite3')))
if not DB.is_absolute(): DB = ROOT/DB
app=FastAPI(title='AVORA — Human-centred Commerce', version='0.9.1-hardened', docs_url=None, redoc_url=None, openapi_url=None)
# Single-process local/demo rate limiting. Use Redis/edge WAF in production/multiple workers.
_attempts=defaultdict(deque)
_attempt_lock=threading.Lock()
MAX_BODY_BYTES=65536

def throttle(key:str, max_attempts:int, period:int):
    now=time.monotonic()
    with _attempt_lock:
        bucket=_attempts[key]
        while bucket and bucket[0] <= now-period:bucket.popleft()
        if len(bucket)>=max_attempts:raise HTTPException(429,'Too many attempts. Try again later.',headers={'Retry-After':str(period)})
        bucket.append(now)

@app.middleware('http')
async def security_middleware(request:Request, call_next):
    # No bearer tokens in cookies, so forms can't silently perform authenticated CSRF requests.
    # Also enforce same-origin mutations, including for unauthenticated endpoints.
    if request.method in ('POST','PUT','PATCH','DELETE'):
        origin=request.headers.get('origin')
        if origin:
            from urllib.parse import urlsplit
            src=urlsplit(origin)
            host=request.url.hostname
            if src.hostname!=host or src.scheme not in ('http','https') or (src.port or (443 if src.scheme=='https' else 80)) != (request.url.port or (443 if request.url.scheme=='https' else 80)):
                return JSONResponse({'detail':'Cross-origin requests are blocked'},status_code=403)
        size=request.headers.get('content-length','')
        if size.isdigit() and int(size)>(3200000 if (request.url.path.endswith('/photo') and request.url.path.startswith('/api/marketplace/')) or request.url.path.startswith('/api/experience/images/') else MAX_BODY_BYTES):
            return JSONResponse({'detail':'Request body too large'},status_code=413)
        # Bound the actual body even when Content-Length is absent.
        body=await request.body()
        if len(body)>(3200000 if (request.url.path.endswith('/photo') and request.url.path.startswith('/api/marketplace/')) or request.url.path.startswith('/api/experience/images/') else MAX_BODY_BYTES):return JSONResponse({'detail':'Request body too large'},status_code=413)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=(), payment=()'
    response.headers['Content-Security-Policy']="default-src 'self'; base-uri 'self'; form-action 'self'; object-src 'none'; frame-ancestors 'none'; connect-src 'self' https://rpc.testnet.near.org; img-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'"
    response.headers['Cache-Control']='no-store' if request.url.path.startswith('/api/') else 'no-cache'
    if os.getenv('APP_BASE_URL','').startswith('https://'):
        response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
    return response

app.mount('/static', StaticFiles(directory=ROOT/'static'), name='static')

@contextmanager
def conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db=sqlite3.connect(DB, timeout=20, check_same_thread=False)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    finally: db.close()

def obj(row): return dict(row) if row else None

def rows(cursor): return [dict(x) for x in cursor.fetchall()]

def pwd_hash(password, salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+'$'+hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),260000).hex()

def check_pwd(password, stored):
    try:
        salt,digest=stored.split('$')
        return hmac.compare_digest(pwd_hash(password,salt).split('$')[1],digest)
    except Exception:return False

def setup():
    with conn() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS providers(id INTEGER PRIMARY KEY, owner_id INTEGER REFERENCES users(id), name TEXT NOT NULL, category TEXT NOT NULL, kind TEXT NOT NULL, city TEXT NOT NULL, country TEXT NOT NULL, remote INTEGER NOT NULL DEFAULT 0, bio TEXT NOT NULL, skills TEXT NOT NULL, price INTEGER NOT NULL, capacity INTEGER NOT NULL DEFAULT 1, rating REAL NOT NULL DEFAULT 0, reviews INTEGER NOT NULL DEFAULT 0, verified INTEGER NOT NULL DEFAULT 0, featured INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS listings(id INTEGER PRIMARY KEY,provider_id INTEGER NOT NULL REFERENCES providers(id),title TEXT NOT NULL,description TEXT NOT NULL,price INTEGER NOT NULL,kind TEXT NOT NULL,stock INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY,buyer_id INTEGER REFERENCES users(id),title TEXT NOT NULL,description TEXT NOT NULL,category TEXT NOT NULL,budget INTEGER NOT NULL,quantity INTEGER NOT NULL,city TEXT NOT NULL,remote INTEGER NOT NULL,created INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'open');
        CREATE TABLE IF NOT EXISTS proposals(id INTEGER PRIMARY KEY,request_id INTEGER NOT NULL REFERENCES requests(id),provider_id INTEGER NOT NULL REFERENCES providers(id),amount INTEGER NOT NULL, note TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,request_id INTEGER NOT NULL REFERENCES requests(id),sender_id INTEGER REFERENCES users(id),body TEXT NOT NULL,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY,author_id INTEGER NOT NULL REFERENCES users(id),target_type TEXT NOT NULL,target_id INTEGER NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY,author_id INTEGER REFERENCES users(id),provider_id INTEGER NOT NULL REFERENCES providers(id),payment_id INTEGER NOT NULL,score INTEGER NOT NULL,text TEXT NOT NULL,created INTEGER NOT NULL, UNIQUE(author_id,payment_id));
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,request_id INTEGER REFERENCES requests(id),actor_id INTEGER REFERENCES users(id),type TEXT NOT NULL,detail TEXT NOT NULL,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS provider_enquiries(id INTEGER PRIMARY KEY,provider_id INTEGER NOT NULL REFERENCES providers(id),buyer_id INTEGER NOT NULL REFERENCES users(id),subject TEXT NOT NULL,created INTEGER NOT NULL,updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS enquiry_messages(id INTEGER PRIMARY KEY,enquiry_id INTEGER NOT NULL REFERENCES provider_enquiries(id),sender_id INTEGER NOT NULL REFERENCES users(id),body TEXT NOT NULL,created INTEGER NOT NULL);
        ''')
        if db.execute('SELECT COUNT(*) FROM providers').fetchone()[0]==0:
            demo=[
                ('Mpho Woodworks','Carpentry','Local services','Johannesburg','South Africa',0,'Hand-crafted cabinetry, furniture, repairs and fitting.','carpentry,woodworking,furniture,installation',160,30,4.9,42,1,1),
                ('Anele Digital','Web development','Digital services','Cape Town','South Africa',1,'Accessible websites and e-commerce tools for independent businesses.','web,react,website,software,shopify',240,12,4.8,36,1,1),
                ('Thabo Visuals','Creative','Creative services','Pretoria','South Africa',1,'Brand photography, identity, visual design and content.','photography,branding,logo,design',110,10,4.8,27,1,1),
                ('Naledi Bakes','Food','Products','Johannesburg','South Africa',0,'Custom cakes, breads and community catering.','cake,bakery,catering,food',35,50,4.9,71,1,1),
                ('BrightPath Plumbing','Plumbing','Local services','Durban','South Africa',0,'Residential installations and maintenance.','plumbing,repairs,installation',80,20,4.7,19,0,1),
                ('Pixel Harbor','Web development','Digital services','London','United Kingdom',1,'Remote frontend development and accessible design systems.','web,frontend,design,react,remote',300,8,4.7,31,1,0),
                ('Sefako Prints','Printing','Products','Johannesburg','South Africa',0,'Custom packaging and event printing.','packaging,printing,branding,boxes',40,100,4.8,24,1,1),
                ('Nala Community Courier','Logistics','Local services','Johannesburg','South Africa',0,'Community collection and last-mile delivery coordination.','delivery,courier,logistics',25,75,4.6,18,0,0),
                ('Dineo Home Care','Cleaning','Local services','Soweto','South Africa',0,'Home, office and short-let cleaning.','cleaning,home,office',55,22,4.9,46,1,0),
                ('Tumi Learning','Tutoring','Remote services','Gaborone','Botswana',1,'Online maths and science tutoring.','education,tutor,mathematics,science',45,18,4.9,22,1,0),
            ]
            db.executemany('INSERT INTO providers(owner_id,name,category,kind,city,country,remote,bio,skills,price,capacity,rating,reviews,verified,featured) VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',demo)
            for p in db.execute('SELECT * FROM providers').fetchall():
                db.execute('INSERT INTO listings(provider_id,title,description,price,kind,stock) VALUES(?,?,?,?,?,?)',(p['id'],p['name']+' · '+p['category'],p['bio'],p['price'],p['kind'],p['capacity']))
setup()

# Seed a disclosed fashion demonstration merchant without changing existing accounts.
from app.velora_seed import ensure_velora
with conn() as _velora_db:
    ensure_velora(_velora_db)

class Credentials(BaseModel):
    email:str=Field(min_length=5,max_length=254)
    password:str=Field(min_length=1,max_length=1024)
    name:str=Field(default='',max_length=80)
    @field_validator('email')
    @classmethod
    def clean_email(cls,value):return value.strip().lower()

class Profile(BaseModel):
    name:str=Field(min_length=2,max_length=70)
    category:str=Field(min_length=2,max_length=70)
    kind:str=Field(default='Services',pattern=r'^(Products|Services|Digital services|Local services|Remote services)$')
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
class ServiceRequest(BaseModel):
    title:str=Field(min_length=5,max_length=130)
    description:str=Field(min_length=10,max_length=1200)
    category:str='General'
    budget:int=Field(ge=1,le=1000000)
    quantity:int=Field(default=1,ge=1,le=100000)
    city:str='Remote'
    remote:bool=False
class ProposalIn(BaseModel):
    provider_id:int
    amount:int=Field(ge=1,le=1000000)
    note:str=Field(min_length=4,max_length=600)
class MessageIn(BaseModel):
    body:str=Field(min_length=1,max_length=1500)
class EnquiryIn(BaseModel):
    subject:str=Field(min_length=4,max_length=140)
    message:str=Field(min_length=10,max_length=1500)
class ReportIn(BaseModel):
    target_type:str=Field(max_length=30)
    target_id:int=Field(gt=0)
    reason:str=Field(min_length=10,max_length=1200)
class ReviewIn(BaseModel):
    payment_id:int
    score:int=Field(ge=1,le=5)
    text:str=Field(min_length=8,max_length=1000)

def current(authorization:Optional[str]=Header(default=None)):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Sign in required')
    digest=hashlib.sha256(authorization[7:].encode()).hexdigest()
    with conn() as db:
        u=db.execute('SELECT users.id,users.name,users.email FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>?',(digest,int(time.time()))).fetchone()
    if not u: raise HTTPException(401,'Session expired')
    return dict(u)

def optional_user(authorization:Optional[str]=Header(default=None)):
    try: return current(authorization)
    except HTTPException: return None

def session_for(db,user):
    token=secrets.token_urlsafe(36)
    db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],int(time.time())+86400*7))
    return {'token':token,'user':{'id':user['id'],'name':user['name'],'email':user['email']}}

@app.get('/')
def index(): return FileResponse(ROOT/'static'/'index.html')
@app.get('/health')
def health():return {'ok':True,'near_network':'testnet','ai_configured':bool(os.getenv('AI_API_KEY') or os.getenv('GROQ_API_KEY'))}
@app.post('/api/auth/register')
def register(c:Credentials,request:Request):
    throttle('register:'+request.client.host,20,3600)
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',c.email.strip()) or len(c.password)<12 or len(c.name.strip())<2 or c.password.lower() in ('password123456','123456789012','correcthorsebatterystaple'):raise HTTPException(400,'Valid email, name and a nontrivial password of 12+ characters required')
    with conn() as db:
        try:
            cursor=db.execute('INSERT INTO users(name,email,password,created) VALUES(?,?,?,?)',(c.name.strip()[:80],c.email.lower().strip(),pwd_hash(c.password),int(time.time())))
        except sqlite3.IntegrityError:raise HTTPException(409,'Email already registered')
        user=db.execute('SELECT * FROM users WHERE id=?',(cursor.lastrowid,)).fetchone()
        return session_for(db,user)
@app.post('/api/auth/login')
def login(c:Credentials,request:Request):
    throttle('login-ip:'+request.client.host,35,900)
    throttle('login:'+request.client.host+':'+hashlib.sha256(c.email.encode()).hexdigest()[:16],6,900)
    with conn() as db:
        u=db.execute('SELECT * FROM users WHERE email=?',(c.email.lower().strip(),)).fetchone()
        if not u or not check_pwd(c.password,u['password']):raise HTTPException(401,'Invalid email or password')
        return session_for(db,u)
@app.post('/api/auth/logout')
def logout(authorization:Optional[str]=Header(default=None),u=Depends(current)):
    digest=hashlib.sha256(authorization[7:].encode()).hexdigest()
    with conn() as db:db.execute('DELETE FROM sessions WHERE token_hash=? AND user_id=?',(digest,u['id']))
    return {'ok':True}

@app.get('/api/me')
def me(u=Depends(current)):
    with conn() as db:
        businesses=rows(db.execute('SELECT * FROM providers WHERE owner_id=?',(u['id'],)))
        mine=db.execute('SELECT avatar_url,bio,city FROM users WHERE id=?',(u['id'],)).fetchone()
    return {**u,**dict(mine),'businesses':businesses}
@app.get('/api/providers')
def providers(q:str='',city:str='',remote:Optional[bool]=None,sort:str='recommended'):
    sql='SELECT * FROM providers WHERE 1=1';args=[]
    if q:
        sql+=' AND (name LIKE ? OR category LIKE ? OR skills LIKE ? OR bio LIKE ?)'; args += ['%'+q+'%']*4
    if city:sql+=' AND (city LIKE ? OR remote=1)';args.append('%'+city+'%')
    if remote is True:sql+=' AND remote=1'
    sql += ' ORDER BY '+('rating DESC,reviews DESC' if sort=='rating' else 'price ASC' if sort=='price' else 'reviews ASC' if sort=='new' else 'verified DESC,rating DESC,reviews DESC')
    with conn() as db:return rows(db.execute(sql+' LIMIT 80',args))
@app.get('/api/providers/{pid}')
def provider(pid:int):
    with conn() as db:
        p=obj(db.execute('SELECT * FROM providers WHERE id=?',(pid,)).fetchone())
        if not p:raise HTTPException(404,'Not found')
        p['listings']=rows(db.execute('SELECT * FROM listings WHERE provider_id=?',(pid,)))
        p['feedback']=rows(db.execute('SELECT score,text,created FROM reviews WHERE provider_id=? ORDER BY id DESC LIMIT 20',(pid,)))
        return p
@app.post('/api/providers')
def new_provider(p:Profile,u=Depends(current)):
    if p.website and not p.website.startswith(('https://','http://')):raise HTTPException(422,'Website must start with https:// or http://')
    with conn() as db:
        cur=db.execute('INSERT INTO providers(owner_id,name,category,kind,city,country,remote,bio,skills,price,capacity,website,service_area,delivery_info,booking_info) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(u['id'],p.name,p.category,p.kind,p.city,p.country,int(p.remote),p.bio,p.skills,p.price,p.capacity,p.website,p.service_area,p.delivery_info,p.booking_info))
        db.execute('INSERT INTO listings(provider_id,title,description,price,kind,stock) VALUES(?,?,?,?,?,?)',(cur.lastrowid,p.category+' by '+p.name,p.bio,p.price,p.kind,p.capacity))
        return {'id':cur.lastrowid,'status':'unverified','note':'Contact, identity and legal credentials are not yet verified.'}
# Genuine private buyer/provider messaging; seeded demo providers have no account inbox.
def enquiry_access(db,eid,uid):
    thread=db.execute("""SELECT e.*,p.owner_id,p.name provider_name,u.name buyer_name
                          FROM provider_enquiries e JOIN providers p ON p.id=e.provider_id
                          JOIN users u ON u.id=e.buyer_id WHERE e.id=?""",(eid,)).fetchone()
    if not thread:raise HTTPException(404,'Enquiry not found')
    if uid not in (thread['buyer_id'],thread['owner_id']):raise HTTPException(403,'Not a participant in this conversation')
    return thread

@app.post('/api/providers/{pid}/enquiries')
def create_enquiry(pid:int,details:EnquiryIn,u=Depends(current)):
    with conn() as db:
        provider=db.execute('SELECT id,owner_id FROM providers WHERE id=?',(pid,)).fetchone()
        if not provider:raise HTTPException(404,'Provider not found')
        if provider['owner_id'] is None:raise HTTPException(409,'This is an example provider without a real inbox. Post an open service request instead.')
        if provider['owner_id']==u['id']:raise HTTPException(403,'You cannot message your own provider profile')
        when=int(time.time())
        cur=db.execute("INSERT INTO provider_enquiries(provider_id,buyer_id,subject,created,updated,status) VALUES(?,?,?,?,?,'pending')",(pid,u['id'],details.subject.strip(),when,when))
        db.execute('INSERT INTO enquiry_messages(enquiry_id,sender_id,body,created) VALUES(?,?,?,?)',(cur.lastrowid,u['id'],details.message.strip(),when))
        db.execute('INSERT INTO avora_notifications(recipient_id,title,body,link,created) VALUES(?,?,?,?,?)',(provider['owner_id'],'New message request','A buyer asked to start a conversation.','/enquiry/'+str(cur.lastrowid),when))
        return {'id':cur.lastrowid,'status':'pending'}

@app.get('/api/enquiries')
def list_enquiries(u=Depends(current)):
    with conn() as db:
        return rows(db.execute("""SELECT e.id,e.subject,e.provider_id,e.buyer_id,e.updated,e.status,p.name provider_name,
            b.name buyer_name, (SELECT body FROM enquiry_messages m WHERE m.enquiry_id=e.id ORDER BY m.id DESC LIMIT 1) last_message
            FROM provider_enquiries e JOIN providers p ON p.id=e.provider_id JOIN users b ON b.id=e.buyer_id
            WHERE e.buyer_id=? OR p.owner_id=? ORDER BY e.updated DESC LIMIT 100""",(u['id'],u['id'])))

@app.get('/api/enquiries/{eid}')
def get_enquiry(eid:int,u=Depends(current)):
    with conn() as db:
        thread=enquiry_access(db,eid,u['id'])
        out=dict(thread)
        out['messages']=rows(db.execute("""SELECT m.id,m.sender_id,m.body,m.created,u.name sender_name FROM enquiry_messages m
                           JOIN users u ON u.id=m.sender_id WHERE m.enquiry_id=? ORDER BY m.id LIMIT 300""",(eid,)))
        return out

@app.post('/api/enquiries/{eid}/messages')
def reply_enquiry(eid:int,message:MessageIn,u=Depends(current)):
    with conn() as db:
        thread=enquiry_access(db,eid,u['id'])
        if thread['status']!='accepted':raise HTTPException(409,'The provider must accept the message request before a conversation can begin')
        when=int(time.time())
        cur=db.execute('INSERT INTO enquiry_messages(enquiry_id,sender_id,body,created) VALUES(?,?,?,?)',(eid,u['id'],message.body.strip(),when))
        db.execute('UPDATE provider_enquiries SET updated=? WHERE id=?',(when,eid))
        recipient=thread['owner_id'] if u['id']==thread['buyer_id'] else thread['buyer_id']
        db.execute('INSERT INTO avora_notifications(recipient_id,title,body,link,created) VALUES(?,?,?,?,?)',(recipient,'New conversation message','You have a new message inside AVORA.','/enquiry/'+str(eid),when))
        return {'id':cur.lastrowid}

@app.get('/api/requests')
def requests(u=Depends(optional_user)):
    with conn() as db:
        items=rows(db.execute('SELECT requests.*,users.name AS buyer_name FROM requests JOIN users ON users.id=requests.buyer_id ORDER BY requests.id DESC LIMIT 100'))
        if u:
            for r in items:r['mine']=r['buyer_id']==u['id']
        return items
@app.post('/api/requests')
def new_request(r:ServiceRequest,u=Depends(current)):
    with conn() as db:
        cur=db.execute('INSERT INTO requests(buyer_id,title,description,category,budget,quantity,city,remote,created) VALUES(?,?,?,?,?,?,?,?,?)',(u['id'],r.title,r.description,r.category,r.budget,r.quantity,r.city,int(r.remote),int(time.time())))
        db.execute('INSERT INTO events(request_id,actor_id,type,detail,created) VALUES(?,?,?,?,?)',(cur.lastrowid,u['id'],'request_created',r.title,int(time.time())))
        return {'id':cur.lastrowid}
@app.get('/api/requests/{rid}')
def get_request(rid:int,u=Depends(optional_user)):
    with conn() as db:
        r=obj(db.execute('SELECT requests.*,users.name buyer_name FROM requests JOIN users ON users.id=requests.buyer_id WHERE requests.id=?',(rid,)).fetchone())
        if not r:raise HTTPException(404,'Request not found')
        all_proposals=rows(db.execute('SELECT proposals.*,providers.name provider_name,providers.owner_id provider_owner FROM proposals JOIN providers ON providers.id=proposals.provider_id WHERE request_id=?',(rid,)))
        is_buyer=bool(u and r['buyer_id']==u['id'])
        is_provider=bool(u and any(p['provider_owner']==u['id'] and p['status']=='accepted' for p in all_proposals))
        # Confidential quotes are visible only to buyer and their own submitting provider.
        r['proposals']=[p for p in all_proposals if is_buyer or (u and p['provider_owner']==u['id'])]
        if not is_buyer and not is_provider:r['buyer_id']=None
        r['messages']=rows(db.execute('SELECT messages.*,users.name sender_name FROM messages JOIN users ON users.id=messages.sender_id WHERE request_id=? ORDER BY messages.id',(rid,))) if is_buyer or is_provider else []
        r['events']=rows(db.execute('SELECT type,detail,created FROM events WHERE request_id=? ORDER BY id DESC LIMIT 20',(rid,))) if is_buyer or is_provider else []
        # Legacy checkout records are intentionally excluded. Only verified NEAR settlements are authoritative.
        return r
@app.post('/api/requests/{rid}/proposals')
def propose(rid:int,p:ProposalIn,u=Depends(current)):
    with conn() as db:
        request=db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()
        provider=db.execute('SELECT * FROM providers WHERE id=?',(p.provider_id,)).fetchone()
        if not request or not provider:raise HTTPException(404,'Request/provider not found')
        if request['status']!='open':raise HTTPException(409,'Request is not accepting proposals')
        if provider['owner_id']!=u['id']:raise HTTPException(403,'You must own this provider profile')
        if db.execute("SELECT 1 FROM proposals WHERE request_id=? AND provider_id=? AND status IN ('pending','accepted')",(rid,p.provider_id)).fetchone():raise HTTPException(409,'This business already submitted a proposal for this request')
        if request['buyer_id']==u['id']:raise HTTPException(400,'Cannot quote your own request')
        cur=db.execute('INSERT INTO proposals(request_id,provider_id,amount,note,created) VALUES(?,?,?,?,?)',(rid,p.provider_id,p.amount,p.note,int(time.time())))
        db.execute('INSERT INTO avora_notifications(recipient_id,title,body,link,created) VALUES(?,?,?,?,?)',(request['buyer_id'],'New provider proposal','A provider responded to your request.','/requests/'+str(rid),int(time.time())))
        return {'id':cur.lastrowid}
@app.post('/api/proposals/{pid}/accept')
def accept(pid:int,u=Depends(current)):
    with conn() as db:
        p=db.execute('SELECT proposals.*,requests.buyer_id,requests.status request_status FROM proposals JOIN requests ON requests.id=proposals.request_id WHERE proposals.id=?',(pid,)).fetchone()
        if not p:raise HTTPException(404,'Proposal not found')
        if p['buyer_id']!=u['id']:raise HTTPException(403,'Only the buyer can accept')
        if p['request_status']!='open':raise HTTPException(409,'Request is no longer open')
        db.execute("UPDATE proposals SET status='declined' WHERE request_id=? AND id<>? AND status='pending'",(p['request_id'],pid))
        db.execute('UPDATE proposals SET status=? WHERE id=?',('accepted',pid))
        db.execute('UPDATE requests SET status=? WHERE id=?',('agreed',p['request_id']))
        db.execute('INSERT INTO events(request_id,actor_id,type,detail,created) VALUES(?,?,?,?,?)',(p['request_id'],u['id'],'proposal_accepted','Buyer approved proposal '+str(pid),int(time.time())))
        return {'ok':True}
@app.post('/api/requests/{rid}/messages')
def send_message(rid:int,m:MessageIn,u=Depends(current)):
    with conn() as db:
        r=db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()
        if not r:raise HTTPException(404,'Request not found')
        allowed=r['buyer_id']==u['id'] or bool(db.execute("SELECT 1 FROM proposals JOIN providers ON providers.id=proposals.provider_id WHERE proposals.request_id=? AND providers.owner_id=? AND proposals.status='accepted'",(rid,u['id'])).fetchone())
        if not allowed:raise HTTPException(403,'Only request participants can message')
        db.execute('INSERT INTO messages(request_id,sender_id,body,created) VALUES(?,?,?,?)',(rid,u['id'],m.body,int(time.time())))
        return {'ok':True}
@app.post('/api/reports')
def report(r:ReportIn,u=Depends(current)):
    if r.target_type not in ('provider','request','message','user'):raise HTTPException(400,'Invalid report target')
    with conn() as db:
        target_table={'provider':'providers','request':'requests','message':'messages','user':'users'}[r.target_type]
        if not db.execute(f'SELECT 1 FROM {target_table} WHERE id=?',(r.target_id,)).fetchone():raise HTTPException(404,'Report target not found')
        cur=db.execute('INSERT INTO reports(author_id,target_type,target_id,reason,created) VALUES(?,?,?,?,?)',(u['id'],r.target_type,r.target_id,r.reason,int(time.time())))
        return {'id':cur.lastrowid,'status':'open','note':'A report is not proof of wrongdoing.'}
@app.get('/api/reports')
def my_reports(u=Depends(current)):
    with conn() as db:return rows(db.execute('SELECT * FROM reports WHERE author_id=? ORDER BY id DESC',(u['id'],)))
@app.post('/api/reviews')
def review(r:ReviewIn,u=Depends(current)):
    # The retired legacy payment-ID review flow must never attest to a NEAR payment.
    # A future review endpoint will reference NEAR proof IDs with strict buyer/provider ownership checks.
    raise HTTPException(410,'Legacy payment reviews are unavailable. Verified NEAR reviews are not implemented yet.')

# Agentic opportunity assembly: deterministic constraints and evidence, plus optional genuine LLM explanations.
def candidate_score(p, request):
    text=(request['title']+' '+request['description']+' '+request['category']).lower()
    words={w for w in re.findall(r'[a-z]{3,}',text) if w not in {'with','from','this','that','need','some','help','have','would','want','please','looking','project','business'}}
    skills=(p['name']+' '+p['category']+' '+p['skills']+' '+p['bio']).lower()
    overlap=sum(w in skills for w in words)
    local=request['city'].lower() in p['city'].lower()
    eligible=local or bool(request['remote'] and p['remote'])
    score=overlap*12+(7 if local else 0)+(4 if p['verified'] else 0)+p['rating']
    return score,eligible,overlap

def assemble(r,people):
    ranked=[]
    for p in people:
        score,eligible,overlap=candidate_score(p,r)
        if eligible and overlap>0:
            ranked.append({**p,'match_score':round(score,1),'available_capacity':p['capacity']})
    ranked.sort(key=lambda x:-x['match_score'])
    remaining=r['quantity']; selected=[];total=0
    for p in ranked:
        if remaining<=0:break
        count=min(remaining,p['capacity'])
        selected.append({'provider_id':p['id'],'name':p['name'],'units':count,'unit_price_usd':p['price'],'subtotal_usd':count*p['price'],'capacity_source':'provider listing (unverified demo data)','fit':p['match_score']})
        total+=count*p['price'];remaining-=count
    return {'plan':selected,'covered_units':r['quantity']-remaining,'requested_units':r['quantity'],'missing_units':remaining,'estimated_total_usd':total,'fits_budget':total<=r['budget'],'assumptions':['Sample provider capacity and prices are illustrative and unverified.','Allocation is deterministic; merchant participation and delivery require explicit confirmation.','Budget and amounts are denominated in USD for the demo.'],'ranked':ranked[:8]}

async def ai_explain(system,user_data):
    key=os.getenv('AI_API_KEY') or os.getenv('GROQ_API_KEY','')
    if not key:return {'mode':'rules_only','text':'AI is not connected. These matches and allocations were computed using a reproducible deterministic rules engine; configure AI_API_KEY to enable model-generated grounded analysis.'}
    base=os.getenv('AI_BASE_URL', 'https://api.groq.com/openai/v1' if (os.getenv('GROQ_API_KEY') or key.startswith('gsk_')) else 'https://api.openai.com/v1').rstrip('/')
    model=os.getenv('AI_MODEL','openai/gpt-oss-120b' if 'groq.com' in base else 'gpt-4o-mini')
    async with httpx.AsyncClient(timeout=25) as client:
        try:
            resp=await client.post(base+'/chat/completions',headers={'Authorization':'Bearer '+key},json={'model':model,'temperature':0.2,'max_tokens':350,'messages':[{'role':'system','content':system+' Never fabricate records, inventory, transactions, or approval. If uncertain say so.'},{'role':'user','content':json.dumps(user_data)[:9000]}]})
            resp.raise_for_status()
            return {'mode':'llm','model':model,'text':resp.json()['choices'][0]['message']['content']}
        except Exception as exc:
            return {'mode':'ai_unavailable','text':'AI request could not complete. Deterministic matching remains available.','error_type':type(exc).__name__}
@app.post('/api/ai/assemble/{rid}')
async def ai_assemble(rid:int,u=Depends(current)):
    throttle('assemble:'+str(u['id']),30,3600)
    with conn() as db:
        r=obj(db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone())
        if not r:raise HTTPException(404,'Request not found')
        if r['buyer_id']!=u['id'] and not db.execute('SELECT 1 FROM proposals JOIN providers ON providers.id=proposals.provider_id WHERE proposals.request_id=? AND providers.owner_id=?',(rid,u['id'])).fetchone():raise HTTPException(403,'Only project participants may run private analysis')
        people=rows(db.execute('SELECT * FROM providers'))
    result=assemble(r,people)
    result['assistant']=await ai_explain('You are the AVORA 5IR commerce coordinator. Explain suitability, fairness, uncertainty, trade-offs and buyer/provider consent concisely. Only use supplied evidence.',{'request':r,'allocation':result['plan'],'constraints':result['assumptions'],'missing':result['missing_units']})
    return result
@app.post('/api/ai/guardian/{rid}')
async def ai_guardian(rid:int,u=Depends(current)):
    throttle('guardian:'+str(u['id']),30,3600)
    with conn() as db:
        r=obj(db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone())
        if not r:raise HTTPException(404,'Request not found')
        participant=r['buyer_id']==u['id'] or bool(db.execute("SELECT 1 FROM proposals JOIN providers ON providers.id=proposals.provider_id WHERE proposals.request_id=? AND providers.owner_id=? AND proposals.status='accepted'",(rid,u['id'])).fetchone())
        if not participant:raise HTTPException(403,'Not a participant in this project')
        messages=rows(db.execute('SELECT body FROM messages WHERE request_id=?',(rid,)))
    flags=[]
    for m in messages:
        t=m['body'].lower()
        if any(x in t for x in ['gift card','crypto wallet','pay me outside','send your password','wire transfer']): flags.append('Possible off-platform payment or credential request in a message')
    explanation=await ai_explain('You are a cautious trust and safety analyst. Flag signals, not guilt. Do not perform enforcement. Mention uncertainty.',{'request':r,'flags':flags})
    return {'flags':flags,'assessment':'Review recommended' if flags else 'No defined rule triggered; this does not establish safety.','assistant':explanation}

# NEAR opportunity coordination, approvals, rescue and verifiable testnet receipts.
from app.near_workflows import install_near_workflows
install_near_workflows(app, conn, current)

from app.avora_autonomy import install_avora_autonomy
install_avora_autonomy(app, conn, current, assemble, ai_explain, candidate_score)

# Provider-owned catalogue, example inventory, and transparent demo checkout.
from app.marketplace import install as install_marketplace
install_marketplace(app,conn,current)

# Customizable profiles, owner-controlled business settings, consent-first inbox, and request matches.
from app.experience import install as install_experience
install_experience(app,conn,current,candidate_score)

# Optional marketplace operations: bookings, seller-entered delivery, refund requests and notification inbox.
from app.operations import install as install_operations
install_operations(app, conn, current)
