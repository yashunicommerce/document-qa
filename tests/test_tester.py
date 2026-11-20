import json
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from tester_logic import detect_type, item_expression, lint, plan_requests, verdict

APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")


class LogicTests(unittest.TestCase):
    def test_detect_type(self):
        self.assertFalse(detect_type([{"A": "#{x}"}])[0])
        self.assertTrue(detect_type({"SALEORDER.PRIORITY": "#{x}"})[0])
        console, entries, notes = detect_type({"Tags": "#{x}"})
        self.assertFalse(console)
        self.assertTrue(notes)
        with self.assertRaises(ValueError):
            detect_type({"SALEORDER.PRIORITY": "#{x}", "Tags": "#{y}"})
        with self.assertRaises(ValueError):
            detect_type("text")

    def test_item_rewrite(self):
        self.assertEqual(
            item_expression("#{#saleOrderItemJson.get('a') != null and #saleOrderItem?.get('b')}", 2),
            "#{#saleOrderJson.get('line_items').get(2).get('a') != null and "
            "#saleOrderJson.get('line_items').get(2)?.get('b')}",
        )

    def test_plan(self):
        order = {"line_items": [{}, {}]}
        _, entries, _ = detect_type({
            "SALEORDER.PRIORITY": "#{#saleOrderJson.get('x')}",
            "SALEORDER.SALEORDERITEM.ITEMTAG": "#{#saleOrderItemJson.get('y')}",
            "SALEORDER.BILLINGADDRESS.NAME": "Store",
            "SALEORDER.FULFILLMENTTAT": "#{T(com.unifier.core.utils.DateUtils).getCurrentTime()}",
        })
        batches, local = plan_requests(entries, order, True)
        self.assertEqual([b["line"] for b in batches], [None, 0, 1])
        self.assertEqual({r["status"] for r in local}, {"CONSTANT", "NOT TESTABLE"})

    def test_plan_custom_field_constant_is_never_saved(self):
        entries = [{"field": "Source", "expression": "Shopify"},
                   {"field": "Gift", "expression": "#{#saleOrderItem.get('sku')}"}]
        batches, local = plan_requests(entries, {"line_items": [{}]}, False)
        self.assertEqual([b["line"] for b in batches], [0])
        self.assertEqual(local[0]["status"], "ERROR")
        self.assertIn("Never saved", local[0]["error"])

    def test_lat_long_supported(self):
        self.assertFalse(lint([{"field": "SALEORDER.SHIPPINGADDRESS.LATITUDE", "expression": "#{#saleOrderJson}"}], True))

    def test_lint(self):
        warnings = lint([{"field": "Tags ", "expression": "#{(saleOrderJson.get('tags'))}"}], False)
        self.assertTrue(any("spaces" in w for w in warnings))
        self.assertTrue(any("without #" in w for w in warnings))
        self.assertTrue(lint([{"field": "SALEORDER.NDDSDD", "expression": "#{#saleOrderJson}"}], True))

    def test_verdict(self):
        self.assertEqual(verdict([{"field": "a", "status": "SUCCESS"}])[0], "success")
        self.assertEqual(verdict([{"field": "a", "status": "ERROR"}])[0], "error")


def fake_post(url, json=None, timeout=None):
    results = []
    expr = json["customisationExpression"]
    items = expr.items() if isinstance(expr, dict) else [next(iter(e.items())) for e in expr]
    for field, value in items:
        failing = "boom" in value
        results.append({"fieldName": field, "expression": value, "status": "ERROR" if failing else "SUCCESS",
                        "value": None if failing else "ok", "errorType": "EVAL" if failing else None,
                        "errorMessage": "bad" if failing else None})
    response = mock.Mock(status_code=200)
    response.json.return_value = {"status": "success", "data": {"expressionResults": results}}
    return response


class UITests(unittest.TestCase):
    def run_app(self, order, customisation):
        with mock.patch("requests.post", side_effect=fake_post):
            app = AppTest.from_file(APP).run()
            app.text_area(key="order_json").input(json.dumps(order))
            app.text_area(key="customisation_json").input(json.dumps(customisation))
            app.button(key="run_test").click().run()
        return app

    def test_single_page(self):
        app = AppTest.from_file(APP).run()
        self.assertEqual(len(app.tabs), 0)
        self.assertFalse(app.exception)

    def test_success(self):
        app = self.run_app({"id": 1, "tags": "A"}, [{"Tags": "#{#saleOrderJson.get('tags')}"}])
        self.assertFalse(app.exception)
        self.assertTrue(app.success)

    def test_failure(self):
        app = self.run_app({"id": 1}, {"SALEORDER.PRIORITY": "#{#saleOrderJson.boom}"})
        self.assertTrue(app.error)

    def test_bad_json(self):
        with mock.patch("requests.post", side_effect=fake_post):
            app = AppTest.from_file(APP).run()
            app.text_area(key="order_json").input("{bad")
            app.text_area(key="customisation_json").input("[]")
            app.button(key="run_test").click().run()
        self.assertIn("not valid JSON", app.error[0].value)


if __name__ == "__main__":
    unittest.main()
