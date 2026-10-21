import unittest

from expression_generator import (
    ArrayFilterSegment, _get_at_path, direct_expression_for_path,
    json_field_options, json_condition_options,
)


class ArrayMappingTests(unittest.TestCase):
    def setUp(self):
        self.order = {"note_attributes": [
            {"name": "aa", "value": "0.0"},
            {"name": "GOKWIK_NECTOR_CREDITS_USED", "value": "25"},
            {"name": "other", "value": "5"},
        ]}
        self.path = ["note_attributes", ArrayFilterSegment(
            "name", "GOKWIK_NECTOR_CREDITS_USED", "equals"), "value"]

    def test_every_array_entry_is_selectable(self):
        for options in (json_field_options(self.order), json_condition_options(self.order)):
            values = {tuple(item["path"]): item["value"] for item in options}
            self.assertEqual(values[("note_attributes", 1, "value")], "25")
            self.assertEqual(values[("note_attributes", 2, "name")], "other")

    def test_nested_and_scalar_arrays(self):
        options = json_field_options({"items": [{"tags": ["a", "b"]}, {"tags": ["c"]}]})
        self.assertEqual([item["value"] for item in options], ["a", "b", "c"])
        self.assertEqual(_get_at_path({"a": [1, 2]}, ["a", 1]), 2)

    def test_filter_uses_matching_item_and_survives_reordering(self):
        self.assertEqual(_get_at_path(self.order, self.path), "25")
        self.order["note_attributes"].reverse()
        self.assertEqual(_get_at_path(self.order, self.path), "25")

    def test_missing_match_and_missing_value(self):
        for order in ({}, {"note_attributes": []}, {"note_attributes": None},
                      {"note_attributes": [{"name": None}]},
                      {"note_attributes": [{"name": "GOKWIK_NECTOR_CREDITS_USED"}]}):
            self.assertIsNone(_get_at_path(order, self.path))

    def test_first_match_wins(self):
        self.order["note_attributes"].append(
            {"name": "GOKWIK_NECTOR_CREDITS_USED", "value": "90"})
        self.assertEqual(_get_at_path(self.order, self.path), "25")

    def test_blank_fallback_is_opt_in_and_typed(self):
        for kind, fallback in (("String", "'0'"), ("Decimal", "0.0")):
            expression = direct_expression_for_path(self.path, kind, "0", True)
            self.assertIn("StringUtils).isNotBlank(", expression)
            self.assertIn(".getAsJsonArray().^[", expression)
            self.assertIn(".isJsonPrimitive()", expression)
            self.assertIn(".isJsonNull()", expression)
            self.assertTrue(expression.endswith(f" : {fallback}" + "}"))
        self.assertNotIn("isNotBlank", direct_expression_for_path(self.path))


if __name__ == "__main__":
    unittest.main()
