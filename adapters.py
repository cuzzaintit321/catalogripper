"""Offline parsers for public, embedded storefront metadata; no extra requests."""
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit, parse_qsl, urlencode, urlunsplit

def detect(soup, url):
    if (urlsplit(url).hostname or '').endswith('.dashery.com'): return 'Dashery'
    html=str(soup).lower()
    for platform, markers in {'Shopify':('cdn.shopify.com','shopify.theme','shopify-section'), 'WooCommerce':('woocommerce','wc-block'), 'Magento':('mage/cookies','magento','mage-init'), 'BigCommerce':('cdn11.bigcommerce.com','stencil-utils','bigcommerce'), 'Dashery':('dashery.com','dashery'),}.items():
        if any(m in html for m in markers): return platform
    return 'Generic'

def shopify_products(soup,url):
    """Read explicitly embedded product objects with actual variant IDs and prices."""
    for tag in soup.select('script[type="application/json"]'):
        try: obj=json.loads(tag.string or tag.get_text())
        except (ValueError,TypeError): continue
        if not isinstance(obj,dict): continue
        p=obj.get('product',obj)
        if not isinstance(p,dict) or not p.get('title') or not isinstance(p.get('variants'),list): continue
        if not p.get('handle') or '/products/'+str(p['handle']) not in urlsplit(url).path: continue
        for v in p['variants']:
            if not isinstance(v,dict) or not v.get('id'): continue
            # Shopify Liquid product JSON represents prices in minor units; only accept integers.
            price=v.get('price'); currency=obj.get('currency') or p.get('currency') or ''
            if currency in ('USD','CAD','AUD','GBP','EUR','NZD') and type(price) is int: price=str(Decimal(price)/100)
            else: price=''
            parts=urlsplit(url); q=dict(parse_qsl(parts.query)); q['variant']=str(v['id']); link=urlunsplit(parts._replace(query=urlencode(q)))
            image=v.get('featured_image') or p.get('featured_image') or ''
            if isinstance(image,dict): image=image.get('src') or image.get('url') or ''
            yield {'name':p['title']+(' – '+v['title'] if v.get('title') and v['title']!='Default Title' else ''),'description':p.get('description',''),'brand':p.get('vendor',''),'image':image}, {'url':link,'sku':v.get('sku') or str(v['id']),'price':price,'priceCurrency':currency,'availability':{True:'InStock',False:'OutOfStock'}.get(v.get('available'),'')}

def microdata(soup):
    for p in soup.select('[itemscope][itemtype]'):
        if not p.get('itemtype','').rstrip('/').endswith('/Product'): continue
        def prop(name):
            e=p.select_one('[itemprop="'+name+'"]')
            return (e.get('content') or e.get('href') or e.get('src') or e.get_text(' ',strip=True)) if e else ''
        yield {k:prop(k) for k in ('name','description','image','brand','sku')},{k:prop(k) for k in ('price','priceCurrency','availability','url')}

import re
DASHERY_DETAIL = re.compile(r'^/(?:products|hoodie|crewneck-sweatshirt|long-sleeve-t-shirt|socks|hat|sticker|mug|kids-t-shirt)/\d+-[^/]+/?$')
def dashery_product(soup,url):
    """Use actual fetched storefront URL, not cross-domain OG canonical aliases."""
    if not DASHERY_DETAIL.fullmatch('/'+urlsplit(url).path.lstrip('/')): return
    def meta(k):
        e=soup.find('meta',property=k)
        return e.get('content','') if e else ''
    if meta('og:type')!='product': return
    title=soup.title.get_text(strip=True).split(' | ')[0] if soup.title else meta('og:title')
    # OG images are artwork previews, not merchandise. Prefer front mockups only.
    image=''
    for img in soup.select('img.mockup_front.jsProductMainImage, img.mockup_front, img.mockup.jsProductMainImage'):
        picture=img.find_parent('picture')
        candidates=[img.get('src',''),img.get('data-src','')]
        if picture:
            candidates.extend(x.get('srcset','').split()[0] for x in picture.select('source[srcset]') if x.get('srcset','').strip())
        for src in candidates:
            if src.startswith(('https://','//')) and 'wmk' not in src.lower() and '/i_p' not in src.lower():
                image=urljoin(url,src); break
        if image: break
    if not image: return
    category=urlsplit(url).path.strip('/').split('/')[0]
    kind={'products':'T-Shirt','hoodie':'Hoodie','crewneck-sweatshirt':'Crewneck Sweatshirt','long-sleeve-t-shirt':'Long Sleeve T-Shirt','socks':'Socks','hat':'Hat','sticker':'Sticker','mug':'Mug','kids-t-shirt':'Kids T-Shirt'}[category]
    if kind.lower() not in title.lower(): title=title+' – '+kind
    price=meta('og:price:amount'); currency=meta('og:price:currency')
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?',price) or not re.fullmatch(r'[A-Z]{3}',currency): return
    yield {'name':title,'description':meta('og:description'),'image':image}, {'url':urlunsplit(urlsplit(url)._replace(path='/'+urlsplit(url).path.strip('/'),query='',fragment='')),'price':price,'priceCurrency':currency}

def dashery_cards(soup,url):
    """Extract visible merchandise cards, not analytics prices or artwork."""
    for tile in soup.select('.tp-design-tile[data-currency-code]'):
        a=tile.select_one('a.tp-design-tile__title_link[href]'); preview=tile.select_one('a[data-image-type="mockup"] picture')
        if not a or not preview: continue
        link=urljoin(url,a['href']); p=urlsplit(link)
        if p.hostname!=urlsplit(url).hostname or not DASHERY_DETAIL.fullmatch(p.path): continue
        title=a.get_text(' ',strip=True); currency=tile.get('data-currency-code','')
        pricing=tile.select_one('.tp-design-tile__pricing');
        if not pricing: continue
        sale=pricing.select_one('[class*="price--sale"], [class*="price--discount"]')
        regular=pricing.select_one('.tp-design-tile__price--regular')
        price_tag=sale or regular
        if not price_tag: continue
        price_text=price_tag.get_text(' ',strip=True)
        m=re.fullmatch(r'\s*(?:US\s*)?\$\s*(\d+(?:\.\d{1,2})?)\s*',price_text)
        if not m or currency!='USD' or not title: continue
        candidates=[x.get('srcset','').split()[0] for x in preview.select('source[srcset]') if x.get('srcset','').strip()]
        img=preview.find('img')
        if img: candidates.extend([img.get('data-src',''),img.get('src','')])
        image=next((urljoin(url,x) for x in candidates if x.startswith(('https://','//')) and '/i_m' in x and 'wmk' not in x.lower()),'')
        if not image: continue
        desc=tile.select_one('.tp-design-tile__seo-description')
        yield {'name':title,'image':image,'description':desc.get_text(' ',strip=True).removeprefix('Description:').strip() if desc else ''},{'url':urlunsplit(p._replace(query='',fragment='')),'price':m.group(1),'priceCurrency':currency}

def dashery_next(soup,url):
    """Follow only the storefront's explicit next-page link."""
    a=soup.select_one('nav.pagination a[rel~="next"][href]')
    if not a: return []
    p=urlsplit(urljoin(url,a['href'])); q=dict(parse_qsl(p.query))
    if p.hostname!=urlsplit(url).hostname or not q.get('page','').isdigit(): return []
    return [urlunsplit(p._replace(query=urlencode({k:v for k,v in q.items() if not k.startswith('utm_')}),fragment=''))]
