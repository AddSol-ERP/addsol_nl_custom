# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""The rate per kg is the buyer's to enter.

These cover two things that used to be wrong in opposite directions. The rate
was read out of a per-supplier table and written over the line on every items
grid change, so a typed figure never survived; and with the supplier lookup
gone, there had to be something sensible to offer instead of an empty field.

`bench --site <site> run-tests --app addsol_nl_custom`
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.addsol_nl_custom.plates.purchase import copy_rate_from_order, set_po_rate
from addsol_nl_custom.addsol_nl_custom.plates.rate_history import last_rate

from .test_item import make_thickness
from .test_weight import THREE_D_FORMULA, make_plate_group

GROUP = "Rate Test Plate Group"
THICKNESS = "10 mm"
SUPPLIER = "RATE-TEST-SUPPLIER"
OTHER_SUPPLIER = "RATE-TEST-OTHER"
NEW_SUPPLIER = "RATE-TEST-BRAND-NEW"


def make_item():
	"""A weighed plate Item.

	The name is not ours to choose: item_autoname derives it from the grade and
	the dimensions, so callers have to use the name it comes back with.
	"""
	if frappe.db.exists("Item", f"{GROUP}-10x2500x1250"):
		frappe.delete_doc("Item", f"{GROUP}-10x2500x1250", force=True, ignore_missing=True)

	return frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": "PLACEHOLDER",
			"item_name": "PLACEHOLDER",
			"item_group": GROUP,
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"is_purchase_item": 1,
			"custom_thickness_dropdown": THICKNESS,
			"custom_length_mm": 2500,
			"custom_width_mm": 1250,
		}
	).insert(ignore_permissions=True)


def make_supplier(name):
	if frappe.db.exists("Supplier", name):
		frappe.delete_doc("Supplier", name, force=True, ignore_permissions=True)

	return frappe.get_doc({"doctype": "Supplier", "supplier_name": name}).insert(ignore_permissions=True)


def make_order(item_code, supplier, rate_per_kg, submit=True, on_date=None):
	"""A Purchase Order carrying one weighed line at a given rate per kg."""
	order = frappe.get_doc(
		{
			"doctype": "Purchase Order",
			"supplier": supplier,
			"transaction_date": on_date or frappe.utils.add_days(frappe.utils.nowdate(), -1),
			"items": [
				{
					"item_code": item_code,
					"qty": 10,
					"rate": 10,
					"custom_is_plate": 1,
					"custom_rate_per_kg": rate_per_kg,
				}
			],
		}
	).insert(ignore_permissions=True)

	if submit:
		order.submit()

	return order


def plate_row(item_code, **overrides):
	row = frappe._dict(
		{
			"idx": 1,
			"item_code": item_code,
			"item_group": GROUP,
			"qty": 10,
			"custom_est_weight_kg": 2453.125,
			"custom_is_plate": 1,
			"custom_rate_per_kg": None,
		}
	)
	row.update(overrides)
	return row


def po_doc(row, supplier=SUPPLIER):
	return frappe._dict(
		{"doctype": "Purchase Order", "name": "PO-RATE-TEST", "supplier": supplier, "items": [row]}
	)


