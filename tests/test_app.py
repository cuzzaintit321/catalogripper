import os, tempfile, unittest
os.environ['DB']=os.path.join(tempfile.mkdtemp(),'test.db')
from app import app, extract
class CatalogTests(unittest.TestCase):
    def test_product(self):
        html='''<script type="application/ld+json">{"@type":"Product","name":"Example shirt","sku":"ABC","description":"Cotton","image":"/shirt.png","offers":{"price":"22.00","priceCurrency":"USD","availability":"https://schema.org/InStock"}}</script>'''
        rows,_=extract(html,'https://example.com/products/shirt')
        self.assertEqual(rows[0]['price'],'22.00')
        self.assertEqual(rows[0]['image'],'https://example.com/shirt.png')
        changed,_=extract(html.replace('22.00','24.00'),'https://example.com/products/shirt')
        self.assertEqual(rows[0]['id'],changed[0]['id'])
    def test_routes(self):
        with app.test_client() as c:
            for path in ('/','/export.csv','/export.xml'): self.assertEqual(c.get(path).status_code,200)
            self.assertEqual(c.post('/scan',data={'url':'https://example.com'}).status_code,400)
    def test_microdata(self):
        html='<div itemscope itemtype="https://schema.org/Product"><span itemprop="name">Sample</span><meta itemprop="price" content="12.00"><meta itemprop="priceCurrency" content="USD"></div>'
        rows,_=extract(html,'https://example.com/item'); self.assertEqual(rows[0]['price'],'12.00')
    def test_shopify(self):
        html='<script type="application/json">{"currency":"USD","product":{"handle":"shirt","title":"Shirt","variants":[{"id":123,"price":2200,"available":true,"title":"Blue"}]}}</script><div class="shopify-section"></div>'
        rows,_=extract(html,'https://example.com/products/shirt'); self.assertEqual(rows[0]['price'],'22'); self.assertIn('variant=123',rows[0]['url'])
    def test_new_routes(self):
        with app.test_client() as c:
            for path in ('/?q=shirt','/validation.csv','/meta.csv','/pinterest.csv'): self.assertEqual(c.get(path).status_code,200)
