import unittest
from readiness import issues,pin_issues
class ReadinessTests(unittest.TestCase):
    def test_missing_stock(self):
        r=dict(title='Shirt',url='https://example.com/p',image='https://example.com/i.jpg',description='',price='22.00',currency='USD',availability='',source='Dashery / dashery listing')
        self.assertEqual(pin_issues(r),[])
        self.assertEqual(issues(r),['Missing description','Unknown availability'])
        r.update(description='Shirt description',availability='instock')
        self.assertEqual(issues(r),[])
        r['image']='https://example.com/derived/production/designs/1.jpg'
        self.assertTrue(pin_issues(r))

    def test_made_to_order(self):
        from readiness import stock_value
        self.assertEqual(stock_value("made_to_order"),"in_stock")
        self.assertEqual(stock_value("out_of_stock"),"out_of_stock")
        self.assertEqual(stock_value(""),"")
