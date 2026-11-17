"""Import an owner-provided historical catalog review CSV without network access."""
import argparse,csv,hashlib,re,sqlite3,os
from urllib.parse import urlsplit,urlunsplit

def restore(path,db,source_host,target_host):
    if not target_host.endswith('.dashery.com') or target_host.count('.')!=2: raise ValueError('Expected individual Dashery storefront hostname')
    count=0
    with open(path,encoding='utf-8-sig',newline='') as f, sqlite3.connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        existing={r[0]:r[1] for r in c.execute('SELECT url,id FROM products') if urlsplit(r[0]).hostname==target_host}
        total=c.execute('SELECT count(*) FROM products WHERE url LIKE ?',('https://'+target_host+'/%',)).fetchone()[0]
        for r in csv.DictReader(f):
            p=urlsplit(r['link']); im=urlsplit(r['image_candidate']); price=re.fullmatch(r'(\d+(?:\.\d{1,2})?) ([A-Z]{3})',r['page_price'].strip())
            if p.scheme!='https' or p.hostname!=source_host or not re.fullmatch(r'/products/\d+-[^/]+',p.path) or not price or not r['title'].strip(): continue
            if im.scheme!='https' or im.hostname!='images.teepublic.com' or '/i_m' not in im.path or 'wmk' in im.path.lower(): continue
            url=urlunsplit(('https',target_host,p.path,'','')); title=r['title']; key=hashlib.sha256((url+'|'+title).encode()).hexdigest()[:24]
            if url in existing: continue # retain newer live data
            if total>=5000: break
            c.execute('INSERT INTO products (id,url,title,description,image,price,currency,availability,brand,sku,source) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(key,url,title,r['description'],r['image_candidate'],price[1],price[2],'','','','Dashery / historical import'))
            existing[url]=key; total+=1; count+=1
    return count
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('csv');p.add_argument('--db',default=os.getenv('DB','data/catalog.db'));p.add_argument('--source-host',required=True);p.add_argument('--target-host',required=True);a=p.parse_args();print('Imported',restore(a.csv,a.db,a.source_host,a.target_host),'historical listings')
