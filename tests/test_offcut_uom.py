"""Local arithmetic regressions; no site or database writes.

Run with the ERP UI sibling installed/on PYTHONPATH:
PYTHONPATH=../../erpnext-ui python3 -m unittest discover -s tests -v
"""

import json
import sys
import types
import unittest

if "frappe" not in sys.modules:
	frappe = types.ModuleType("frappe")
	frappe._ = lambda text: text
	frappe.utils = types.SimpleNamespace(flt=lambda value: float(value or 0))
	frappe.parse_json = json.loads
	sys.modules["frappe"] = frappe

from addsol_nl_custom.addsol_nl_custom.plates.cutting import pricing_totals
from addsol_nl_custom.addsol_nl_custom.plates.uom_pricing import piece_quantity, receipt_snapshot


def snapshot(mode="Formula"):
	return {
		"quantity": 8,
		"cost_per_uom": 25,
		"pricing_uom": "Square Metre",
		"params_by_symbol": {"L": 4000, "W": 2000},
		"rule": {
			"formula_mode": mode,
			"formula_expression": "L * W / 1000000",
			"params": [
				{"symbol": "L", "data_source": "custom_length_mm"},
				{"symbol": "W", "data_source": "custom_width_mm"},
			],
		},
	}


class CuttingPricingTests(unittest.TestCase):
	def test_area_and_length_pricing(self):
		row = {"length_mm": 1000, "width_mm": 500}
		self.assertEqual(piece_quantity(snapshot(), row, {}), 0.5)
		length = snapshot()
		length["quantity"] = 4
		length["rule"]["formula_expression"] = "L / 1000"
		length["rule"]["params"] = length["rule"]["params"][:1]
		self.assertEqual(piece_quantity(length, row, {}), 1)

	def test_actual_source_measurement_calibrates_each_cut(self):
		actual = {**snapshot(), "quantity": 8.4}
		self.assertEqual(piece_quantity(actual, {"length_mm": 1000, "width_mm": 500}, {}), 0.525)

	def test_circle_uses_area_and_rejects_non_area_formula(self):
		import math

		row = {"shape": "Circle", "diameter_mm": 1000}
		self.assertAlmostEqual(piece_quantity(snapshot(), row, {}), math.pi / 4)
		bad = snapshot()
		bad["rule"]["formula_expression"] = "L + W"
		with self.assertRaises(ValueError):
			piece_quantity(bad, row, {})

	def test_direct_entry_requires_a_positive_measure(self):
		for value in (None, "", 0, -1, float("nan")):
			with self.subTest(value=value), self.assertRaises(ValueError):
				piece_quantity(snapshot("Direct Entry"), {"pricing_qty": value}, {})
		self.assertEqual(piece_quantity(snapshot("Direct Entry"), {"pricing_qty": 1.5}, {}), 1.5)

	def test_receipt_uses_stock_count_and_company_currency(self):
		row = {
			"qty": 2,
			"stock_qty": 4,
			"base_net_amount": 400,
			"custom_pricing_snapshot": json.dumps({**snapshot(), "chargeable_qty": 8}),
		}
		result = receipt_snapshot(row)
		self.assertEqual((result["quantity"], result["cost_per_uom"]), (2, 50))

	def test_value_and_measure_are_conserved(self):
		result = pricing_totals(snapshot(), [0.5, 1.5], [12.5, 37.5], 0.2)
		self.assertEqual(result["consumed_pricing_qty"], 5.8)
		self.assertEqual(result["total_offcut_value"] + result["scrap_value"] + result["consumed_value"], 200)

	def test_complete_cut_keeps_currency_rounding_residue(self):
		source = {**snapshot(), "quantity": 3, "cost_per_uom": 10 / 3}
		result = pricing_totals(source, [1, 1, 1], [3.33, 3.33, 3.33], 0)
		self.assertEqual(result["allocated_values"], [3.33, 3.33, 3.34])
		self.assertEqual(result["total_offcut_value"], 10)
		self.assertEqual(result["consumed_value"], 0)

	def test_overage_and_bad_scrap(self):
		self.assertEqual(pricing_totals(snapshot(), [9], [225], 0)["over_by_pricing_qty"], 1)
		for scrap in (-1, float("nan"), float("inf")):
			with self.assertRaises(ValueError):
				pricing_totals(snapshot(), [], [], scrap)

	def test_snapshot_is_not_changed_by_cut_estimation(self):
		frozen = snapshot()
		before = json.dumps(frozen, sort_keys=True)
		piece_quantity(frozen, {"length_mm": 1000, "width_mm": 500}, {})
		self.assertEqual(json.dumps(frozen, sort_keys=True), before)


if __name__ == "__main__":
	unittest.main()