class RateTestBase(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.group = make_plate_group(GROUP, 0.785, THREE_D_FORMULA)
		make_thickness(THICKNESS)
		self.item = make_item().name
		self.supplier = make_supplier(SUPPLIER).name


class TestLastRate(RateTestBase):
	def test_no_history_returns_nothing(self):
		self.assertEqual(last_rate(self.item, self.supplier), 0.0)

	def test_nonsense_input_returns_nothing(self):
		self.assertEqual(last_rate(None), 0.0)
		self.assertEqual(last_rate(""), 0.0)
		self.assertEqual(last_rate("No Such Item At All"), 0.0)

	def test_an_agreed_rate_is_offered_back(self):
		make_order(self.item, self.supplier, 62.5)
		self.assertEqual(last_rate(self.item, self.supplier), 62.5)

	def test_this_supplier_wins_over_another(self):
		other = make_supplier(OTHER_SUPPLIER).name
		make_order(self.item, other, 70.0, on_date=frappe.utils.add_days(frappe.utils.nowdate(), -5))
		make_order(self.item, self.supplier, 62.5)

		self.assertEqual(last_rate(self.item, self.supplier), 62.5)
		self.assertEqual(last_rate(self.item, other), 70.0)

	def test_another_supplier_is_still_offered_when_this_one_is_new(self):
		# A new supplier is not left staring at an empty field.
		make_order(self.item, self.supplier, 62.5)

		self.assertEqual(last_rate(self.item, NEW_SUPPLIER), 62.5)

	def test_draft_orders_are_ignored(self):
		make_order(self.item, self.supplier, 99.9, submit=False)
		self.assertEqual(last_rate(self.item, self.supplier), 0.0)

	def test_the_most_recent_order_wins(self):
		make_order(self.item, self.supplier, 62.5, on_date=frappe.utils.add_days(frappe.utils.nowdate(), -10))
		make_order(self.item, self.supplier, 64.0, on_date=frappe.utils.add_days(frappe.utils.nowdate(), -2))

		self.assertEqual(last_rate(self.item, self.supplier), 64.0)

	def test_a_zero_rate_is_not_history(self):
		# An order with no rate per kg must not be offered as a starting point.
		make_order(self.item, self.supplier, 0)
		self.assertEqual(last_rate(self.item, self.supplier), 0.0)


class TestSetPoRate(RateTestBase):
	def test_a_rate_the_buyer_typed_is_never_touched(self):
		make_order(self.item, self.supplier, 62.5)
		row = plate_row(self.item, custom_rate_per_kg=71.25)

		set_po_rate(po_doc(row), row)

		self.assertEqual(row.custom_rate_per_kg, 71.25)

	def test_editing_the_grid_does_not_overwrite_a_typed_rate(self):
		# The old code overwrote on items_changed, which is what made a typed
		# rate impossible to keep.
		make_order(self.item, self.supplier, 62.5)
		row = plate_row(self.item, custom_rate_per_kg=71.25, items_changed=True)

		set_po_rate(po_doc(row), row)

		self.assertEqual(row.custom_rate_per_kg, 71.25)

	def test_an_empty_line_is_offered_the_last_agreed_rate(self):
		make_order(self.item, self.supplier, 62.5)
		row = plate_row(self.item)

		set_po_rate(po_doc(row), row)

		self.assertEqual(row.custom_rate_per_kg, 62.5)

	def test_a_line_with_no_rate_and_no_history_is_refused(self):
		row = plate_row(self.item)

		with self.assertRaises(frappe.ValidationError):
			set_po_rate(po_doc(row), row)

	def test_the_error_says_to_enter_one(self):
		row = plate_row(self.item)
		try:
			set_po_rate(po_doc(row), row)
		except frappe.ValidationError as error:
			self.assertIn("enter a rate per kg", str(error))
		else:
			self.fail("expected a ValidationError")

	def test_the_amount_is_recomputed_from_the_weight(self):
		row = plate_row(self.item, custom_rate_per_kg=62.5, qty=10, custom_est_weight_kg=2453.125)

		set_po_rate(po_doc(row), row)

		# 2453.125 kg x 62.5 = 153320.31, over 10 plates.
		self.assertEqual(row.rate, 15332.031)
		self.assertEqual(row.custom_weight_per_plate_kg, 245.313)


class TestCopyRateFromOrder(RateTestBase):
	def test_the_order_rate_is_taken(self):
		make_order(self.item, self.supplier, 62.5)
		row = plate_row(self.item, custom_rate_per_kg=99.0)

		copy_rate_from_order(po_doc(row), row)

		self.assertEqual(row.custom_rate_per_kg, 62.5)

	def test_a_rate_left_on_the_receipt_is_replaced_not_refused(self):
		# A receipt is priced at the rate the order agreed. There is nothing to
		# reconcile, so a stale figure left on the row is simply overwritten.
		make_order(self.item, self.supplier, 62.5)
		row = plate_row(self.item, custom_rate_per_kg=99.0)

		copy_rate_from_order(po_doc(row), row)

		self.assertEqual(row.custom_rate_per_kg, 62.5)

	def test_an_order_line_with_no_rate_is_still_refused(self):
		make_order(self.item, self.supplier, 0)
		row = plate_row(self.item)

		with self.assertRaises(frappe.ValidationError):
			copy_rate_from_order(po_doc(row), row)

	def test_a_line_with_no_order_is_left_alone(self):
		row = plate_row(self.item, custom_rate_per_kg=62.5)

		copy_rate_from_order(po_doc(row), row)

		self.assertEqual(row.custom_rate_per_kg, 62.5)
