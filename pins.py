"""Build organic Pinterest image Pin CSVs without retail feed requirements."""
import csv, io, re
from urllib.parse import urlsplit
from datetime import date, datetime
FIELDS = ['Title','Media URL','Pinterest board','Thumbnail','Description','Link','Publish date','Keywords']

def valid_url(value):
    try:
        p=urlsplit(value or '')
        return p.scheme in ('http','https') and bool(p.hostname) and not p.username and not p.password and not any(c.isspace() for c in value)
    except ValueError:
        return False

def clean(value, limit):
    value=' '.join((value or '').split())[:limit]
    return "'"+value[:limit-1] if value.startswith(('=','+','-','@')) else value

def artwork_only(r):
    # TeePublic stores both artwork and merchandise renders under designs/.
    if not valid_url(r['image']): return False
    path=urlsplit(r['image'] or '').path.lower()
    if r['source']=='Dashery / open-graph': return True
    if '/derived/production/designs/' not in path: return False
    return not (path.rsplit('/',1)[-1].startswith('i_m') and 'wmk' not in path)

def eligible(rows):
    seen=set()
    for r in rows:
        if not (r['title'] or '').strip() or not valid_url(r['image']) or not valid_url(r['url']): continue
        if artwork_only(r): continue
        key=r['url']
        if key in seen: continue
        seen.add(key)
        yield r

def unique_title(title, used):
    base=clean(title,100)
    candidate=base; n=2
    while candidate.casefold() in used:
        suffix=f' ({n})'
        candidate=base[:100-len(suffix)].rstrip()+suffix
        n+=1
    used.add(candidate.casefold())
    return candidate

def retry_report(raw):
    reader=csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or not set(FIELDS+['error']).issubset(reader.fieldnames):
        raise ValueError('Upload a Pinterest CSV error report with the original Pin columns and error column.')
    rows=list(reader)
    used={clean(r['Title'],100).casefold() for r in rows if not (r['error'] or '').strip()}
    failed=[]; seen=set()
    for r in rows:
        if not (r['error'] or '').strip(): continue
        if not valid_url(r['Link']) or not valid_url(r['Media URL']) or not (r['Title'] or '').strip():
            raise ValueError('A failed row has invalid required fields; correct the report first.')
        if r['Link'] in seen: continue
        seen.add(r['Link'])
        r['Title']=unique_title(r['Title'],used)
        r['Publish date']=''
        failed.append(r)
    files=[]
    for i in range(0,len(failed),200):
        b=io.StringIO(newline=''); w=csv.DictWriter(b,fieldnames=FIELDS,extrasaction='ignore'); w.writeheader(); w.writerows(failed[i:i+200]); files.append(b.getvalue())
    return files

def build(rows, board, keywords='', publish='', size=200):
    board=clean(board,200)
    if not board: raise ValueError('Enter a Pinterest board name.')
    if publish:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2})?',publish): raise ValueError('Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS (UTC).')
        try: datetime.fromisoformat(publish)
        except ValueError: raise ValueError('Invalid publish date.')
    if not 1<=size<=200: raise ValueError('Batch size must be 1–200.')
    rows=list(eligible(rows)); files=[]; used=set()
    for i in range(0,len(rows),size):
        b=io.StringIO(newline=''); w=csv.writer(b); w.writerow(FIELDS)
        for r in rows[i:i+size]:
            w.writerow([unique_title(r['title'],used),r['image'],board,'',clean(r['description'] or r['title'],500),r['url'],publish,clean(keywords,500)])
        files.append(b.getvalue())
    return files
