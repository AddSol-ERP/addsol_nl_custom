# Copyright (c) 2026, Your Company and contributors
# For license information, see license.txt

"""Submitting has to name each offcut's Batch and reserve its Serial No.

`on_submit` is the only thing that runs this code and nothing - not a test,
not a real record - had ever run it: the site had zero submitted Plate Cutting
Records and zero batches on the offcut series when the first submit died in
`make_autoname` with 'str' object has no attribute 'get'. The series is handed
a Batch (or a Serial No) document to name from, never a doctype name string.

`bench --site <site> run-tests --app addsol_nl_custom`
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.addsol_nl_custom.plates import cutting

from .test_cutting_estimate import (
	COST_PER_KG,
	GROUP,
	PLATE_WEIGHT,
	RATIO,
	THICKNESS,
	record_for,
	source_serial,
)
from .test_item import make_group, make_plate_item, make_thickness

# 1000 x 500 and 800 x 400 of a 2500 x 1250 x 10 plate: 65.657 kg at the
# batch's 1.02 ratio, comfortably inside the 245.313 kg the plate weighs, so
# nothing here trips the overage rule on its way to on_submit.
ROWS = [
	{"length_mm": 1000, "width_mm": 500},
	{"length_mm": 800, "width_mm": 400},
]


class TestOffcutStockOnSubmit(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# Per-test undo, the way the rest of the suite rebuilds its world.
		self.addCleanup(frappe.db.rollback)
		# The minimum offcut is the suite's choice, not the site's.
		frappe.db.set_single_value("Plate Settings", "min_offcut_length_mm", 0)
		frappe.db.set_single_value("Plate Settings", "min_offcut_width_mm", 0)
		self.group = make_group(GROUP)
		self.thickness = make_thickness(THICKNESS)
		self.item = make_plate_item(group=GROUP, length=2500, width=1250)
		self.serial = source_serial(self.item, PLATE_WEIGHT)

	def submit_record(self, serial=None):
		"""Insert and submit one record.

		``work_order`` and ``job_card`` are mandatory on the form, but nothing
		in the submit path reads them - the work order check has its own test
		module - so they are skipped instead of built as fixtures, which would
		drag an Operation, a Workstation and a BOM into a test about names.
		"""
		record = record_for(serial or self.serial, ROWS)
		record.insert(ignore_mandatory=True)
		record.submit()
		return record

	def test_a_submit_makes_a_batch_per_offcut(self):
		record = self.submit_record()

		self.assertEqual(record.docstatus, 1)
		self.assertEqual(record.status, "Recorded")

		for row in record.offcuts:
			with self.subTest(length=row.length_mm, width=row.width_mm):
				batch = frappe.get_doc("Batch", row.batch_no)
				# Batch is autonamed field:batch_id, so the name the record
				# carries and the batch that exists have to be the same one.
				self.assertEqual(batch.batch_id, row.batch_no)
				self.assertEqual(batch.item, row.offcut_item)
				self.assertEqual(batch.custom_weight_per_plate_kg, row.weight_kg)
				self.assertEqual(batch.custom_source_batch, record.source_batch)
				self.assertEqual(batch.custom_heat_number, record.heat_number)
				# The grade the weight maths uses is the Item's group, not the
				# batch's own label - the trap that once made weights go stale.
				self.assertEqual(batch.custom_grade, GROUP)
				self.assertEqual(batch.custom_actual_to_theoretical_ratio, RATIO)
				self.assertEqual(batch.custom_cost_per_kg, COST_PER_KG)

	def test_the_serial_is_reserved_but_not_created(self):
		record = self.submit_record()

		for row in record.offcuts:
			with self.subTest(length=row.length_mm, width=row.width_mm):
				self.assertTrue(row.serial_no)
				self.assertTrue(row.serial_no.startswith("PL-"))
				self.assertFalse(frappe.db.exists("Serial No", row.serial_no))

	def test_two_records_take_their_own_names_and_share_the_item(self):
		first = self.submit_record()
		second = self.submit_record(source_serial(self.item, PLATE_WEIGHT))

		self.assertNotEqual(first.offcuts[0].batch_no, second.offcuts[0].batch_no)
		self.assertNotEqual(first.offcuts[0].serial_no, second.offcuts[0].serial_no)

		offcut_item = first.offcuts[0].offcut_item
		self.assertEqual(second.offcuts[0].offcut_item, offcut_item)
		self.assertEqual(cutting.get_or_create_offcut_item(self.item.name, 1000, 500), offcut_item)
		self.assertEqual(frappe.db.count("Item", {"item_code": offcut_item}), 1)

		item = frappe.get_doc("Item", offcut_item)
		self.assertEqual(item.item_group, GROUP)
		self.assertEqual(item.custom_source_item, self.item.name)
		self.assertEqual(item.custom_is_offcut, 1)
		self.assertEqual(item.custom_length_mm, 1000)
		self.assertEqual(item.custom_width_mm, 500)
