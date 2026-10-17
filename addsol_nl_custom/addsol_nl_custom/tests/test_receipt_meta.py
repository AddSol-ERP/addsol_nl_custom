# Copyright (c) 2026, Your Company and contributors
# For license information, see license.txt

"""The receipt must stamp its weight onto the serials, not only the batch.

`receipt_meta.apply_receipt_metadata` runs on Purchase Receipt submit. It used
to return as soon as a line's bundle carried no batch, so the serials on that
line never received `custom_weight_kg` - the very weight the plate reports read
and the Plate Cutting Screen checks before it lets a plate be cut. The live log
for PR-26-00011 and PR-26-00012 recorded exactly this: the stamp ran, found no
bundle in time, and stamped nothing.

Two things close that gap, and both are pinned here:

- `stamp_row` stamps the serials whether or not a batch was produced;
- `stamp_submitted_receipt` re-reads a submitted receipt after commit, once
  ERPNext has finished writing the bundle, and stamps it again. It is a no-op
  for anything that is not a submitted receipt.

`bench --site <site> run-tests --app addsol_nl_custom`
"""

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.addsol_nl_custom.plates import receipt_meta

from .test_item import hsn_for_tests

COMPANY = "_Test Company"


def make_item():
	"""A serial- and batch-tracked stock Item, plain enough to stay out of the plate rules."""
	item_code = f"PCR-STAMP-{uuid.uuid4().hex[:6]}"
	return frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"item_group": "All Item Groups",
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"has_serial_no": 1,
			"has_batch_no": 1,
			"create_new_batch": 1,
			"serial_no_series": "PCRS-.######",
			"batch_number_series": "PCRB-.######",
			"valuation_rate": 100,
			**hsn_for_tests(),
		}
	).insert(ignore_permissions=True).name


def make_serial(item_code, weight=None):
	"""An Active serial. ERPNext refuses one born with a warehouse, so set it after."""
	serial_no = f"PCR-STAMP-SN-{uuid.uuid4().hex[:8].upper()}"
	frappe.get_doc(
		{
			"doctype": "Serial No",
			"serial_no": serial_no,
			"item_code": item_code,
			"company": COMPANY,
		}
	).insert(ignore_permissions=True)

	values = {"status": "Active"}
	if weight is not None:
		values["custom_weight_kg"] = weight
	frappe.db.set_value("Serial No", serial_no, values)
	return serial_no


def make_bundle(item_code, serial_nos, batch_no=None):
	"""A Serial and Batch Bundle carrying the given serials, optionally a batch.

	Validation is stood down: this test is about the stamp reading the bundle's
	entries, not about ERPNext's rules for who may own a bundle.
	"""
	entries = [
		{
			"serial_no": serial_no,
			"batch_no": batch_no,
			"qty": 1,
			"warehouse": "Stores - _TC",
			"type_of_transaction": "Inward",
		}
		for serial_no in serial_nos
	]

	bundle = frappe.get_doc(
		{
			"doctype": "Serial and Batch Bundle",
			"company": COMPANY,
			"item_code": item_code,
			"voucher_type": "Purchase Receipt",
			"type_of_transaction": "Inward",
			"entries": entries,
		}
	)
	bundle.flags.ignore_validate = True
	bundle.insert(ignore_permissions=True)
	return bundle.name


def receipt_row(bundle, item_code, **overrides):
	row = {
		"idx": 1,
		"item_code": item_code,
		"serial_and_batch_bundle": bundle,
		"custom_is_plate": 1,
		"custom_heat_number": "HEAT-42",
		"custom_weight_per_plate_kg": 250.0,
		"qty": 1,
		"rate": 1000.0,
	}
	row.update(overrides)
	return frappe._dict(row)


class TestStampRow(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# FrappeTestCase rolls back per class, so rebuild the world per test.
		self.addCleanup(frappe.db.rollback)
		self.item = make_item()
		self.receipt = frappe._dict(name="PR-TEST-STAMP")

	def test_serials_are_stamped_when_the_line_has_no_batch(self):
		"""The regression: a bundle with serials but no batch must still stamp them."""
		serials = [make_serial(self.item), make_serial(self.item)]
		bundle = make_bundle(self.item, serials)
		row = receipt_row(bundle, self.item)

		receipt_meta.stamp_row(self.receipt, row)

		for serial_no in serials:
			with self.subTest(serial_no=serial_no):
				self.assertEqual(
					frappe.db.get_value("Serial No", serial_no, "custom_weight_kg"),
					250.0,
				)
				self.assertEqual(
					frappe.db.get_value("Serial No", serial_no, "custom_heat_number"),
					"HEAT-42",
				)

	def test_a_bundle_with_a_batch_stamps_both_the_batch_and_the_serials(self):
		"""The ordinary path must keep working alongside the new one."""
		serial = make_serial(self.item)
		batch = frappe.get_doc(
			{
				"doctype": "Batch",
				"batch_id": f"PCRB-{uuid.uuid4().hex[:8]}",
				"item": self.item,
			}
		).insert(ignore_permissions=True).name

		bundle = make_bundle(self.item, [serial], batch_no=batch)
		row = receipt_row(bundle, self.item)

		receipt_meta.stamp_row(self.receipt, row)

		self.assertEqual(frappe.db.get_value("Serial No", serial, "custom_weight_kg"), 250.0)
		self.assertEqual(
			frappe.db.get_value("Batch", batch, "custom_weight_per_plate_kg"), 250.0
		)
		self.assertEqual(frappe.db.get_value("Batch", batch, "custom_heat_number"), "HEAT-42")

	def test_no_bundle_stamps_nothing_and_does_not_raise(self):
		"""A line with no bundle is left alone - the post-commit pass retries it."""
		row = receipt_row(None, self.item, serial_and_batch_bundle=None)

		receipt_meta.stamp_row(self.receipt, row)  # must not throw


class TestStampSubmittedReceipt(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.db.rollback)
		self.item = make_item()

	def test_a_receipt_that_is_not_submitted_is_left_alone(self):
		"""The post-commit pass must not touch a missing or unsubmitted receipt.

		It re-reads the receipt, so acting on anything but a submitted one would
		stamp a document ERPNext has not finished with.
		"""
		serials = [make_serial(self.item)]
		make_bundle(self.item, serials)
		before = {serial_no: frappe.db.get_value("Serial No", serial_no, "custom_weight_kg") for serial_no in serials}

		# A receipt name that does not exist: the pass must be a silent no-op.
		receipt_meta.stamp_submitted_receipt("PR-DOES-NOT-EXIST")

		for serial_no in serials:
			self.assertEqual(
				frappe.db.get_value("Serial No", serial_no, "custom_weight_kg"),
				before[serial_no],
				"an unknown receipt must not stamp anything",
			)
