import csv, io, json, os, re, sqlite3, threading, time, ipaddress, socket
from collections import deque
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
from adapters import detect, shopify_products, microdata, dashery_product, DASHERY_DETAIL, dashery_cards, dashery_next
from readiness import issues, pin_issues, stock_value
from flask import Flask, request, redirect, render_template, Response, abort, jsonify

app = Flask(__name__)
DB = os.getenv('DB', 'data/catalog.db')
AGENT = 'CatalogRipper/2.12'
MAX_PRODUCTS = 5000
MAX_PAGES = 15000
MAX_SECONDS = 12 * 3600
MARKETPLACES = ('amazon','ebay','walmart','etsy','aliexpress','temu','alibaba','mercari','rakuten','shein','target')
def blocked(host):
    return any(label in MARKETPLACES for label in (host or '').lower().rstrip('.').split('.'))

os.makedirs(os.path.dirname(DB) or '.', exist_ok=True)

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    return c
with db() as c:
    c.execute('CREATE TABLE IF NOT EXISTS crawl_checkpoint (url TEXT PRIMARY KEY, next_url TEXT, pages INTEGER, cooldown REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS products (id TEXT PRIMARY KEY, url TEXT, title TEXT, description TEXT, image TEXT, price TEXT, currency TEXT, availability TEXT, brand TEXT, sku TEXT, source TEXT)')
FIELDS = 'id url title description image price currency availability brand sku source'.split()

def canonical(url):
    p = urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password: return ''
    return urlunsplit((p.scheme,p.netloc,p.path or '/',p.query,''))

def scalar(x):
    if isinstance(x,dict): return scalar(x.get('name') or x.get('url') or x.get('contentUrl'))
    if isinstance(x,list): return scalar(x[0]) if x else ''
    return str(x) if x is not None else ''

def walk(x):
    if isinstance(x,dict):
        yield x
        for v in x.values(): yield from walk(v)
    elif isinstance(x,list):
        for v in x: yield from walk(v)

def extract(raw,url):
    import hashlib
    s=BeautifulSoup(raw,'html.parser'); rows=[]; platform=detect(s,url)
    def meta(k):
        t=s.find('meta',attrs={'property':k}) or s.find('meta',attrs={'name':k}) or s.find('meta',attrs={'itemprop':k})
        return t.get('content','') if t else ''
    def add(p,o,source):
        link=canonical(urljoin(url,scalar(o.get('url') or p.get('url')) or url)) or url
        title=scalar(p.get('name')); sku=scalar(o.get('sku') or p.get('sku'))
        if not title: return
        price=scalar(o.get('price')); currency=scalar(o.get('priceCurrency'))
        image=scalar(o.get('image') or p.get('image')); image=canonical(urljoin(url,image)) if image else ''
        key=hashlib.sha256((link+'|'+(sku or title)).encode()).hexdigest()[:24]
        rows.append(dict(id=key,url=link,title=title,description=BeautifulSoup(scalar(p.get('description')),'html.parser').get_text(' ',strip=True),image=image,price=price,currency=currency,availability=scalar(o.get('availability')).rsplit('/',1)[-1],brand=scalar(p.get('brand')),sku=sku,source=platform+' / '+source))
    for tag in s.select('script[type="application/ld+json"]'):
        try: data=json.loads(tag.string or tag.get_text())
        except (ValueError,TypeError): continue
        for p in walk(data):
            types=p.get('@type',[]); types=[types] if isinstance(types,str) else types
            if not isinstance(types,list) or not any(str(t).rsplit('/',1)[-1]=='Product' for t in types): continue
            offers=p.get('offers',[]); offers=[offers] if isinstance(offers,dict) else offers
            # AggregateOffer ranges are not individual purchasable offers.
            offers=[o for o in offers if isinstance(o,dict) and o.get('@type')!='AggregateOffer'] if isinstance(offers,list) else []
            for o in offers or [{}]: add(p,o,'json-ld')
            for v in p.get('hasVariant',[]) if isinstance(p.get('hasVariant'),list) else []:
                if isinstance(v,dict) and not v.get('@type'):
                    vo=v.get('offers',{}); add({**p,**v},vo if isinstance(vo,dict) else {},'variant')
    if platform=='Dashery':
        rows.clear()
        for p,o in dashery_product(s,url): add(p,o,'dashery detail')
        if not rows:
            for p,o in dashery_cards(s,url): add(p,o,'dashery listing')
    if platform=='Shopify':
        variants=list(shopify_products(s,url))
        if variants:
            rows.clear()
            for p,o in variants: add(p,o,'embedded variants')
    if not rows and platform!='Dashery':
        for p,o in microdata(s): add(p,o,'microdata')
    if not rows and platform!='Dashery' and (meta('og:type')=='product' or meta('product:price:amount') or meta('og:price:amount')):
        add({'name':meta('og:title') or (s.title.get_text(strip=True) if s.title else ''),'description':meta('og:description'),'image':meta('og:image')},{'price':meta('product:price:amount') or meta('og:price:amount'),'priceCurrency':meta('product:price:currency') or meta('og:price:currency'),'availability':meta('product:availability')},'open-graph')
    rows=list({r['id']:r for r in rows}.values())
    links=[canonical(urljoin(url,a['href'])) for a in s.select('a[href]')]
    if platform=='Dashery' and any(r['source']=='Dashery / dashery listing' for r in rows):
        return rows,dashery_next(s,url)
    if platform=='Dashery':
        links=[urlunsplit(urlsplit(x)._replace(path='/'+urlsplit(x).path.lstrip('/'))) if x and DASHERY_DETAIL.fullmatch('/'+urlsplit(x).path.lstrip('/')) else x for x in links]
    return rows,links

