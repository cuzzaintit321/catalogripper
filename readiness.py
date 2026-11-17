import re
from pins import valid_url, artwork_only

def pin_issues(r):
    errors=[]
    if not (r['title'] or '').strip(): errors.append('Missing title')
    for key,label in [('url','product URL'),('image','image URL')]:
        if not valid_url(r[key]): errors.append(('Invalid ' if r[key] else 'Missing ')+label)
    if valid_url(r['image']) and artwork_only(r): errors.append('Artwork instead of merchandise')
    return errors

def stock_value(value):
    return {'made_to_order':'in_stock','instock':'in_stock','outofstock':'out_of_stock','preorder':'preorder','in_stock':'in_stock','out_of_stock':'out_of_stock'}.get((value or '').lower(),'')

def issues(r):
    errors=pin_issues(r)
    if not (r['description'] or '').strip(): errors.append('Missing description')
    if not r['price']: errors.append('Missing price')
    elif not re.fullmatch(r'\d+(?:\.\d{1,2})?',r['price']): errors.append('Invalid price')
    if not r['currency']: errors.append('Missing currency')
    elif not re.fullmatch('[A-Z]{3}',r['currency']): errors.append('Invalid currency')
    if not stock_value(r['availability']): errors.append('Unknown availability')
    if r['source']=='Dashery / historical import': errors.append('Historical metadata requires verification')
    return errors
