import json
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest


def widget(items, label):
    return next(item for item in items if item.label == label)


class BuilderUITests(unittest.TestCase):
    def test_nector_mapping_and_blank_fallback(self):
        for value, expected in [("25", "25"), ("", "0"), ("   ", "0"), (None, "0")]:
            with self.subTest(value=value):
                app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app.py")).run()
                order = {"note_attributes": [
                    {"name": "aa", "value": "0.0"},
                    {"name": "GOKWIK_NECTOR_CREDITS_USED", "value": value},
                ]}
                app.text_area(key="simple_order_json").input(json.dumps(order))
                widget(app.button, "Load JSON fields").click().run()
                widget(app.radio, "Create").set_value("Create order customisation").run()
                widget(app.selectbox, "Create-order customisation key").select("SALEORDER.TOTALSTORECREDIT").run()
                source = widget(app.selectbox, "Shopify value to use")
                self.assertTrue(any("note_attributes[1].name" in label for label in source.options))
                source.select("$.note_attributes (json) = JSON object/array").run()
                app.radio(key="simple_array_selection").set_value("Find first matching item").run()
                app.selectbox(key="simple_array_match_field").select("name").run()
                app.selectbox(key="simple_array_match_operator").select("equals").run()
                app.text_input(key="simple_array_match_value").input("GOKWIK_NECTOR_CREDITS_USED").run()
                app.selectbox(key="simple_array_return_field").select("value").run()
                widget(app.selectbox, "Treat selected value as").select("String").run()
                widget(app.selectbox, "Action").select("Save directly").run()
                widget(app.text_input, "Custom default value (if source is missing/null or no condition matches)").input("0")
                widget(app.checkbox, "Use default for blank or whitespace-only values").check().run()
                widget(app.button, "Generate customisation").click().run()
                self.assertFalse(app.exception)
                result = app.session_state["simple_result"]
                self.assertEqual(result["finalValue"], expected)
                self.assertIn("isNotBlank", result["customisation"]["SALEORDER.TOTALSTORECREDIT"])


if __name__ == "__main__":
    unittest.main()