state={'status':'idle','pages':0,'products':0,'message':''}; lock=threading.Lock(); stop=threading.Event()

def host_key(host):
    return (host or "").lower().removeprefix("www.")

def crawl(start,limit):
    with db() as c:
        checkpoint=c.execute("SELECT * FROM crawl_checkpoint WHERE url=?",(start,)).fetchone()
        cooldown=max((r["cooldown"] for r in c.execute("SELECT url,cooldown FROM crawl_checkpoint") if host_key(urlsplit(r["url"]).hostname)==host_key(urlsplit(start).hostname)),default=0)
    if cooldown>time.time():
        state.update(status="stopped",message="Rate-limit cooldown active; retry after "+time.strftime("%Y-%m-%d %H:%M UTC",time.gmtime(cooldown)))
        lock.release(); return
    pending=checkpoint["next_url"] if checkpoint and checkpoint["next_url"] else start
    completed=checkpoint["pages"] if checkpoint and checkpoint["next_url"] else 0
    state["pages"]=completed
    def save_checkpoint(next_url,cooldown=0):
        with db() as c: c.execute("INSERT OR REPLACE INTO crawl_checkpoint VALUES (?,?,?,?)",(start,next_url,state["pages"],cooldown))
    session=requests.Session(); session.trust_env=False; session.headers['User-Agent']=AGENT
    origin=urlsplit(start); host=host_key(origin.hostname); last=0; started=time.monotonic(); requests_count=0
    def fetch(u, redirects=0, check_robots=True):
        nonlocal last, requests_count, final_url
        if stop.is_set() or time.monotonic()-started >= MAX_SECONDS or requests_count >= MAX_PAGES: raise RuntimeError("Scan stopped or request/time budget reached")
        requests_count += 1
        p=urlsplit(u)
        if blocked(p.hostname) or host_key(p.hostname)!=host or p.port not in (None,80,443): raise ValueError('Outside permitted host or port')
        for addr in socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(addr[4][0]).is_global: raise ValueError('Non-public network address')
        if check_robots and not robots.can_fetch(AGENT,u): return None
        time.sleep(max(0,delay-(time.monotonic()-last))); last=time.monotonic()
        with session.get(u,timeout=(8,20),allow_redirects=False,stream=True) as r:
            if r.status_code==429:
                from email.utils import parsedate_to_datetime
                retry=r.headers.get('Retry-After',''); wait=3600
                try: wait=max(wait,int(retry))
                except ValueError:
                    try: wait=max(wait,parsedate_to_datetime(retry).timestamp()-time.time())
                    except (ValueError,TypeError,OverflowError): pass
                save_checkpoint(pending,time.time()+wait)
            if r.status_code in (401,403,429): raise RuntimeError(f'Access denied or rate limited: {r.status_code}; Retry-After: {r.headers.get("Retry-After", "not supplied")}')
            if 300<=r.status_code<400:
                target=canonical(urljoin(u,r.headers.get('Location','')))
                if not target or redirects>=5 or host_key(urlsplit(target).hostname)!=host:
                    raise RuntimeError(f'Redirect outside authorized storefront or redirect loop: {target}')
                if urlsplit(u).scheme=='https' and urlsplit(target).scheme!='https':
                    raise RuntimeError('HTTPS downgrade refused')
                r.close()
                return fetch(target,redirects+1,check_robots)
            if r.status_code==404: return None
            r.raise_for_status(); chunks=[]; n=0
            for chunk in r.iter_content(65536):
                n+=len(chunk)
                if n>20_000_000: raise ValueError('Response too large')
                chunks.append(chunk)
            final_url=u
            return b''.join(chunks)
    final_url=start
    delay=10.0
    try:
        robots=RobotFileParser(); raw=fetch(f'{origin.scheme}://{origin.netloc}/robots.txt',check_robots=False); robots.parse(raw.decode(errors='replace').splitlines() if raw else [])
        delay=max(delay,robots.crawl_delay(AGENT) or robots.crawl_delay('*') or 0)
        queue=deque([pending]); seen=set(); listing_mode=(origin.hostname or '').endswith('.dashery.com'); maps=deque([] if listing_mode else (robots.site_maps() or [f'{origin.scheme}://{origin.netloc}/sitemap.xml'])); mapseen=set()
        while maps and len(mapseen)<30 and not stop.is_set():
            u=maps.popleft()
            if u in mapseen or host_key(urlsplit(u).hostname)!=host or not robots.can_fetch(AGENT,u): continue
            mapseen.add(u); raw=fetch(u)
            if not raw: continue
            from defusedxml.ElementTree import fromstring
            try: root=fromstring(raw)
            except Exception: continue
            locs=[e.text.strip() for e in root.iter() if e.tag.rsplit('}',1)[-1]=='loc' and e.text]
            if root.tag.rsplit('}',1)[-1]=='sitemapindex': maps.extend(locs[:100])
            else: queue.extend(locs[:limit*4])
        while queue and state['pages']<limit and not stop.is_set():
            u=canonical(queue.popleft())
            if not u or u in seen or host_key(urlsplit(u).hostname)!=host or not robots.can_fetch(AGENT,u): continue
            seen.add(u)
            if re.search(r'/(cart|checkout|account|login|logout|search)(/|\?|$)',u,re.I): continue
            if re.search(r'\.(jpg|png|webp|pdf|zip|css|js|svg|gif|mp4)(\?|$)',u,re.I): continue
            pending=u; state['message']='Fetching '+u; raw=fetch(u)
            if not raw: continue
            if b'cf_chl_opt' in raw or b'Just a moment...' in raw: raise RuntimeError('Challenge page: scan stopped')
            rows,links=extract(raw,final_url)
            state['pages']+=1
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                existing={r['id'] for r in c.execute('SELECT id,url FROM products') if host_key(urlsplit(r['url']).hostname)==host}
                for r in rows:
                    if host_key(urlsplit(r['url']).hostname)!=host: continue
                    if r['source'] in ('Dashery / dashery detail','Dashery / dashery listing'):
                        for old in c.execute('SELECT id,url FROM products WHERE source LIKE ?',('Dashery / %',)).fetchall():
                            if old['id']!=r['id'] and old['url']==r['url']:
                                c.execute('DELETE FROM products WHERE id=?',(old['id'],)); existing.discard(old['id'])
                    if r['id'] not in existing and len(existing)>=MAX_PRODUCTS: break
                    prior=c.execute('SELECT availability FROM products WHERE id=?',(r['id'],)).fetchone()
                    if prior and prior['availability']=='made_to_order' and not stock_value(r['availability']): r['availability']='made_to_order'
                    c.execute('INSERT OR REPLACE INTO products VALUES ('+','.join('?' for _ in FIELDS)+')',[r[k] for k in FIELDS])
                    existing.add(r['id'])
                state['products']=len(existing)
            if state['products']>=MAX_PRODUCTS:
                state.update(status='complete',message='5,000 product record limit reached for this host.'); return
            if listing_mode and any(r['source']=='Dashery / dashery listing' for r in rows):
                queue.clear(); queue.extend(x for x in links if x not in seen); save_checkpoint(queue[0] if queue else ''); continue
            # Prioritize actual detail pages over category and pagination links.
            for link in sorted(links,key=lambda x: bool(DASHERY_DETAIL.fullmatch(urlsplit(x).path))):
                if link and host_key(urlsplit(link).hostname)==host and link not in seen and len(queue)<limit*10:
                    if DASHERY_DETAIL.fullmatch(urlsplit(link).path) or re.search(r'/products?/|/shop/|/collections/|/category/|/catalog/|/p/|[?&]page=',link,re.I): queue.appendleft(link)
                    else: queue.append(link)
        state.update(status='stopped' if stop.is_set() else 'complete',message='Review extracted data before publishing.')
    except Exception as e: state.update(status='stopped',message=str(e))
    finally: session.close(); lock.release()

