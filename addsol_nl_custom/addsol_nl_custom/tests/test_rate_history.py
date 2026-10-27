# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""The rate per kg is the buyer's to enter.

These cover two things that used to be wrong in opposite directions. The rate
was read out of a per-supplier table and written over the line on every items
grid change, so a typed figure never survived; and with the supplier lookup
gone, there had to be something sensible to offer instead of an empty field.

`bench --site <site> run-tests --app addsol_nl_custom`
"""

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.addsol_nl_custom.plates.purchase import copy_rate_from_order, set_po_rate
from addsol_nl_custom.addsol_nl_custom.plates.rate_history import last_rate

from .test_item import hsn_for_tests, make_thickness
from .test_weight import THREE_D_FORMULA, make_plate_group

GROUP = "Rate Test Plate Group"
THICKNESS = "10 mm"
SUPPLIER = "RATE-TEST-SUPPLIER"
OTHER_SUPPLIER = "RATE-TEST-OTHER"
NEW_SUPPLIER = "RATE-TEST-BRAND-NEW"


@contextmanager
def without_material_request_rule():
	"""Let a test Purchase Order through the sibling app's MR-origin rule.

	addsol_devoltrans_custom only accepts a Purchase Order row that originates
	from an approved Material Request, and that rule is bench-wide. It has its
	own tests; these are about rate history, so the hook stands down while a
	test order is inserted. Without the sibling app installed there is nothing
	to stand down.
	"""
	try:
		from addsol_devoltrans_custom.events import work_order_traceability
	except ImportError:
		yield
		return

	with patch.object(work_order_traceability, "validate_purchase_order"):
		yield


def make_item():
	"""A weighed plate Item.

	The name is not ours to choose: item_autoname derives it from the grade and
	the dimensions, so callers have to use the name it comes back with.
	"""
	if frappe.db.exists("Item", f"{GROUP}-10x1250x2500"):
		frappe.delete_doc("Item", f"{GROUP}-10x1250x2500", force=True, ignore_missing=True)

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
			**hsn_for_tests(),
		}
	).insert(ignore_permissions=True)


def make_supplier(name):
	if frappe.db.exists("Supplier", name):
		frappe.delete_doc("Supplier", name, force=True, ignore_permissions=True)

	return frappe.get_doc({"doctype": "Supplier", "supplier_name": name}).insert(ignore_permissions=True)


def make_order(item_code, supplier, rate_per_kg, submit=True, on_date=None):
	"""A Purchase Order carrying one weighed line at a given rate per kg."""
	transaction_date = on_date or frappe.utils.add_days(frappe.utils.nowdate(), -1)
	order = frappe.get_doc(
		{
			"doctype": "Purchase Order",
			"supplier": supplier,
			"transaction_date": transaction_date,
			"items": [
				{
					"item_code": item_code,
					"qty": 10,
					"rate": 10,
					# The form fills Reqd by Date from the order date; a
					# server-side insert has to set it or ERPNext refuses the
					# row. It may not be before the transaction date either.
					"schedule_date": transaction_date,
					"custom_is_plate": 1,
					"custom_rate_per_kg": rate_per_kg,
				}
			],
		}
	)
	with without_material_request_rule():
		order.insert(ignore_permissions=True)

		if submit:
			order.submit()

	return order


def plate_row(item_code, order=None, **overrides):
	"""A Purchase Order Item row in memory, optionally linked to an order.

	The row carries the real meta because that is what a row inside a document
	has, and the production code reads field definitions off it. ``order``
	makes it look like a receipt line that came off the given Purchase Order,
	which is how ERPNext's own mapper leaves the row.
	"""
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
	row.meta = frappe.get_meta("Purchase Order Item")
	if order:
		row.purchase_order = order.name
		row.purchase_order_item = order.items[0].name
	row.update(overrides)
	return row


def po_doc(row, supplier=SUPPLIER):
	return frappe._dict(
		{"doctype": "Purchase Order", "name": "PO-RATE-TEST", "supplier": supplier, "items": [row]}
	)


class RateTestBase(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# FrappeTestCase rolls the database back once per class, not once per
		# test, so a Purchase Order an earlier test submitted would still be
		# there for last_rate to find. Undo whatever the last test left; the
		# helpers below rebuild the world this test needs.
		self.addCleanup(frappe.db.rollback)
		# This switch is the suite's to set, not the site's. Two tests below
		# save an order with no rate per kg, which the enabled hooks refuse by
		# design; the rate machinery itself is called directly here and does
		# not read the switch. The per-test rollback undoes the write.
		frappe.db.set_single_value("Plate Settings", "enable_weight_based_purchasing", 0)
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

		# 2453.125 kg x 62.5 = 153320.31, over 10 plates. A per-plate weight is
		# a receipt figure - on an order, the piece weight is set by
		# set_po_weights as custom_unit_weight_kg, not by the pricing here.
		self.assertEqual(row.rate, 15332.031)
		self.assertEqual(row.price_list_rate, 15332.031)


class TestCopyRateFromOrder(RateTestBase):
	def test_the_order_rate_is_taken(self):
		order = make_order(self.item, self.supplier, 62.5)
		row = plate_row(self.item, order)

		copy_rate_from_order(po_doc(row), row)

		self.assertEqual(row.custom_rate_per_kg, 62.5)

	def test_a_receipt_rate_override_is_preserved(self):
		order = make_order(self.item, self.supplier, 62.5)
		row = plate_row(self.item, order, custom_rate_per_kg=99.0)

		copy_rate_from_order(po_doc(row), row)

		self.assertEqual(row.custom_rate_per_kg, 99.0)

	def test_an_order_line_with_no_rate_is_still_refused(self):
		order = make_order(self.item, self.supplier, 0)
		row = plate_row(self.item, order)

		with self.assertRaises(frappe.ValidationError):
			copy_rate_from_order(po_doc(row), row)

	def test_a_line_with_no_order_is_left_alone(self):
		row = plate_row(self.item, custom_rate_per_kg=62.5)

		copy_rate_from_order(po_doc(row), row)

		self.assertEqual(row.custom_rate_per_kg, 62.5)
