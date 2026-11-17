import unittest,csv,io
from pins import build,FIELDS
class PinTests(unittest.TestCase):
    def test_batches(self):
        rows=[dict(title='Shirt '+str(i),description='',image='https://example.com/image.jpg',url='https://example.com/p/'+str(i),source='Shopify') for i in range(201)]
        files=build(rows+[rows[0]],'T-Shirts','shirts, gifts')
        self.assertEqual(len(files),2)
        parsed=[list(csv.reader(io.StringIO(f))) for f in files]
        self.assertEqual([len(p) for p in parsed],[201,2]); self.assertEqual(parsed[0][0],FIELDS)
        self.assertEqual(parsed[0][1][2],'T-Shirts'); self.assertEqual(parsed[0][1][3],''); self.assertEqual(parsed[0][1][7],'shirts, gifts')
    def test_invalid(self):
        self.assertEqual(build([dict(title='Art',description='',image='https://example.com/derived/production/designs/1.jpg',url='https://example.com/p',source='Dashery / open-graph')],'Board'),[])
        with self.assertRaises(ValueError): build([], 'Board',size=201)
        with self.assertRaises(ValueError): build([], 'Board',publish='2026-02-30')

    def test_dashery_mockup(self):
        r=dict(title='Shirt',description='',image='https://images.teepublic.com/derived/production/designs/123_1/456/i_m:bi_production_blanks_example,s_313,q_90.webp',url='https://example.dashery.com/products/123-shirt',source='Dashery / dashery listing')
        self.assertEqual(len(build([r],'T-Shirts')),1)
        from readiness import pin_issues
        self.assertEqual(pin_issues(r),[])
        r['image']=r['image'].replace('i_m:bi_production_blanks_example','i_p:c_191919,wmk')
        self.assertEqual(build([r],'T-Shirts'),[])
        self.assertTrue(pin_issues(r))
    def test_duplicate_titles_and_retry(self):
        from pins import retry_report
        rows=[dict(title='X'*100,description='',image='https://example.com/i.jpg',url=f'https://example.com/p/{i}',source='Shopify') for i in range(3)]
        out=[r for f in build(rows,'Board',size=1) for r in csv.DictReader(io.StringIO(f))]
        self.assertEqual(len({r['Title'].casefold() for r in out}),3)
        self.assertTrue(all(len(r['Title'])<=100 for r in out))
        b=io.StringIO(); w=csv.DictWriter(b,fieldnames=FIELDS+['error']); w.writeheader()
        for i,r in enumerate(out):
            r['Title']='Same'; r['error']='duplicate title' if i else ''; w.writerow(r)
        retry=list(csv.DictReader(io.StringIO(retry_report(b.getvalue())[0])))
        self.assertEqual([r['Title'] for r in retry],['Same (2)','Same (3)'])