@app.get('/')
def home():
    q=request.args.get('q','')[:200]; page=max(1,request.args.get('page',1,type=int)); pattern='%'+q+'%'
    view=request.args.get('view','grid'); view=view if view in ('grid','list') else 'grid'
    source=request.args.get('source','')[:200]; stock=request.args.get('stock',''); sort=request.args.get('sort','recent')
    where=['(title LIKE ? OR sku LIKE ? OR source LIKE ? OR url LIKE ?)']; args=[pattern]*4
    if source: where.append('source LIKE ?'); args.append(source+' / %')
    if stock=='in': where.append("lower(availability) IN ('instock','in_stock','made_to_order')")
    if stock=='out': where.append("lower(availability) IN ('outofstock','out_of_stock')")
    order={'recent':'rowid DESC','title':'title COLLATE NOCASE,id','price':'currency,CAST(price AS REAL),id'}.get(sort,'rowid DESC')
    clause=' AND '.join(where)
    with db() as c:
        allrows=c.execute('SELECT * FROM products').fetchall()
        count=c.execute('SELECT count(*) FROM products WHERE '+clause,args).fetchone()[0]
        pages=max(1,(count+47)//48); page=min(page,pages)
        rows=c.execute('SELECT * FROM products WHERE '+clause+' ORDER BY '+order+' LIMIT 48 OFFSET ?',args+[(page-1)*48]).fetchall()
    stats=dict(total=len(allrows),images=sum(bool(r['image']) for r in allrows),review=sum(bool(issues(r)) for r in allrows),domains=len({urlsplit(r['url']).hostname for r in allrows}))
    from collections import Counter
    from pins import eligible
    hosts=sorted({urlsplit(r['url']).hostname for r in allrows if urlsplit(r['url']).hostname})
    stats['pins']=len(list(eligible(allrows)))
    stats['shopping']=sum(not issues(r) for r in allrows)
    breakdown=Counter(issue for r in allrows for issue in issues(r))
    sources=sorted({r['source'].split(' / ')[0] for r in allrows if r['source']})
    return render_template('dashboard.html',rows=rows,count=count,state=dict(state),q=q,page=page,pages=pages,view=view,source=source,sources=sources,stock=stock,sort=sort,stats=stats,issues=issues,pin_issues=pin_issues,breakdown=breakdown.most_common(),stock_value=stock_value,hosts=hosts)

@app.post('/availability')
def set_availability():
    host=request.form.get('host','')
    if not host or request.form.get('confirmed')!='yes': abort(400)
    if not lock.acquire(False): return 'Stop the active scan before editing availability.',409
    try:
        with db() as c:
            ids=[r['id'] for r in c.execute('SELECT id,url,availability FROM products') if urlsplit(r['url']).hostname==host and not stock_value(r['availability'])]
            c.executemany("UPDATE products SET availability='made_to_order' WHERE id=?",[(i,) for i in ids])
    finally: lock.release()
    return redirect('/')

@app.get('/status.json')
def status_json(): return jsonify(dict(state))

@app.get('/product/<id>')
def product_detail(id):
    with db() as c: row=c.execute('SELECT * FROM products WHERE id=?',(id,)).fetchone()
    if row is None: abort(404)
    return render_template('product.html',r=row,issues=issues(row),pin_issues=pin_issues(row),stock_value=stock_value)

@app.post('/scan')
def scan():
    u=canonical(request.form.get('url',''))
    if not u or blocked(urlsplit(u).hostname) or not request.form.get('permission'): return 'Valid authorized non-marketplace URL required',400
    try: limit=max(1,min(MAX_PAGES,int(request.form.get('limit',500))))
    except ValueError: return 'Invalid limit',400
    if lock.acquire(False):
        stop.clear(); state.update(status='running',pages=0,products=0,message=''); threading.Thread(target=crawl,args=(u,limit),daemon=True).start()
    return redirect('/')
@app.post('/stop')
def halt(): stop.set(); return redirect('/')
@app.get('/export.csv')
def export():
    b=io.StringIO(); w=csv.writer(b); w.writerow(FIELDS)
    with db() as c:
        for r in c.execute('SELECT * FROM products'): w.writerow(["'"+v if v and v.startswith(('=','+','-','@','\t','\r')) else v for v in r])
    return Response(b.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=catalog-review.csv'})

@app.get('/export.xml')
def export_xml():
    from xml.etree.ElementTree import Element, SubElement, tostring, register_namespace
    ns='http://base.google.com/ns/1.0'; register_namespace('g',ns)
    root=Element('rss',version='2.0'); channel=SubElement(root,'channel'); SubElement(channel,'title').text='CatalogRipper review feed'
    with db() as c:
        for r in c.execute('SELECT * FROM products ORDER BY id'):
            if issues(r): continue
            stock=stock_value(r['availability'])
            if not stock or not re.fullmatch(r'\d+(?:\.\d{1,2})?',r['price']) or not re.fullmatch('[A-Z]{3}',r['currency']): continue
            item=SubElement(channel,'item')
            for k,v in {'id':r['id'],'title':r['title'],'description':r['description'],'link':r['url'],'image_link':r['image'],'price':r['price']+' '+r['currency'],'availability':stock,'brand':r['brand']}.items():
                if v: SubElement(item,'{'+ns+'}'+k).text=v
    return Response(tostring(root,encoding='utf-8',xml_declaration=True),mimetype='application/xml',headers={'Content-Disposition':'attachment; filename=catalog-DRAFT.xml'})


def csv_response(name,fields,rows):
    b=io.StringIO(); w=csv.writer(b); w.writerow(fields)
    for row in rows:
        w.writerow(["'"+str(v) if str(v).startswith(('=','+','-','@','\t','\r')) else v for v in row])
    return Response(b.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename='+name})

@app.get('/validation.csv')
def validation():
    with db() as c:
        return csv_response('validation.csv',['id','title','url','pin_metadata_ready','shopping_metadata_ready','pin_issues','shopping_issues','manual_review'],[(r['id'],r['title'],r['url'],not pin_issues(r),not issues(r),'; '.join(pin_issues(r)),'; '.join(issues(r)),'Verify condition, rights, variant, image, identifiers and eligibility') for r in c.execute('SELECT * FROM products')])

@app.get('/meta.csv')
@app.get('/pinterest.csv')
def platform_csv():
    platform='meta' if request.path=='/meta.csv' else 'pinterest'
    fields=['id','title','description','link','image_link','price','availability','brand','condition']
    with db() as c:
        rows=[(r['id'],r['title'],r['description'],r['url'],r['image'],r['price']+' '+r['currency'],stock_value(r['availability']).replace('_',' ') if platform=='meta' else stock_value(r['availability']),r['brand'],'') for r in c.execute('SELECT * FROM products') if not issues(r)]
    return csv_response(platform+'-DRAFT.csv',fields,rows)

@app.route('/pinterest-pins', methods=['GET','POST'])
def pinterest_pins():
    from pins import eligible, build, retry_report
    import zipfile
    with db() as c:
        rows=c.execute('SELECT * FROM products ORDER BY url,id').fetchall()
    hosts=sorted({urlsplit(r['url']).hostname for r in rows if canonical(r['url'] or '')})
    host=request.form.get('host','')
    selected=[r for r in rows if not host or urlsplit(r['url']).hostname==host]
    count=len(list(eligible(selected)))
    if request.method=='GET': return render_template('pins.html',hosts=hosts,count=count,total=len(rows))
    if request.form.get('permission')!='on': abort(400,'Confirm rights and review before exporting.')
    try:
        report=request.files.get('report')
        if report and report.filename:
            raw=report.stream.read(5*1024*1024+1)
            if len(raw)>5*1024*1024: raise ValueError('Report exceeds 5 MB.')
            files=retry_report(raw.decode('utf-8-sig'))
        else: files=build(selected,request.form.get('board',''),request.form.get('keywords',''),request.form.get('publish',''),int(request.form.get('size','200')))
    except ValueError as e: abort(400,str(e))
    if not files: abort(400,'No eligible Pins or failed report rows to export.')
    if len(files)==1: return Response(files[0],content_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=pinterest-pins-001.csv'})
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        for i,f in enumerate(files,1): z.writestr(f'pinterest-pins-{i:03}.csv',f)
    return Response(b.getvalue(),mimetype='application/zip',headers={'Content-Disposition':'attachment; filename=pinterest-pins.zip'})
