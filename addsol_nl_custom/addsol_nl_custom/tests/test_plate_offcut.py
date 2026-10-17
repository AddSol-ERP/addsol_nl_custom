# Copyright (c) 2026, Your Company and contributors
# For license information, see license.txt

"""Submitting a Plate Offcut must repack the plate into its pieces.

The whole flow lives in on_submit - Items, Batches, reserved Serial Nos and
the Repack Stock Entry - and nothing outside this module had ever run it.
These tests pin the Repack's shape (plate out, pieces back into the same
warehouse, every destination row carrying its own rate), the traceability
chain back to the parent plate, the auto-balanced scrap, and the cancel path
that puts the plate back.

`bench --site <site> run-tests --app addsol_nl_custom`
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.addsol_nl_custom.plates import cutting
from addsol_nl_custom.addsol_nl_custom.plates.utils import round_half_up

from .test_cutting_estimate import (
	COST_PER_KG,
	GROUP,
	PLATE_WEIGHT,
	RATIO,
	THICKNESS,
	make_warehouse,
	offcut_for,
	source_serial,
)
from .test_item import hsn_for_tests, make_group, make_plate_item, make_thickness

SCRAP_ITEM = "Plate Offcut Test Scrap"

# 1000 x 500 and 800 x 400 of a 2500 x 1250 x 10 plate: 65.657 kg at the
# batch's 1.02 ratio, comfortably inside the 245.313 kg the plate weighs, so
# nothing here trips the overage rule on its way to on_submit.
ROWS = [
	{"length_mm": 1000, "width_mm": 500},
	{"length_mm": 800, "width_mm": 400},
]

# 245.313 - 65.657: what the offcuts do not weigh has to leave as scrap.
AUTO_SCRAP_KG = 179.656


def ensure_scrap_item():
	"""The scrap Item and the Plate Settings pointer, whatever the site has."""
	if not frappe.db.exists("Item Group", "Scrap"):
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": "Scrap",
				"parent_item_group": "All Item Groups",
				"is_group": 0,
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Item", SCRAP_ITEM):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": SCRAP_ITEM,
				"item_name": SCRAP_ITEM,
				"item_group": "Scrap",
				"stock_uom": "Kg",
				"is_stock_item": 1,
				**hsn_for_tests(),
			}
		).insert(ignore_permissions=True)

	frappe.db.set_single_value("Plate Settings", "scrap_item", SCRAP_ITEM)


class TestPlateOffcut(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# Per-test undo, the way the rest of the suite rebuilds its world.
		self.addCleanup(frappe.db.rollback)
		frappe.db.set_single_value("Plate Settings", "min_offcut_length_mm", 0)
		frappe.db.set_single_value("Plate Settings", "min_offcut_width_mm", 0)
		ensure_scrap_item()
		self.group = make_group(GROUP)
		self.thickness = make_thickness(THICKNESS)
		self.item = make_plate_item(group=GROUP, length=2500, width=1250)
		self.warehouse = make_warehouse()
		self.serial = source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse)

	def submit_offcut(self, serial=None, rows=ROWS):
		document = offcut_for(serial or self.serial, rows)
		document.insert()
		document.submit()
		return document

	# ------------------------------------------------------------- on submit

	def test_a_submit_repacks_the_plate_back_into_the_same_warehouse(self):
		document = self.submit_offcut()

		self.assertTrue(document.name.startswith("OFC-"))
		self.assertEqual(document.docstatus, 1)
		self.assertEqual(frappe.db.get_value("Stock Entry", document.stock_entry, "docstatus"), 1)

		stock_entry = frappe.get_doc("Stock Entry", document.stock_entry)
		self.assertEqual(stock_entry.purpose, "Repack")
		self.assertEqual(stock_entry.company, frappe.db.get_value("Warehouse", self.warehouse, "company"))

		source_rows = [row for row in stock_entry.items if row.s_warehouse]
		destination_rows = [row for row in stock_entry.items if row.t_warehouse]

		self.assertEqual(len(source_rows), 1)
		self.assertEqual(source_rows[0].item_code, self.item.name)
		self.assertEqual(source_rows[0].s_warehouse, self.warehouse)
		self.assertEqual(source_rows[0].qty, 1)
		self.assertEqual(source_rows[0].serial_no, self.serial)
		self.assertEqual(source_rows[0].batch_no, document.source_batch)

		# Two offcuts plus the scrap row, all back into the plate's warehouse.
		self.assertEqual(len(destination_rows), len(ROWS) + 1)
		for row in destination_rows:
			with self.subTest(item=row.item_code):
				self.assertEqual(row.t_warehouse, self.warehouse)
				self.assertFalse(row.s_warehouse)

	def test_the_plate_is_consumed_and_the_children_become_active_serials(self):
		document = self.submit_offcut()

		parent = frappe.db.get_value(
			"Serial No", self.serial, ["status", "warehouse"], as_dict=True
		)
		self.assertEqual(parent.status, "Consumed")
		self.assertFalse(parent.warehouse)

		for row in document.offcuts:
			with self.subTest(length=row.length_mm, width=row.width_mm):
				serial = frappe.db.get_value(
					"Serial No", row.serial_no, ["item_code", "status", "warehouse"], as_dict=True
				)
				self.assertEqual(serial.item_code, row.offcut_item)
				self.assertEqual(serial.status, "Active")
				self.assertEqual(serial.warehouse, self.warehouse)

				# The traceability chain: child serial -> parent serial, and
				# child weight is the weight this document booked.
				self.assertEqual(
					frappe.db.get_value("Serial No", row.serial_no, "custom_source_serial_no"),
					self.serial,
				)
				self.assertEqual(
					frappe.db.get_value("Serial No", row.serial_no, "custom_weight_kg"), row.weight_kg
				)

	def test_every_destination_row_carries_its_own_rate(self):
		document = self.submit_offcut()
		stock_entry = frappe.get_doc("Stock Entry", document.stock_entry)
		destination_rows = [row for row in stock_entry.items if row.t_warehouse]

		# ERPNext refuses a Repack with several finished items unless every
		# rate is manual, and skips manual rows entirely when it computes
		# amounts - so basic_amount has to be carried in by hand too.
		for row, offcut in zip(destination_rows[: len(document.offcuts)], document.offcuts, strict=True):
			with self.subTest(item=row.item_code):
				self.assertEqual(row.set_basic_rate_manually, 1)
				self.assertEqual(row.basic_rate, offcut.value)
				self.assertEqual(row.basic_amount, offcut.value)

	def test_the_scrap_row_balances_the_plate(self):
		document = self.submit_offcut()

		self.assertEqual(document.scrap_weight_kg, AUTO_SCRAP_KG)
		self.assertEqual(document.scrap_value, round_half_up(AUTO_SCRAP_KG * COST_PER_KG, 2))
		self.assertEqual(
			frappe.utils.flt(document.total_offcut_weight_kg) + frappe.utils.flt(document.scrap_weight_kg),
			document.source_weight_kg,
		)

		scrap_rows = [
			row
			for row in frappe.get_doc("Stock Entry", document.stock_entry).items
			if row.item_code == SCRAP_ITEM
		]
		self.assertEqual(len(scrap_rows), 1)
		self.assertEqual(scrap_rows[0].qty, AUTO_SCRAP_KG)
		self.assertEqual(scrap_rows[0].basic_rate, COST_PER_KG)
		self.assertEqual(scrap_rows[0].t_warehouse, self.warehouse)

	def test_when_the_offcuts_take_the_whole_plate_there_is_no_scrap_row(self):
		# Same-size cut at ratio 1.0: the one offcut weighs exactly what the
		# plate does, so there is nothing left over to book as scrap.
		batch = frappe.db.get_value("Serial No", self.serial, "batch_no")
		frappe.db.set_value("Batch", batch, "custom_actual_to_theoretical_ratio", 1.0)

		document = offcut_for(self.serial, [{"length_mm": 2500, "width_mm": 1250}])
		document.insert()
		document.submit()

		self.assertEqual(document.scrap_weight_kg, 0.0)
		items = frappe.get_doc("Stock Entry", document.stock_entry).items
		self.assertEqual(len(items), 2)  # the plate out, the one offcut in
		self.assertTrue(all(row.t_warehouse or row.s_warehouse for row in items))
		self.assertFalse(any(row.item_code == SCRAP_ITEM for row in items))

	def test_a_submit_makes_a_batch_per_offcut_with_the_parents_history(self):
		document = self.submit_offcut()

		for row in document.offcuts:
			with self.subTest(length=row.length_mm, width=row.width_mm):
				batch = frappe.get_doc("Batch", row.batch_no)
				# Batch is autonamed field:batch_id, so the name the document
				# carries and the batch that exists have to be the same one.
				self.assertEqual(batch.batch_id, row.batch_no)
				self.assertEqual(batch.item, row.offcut_item)
				self.assertEqual(batch.custom_weight_per_plate_kg, row.weight_kg)
				self.assertEqual(batch.custom_source_batch, document.source_batch)
				self.assertEqual(batch.custom_heat_number, document.heat_number)
				# The grade the weight maths uses is the Item's group, not the
				# batch's own label - the trap that once made weights go stale.
				self.assertEqual(batch.custom_grade, GROUP)
				self.assertEqual(batch.custom_actual_to_theoretical_ratio, RATIO)
				self.assertEqual(batch.custom_cost_per_kg, COST_PER_KG)

	def test_the_reserved_serials_exist_after_submit(self):
		document = self.submit_offcut()

		for row in document.offcuts:
			with self.subTest(length=row.length_mm, width=row.width_mm):
				self.assertTrue(row.serial_no)
				self.assertTrue(row.serial_no.startswith("PL-"))
				self.assertTrue(frappe.db.exists("Serial No", row.serial_no))

	def test_two_offcuts_take_their_own_names_and_share_the_item(self):
		first = self.submit_offcut()
		second = self.submit_offcut(serial=source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse))

		self.assertNotEqual(first.offcuts[0].batch_no, second.offcuts[0].batch_no)
		self.assertNotEqual(first.offcuts[0].serial_no, second.offcuts[0].serial_no)

		offcut_item = first.offcuts[0].offcut_item
		self.assertEqual(offcut_item, f"{GROUP}-10x1000x500")
		self.assertEqual(second.offcuts[0].offcut_item, offcut_item)
		self.assertEqual(cutting.get_or_create_offcut_item(self.item.name, 1000, 500), offcut_item)
		self.assertEqual(frappe.db.count("Item", {"item_code": offcut_item}), 1)

		item = frappe.get_doc("Item", offcut_item)
		self.assertEqual(item.item_group, GROUP)
		self.assertEqual(item.custom_source_item, self.item.name)
		self.assertEqual(item.custom_is_offcut, 1)
		self.assertEqual(item.custom_length_mm, 1000)
		self.assertEqual(item.custom_width_mm, 500)

	# ---------------------------------------------------------------- cancel

	def test_cancel_reverses_the_repack_and_restores_the_plate(self):
		document = self.submit_offcut()
		serials = [row.serial_no for row in document.offcuts]
		batches = [row.batch_no for row in document.offcuts]

		document.cancel()

		self.assertEqual(document.docstatus, 2)
		self.assertEqual(frappe.db.get_value("Stock Entry", document.stock_entry, "docstatus"), 2)

		parent = frappe.db.get_value("Serial No", self.serial, ["status", "warehouse"], as_dict=True)
		self.assertEqual(parent.status, "Active")
		self.assertEqual(parent.warehouse, self.warehouse)

		for serial in serials:
			self.assertEqual(frappe.db.get_value("Serial No", serial, "status"), "Inactive")

		for batch in batches:
			self.assertFalse(frappe.db.exists("Batch", batch))

		document.reload()
		for row in document.offcuts:
			self.assertFalse(row.serial_no)
			self.assertFalse(row.batch_no)

	def test_a_cancelled_offcut_can_be_amended_and_submitted_again(self):
		document = self.submit_offcut()
		old_serials = [row.serial_no for row in document.offcuts]
		document.cancel()

		# The desk's Amend button: a fresh document off the cancelled one. The
		# cancelled attempt's serial names were cleared on cancel, so this
		# submit reserves fresh ones instead of tripping ERPNext's wariness of
		# an existing serial. no_copy fields (the cancelled attempt's
		# stock_entry link) must be dropped, and docstatus starts back at 0 -
		# copy_doc only clears it outside a test run.
		amended = frappe.copy_doc(document, ignore_no_copy=False)
		amended.amended_from = document.name
		amended.docstatus = 0
		amended.insert()
		amended.submit()

		self.assertEqual(amended.docstatus, 1)
		self.assertNotEqual([row.serial_no for row in amended.offcuts], old_serials)
		for row in amended.offcuts:
			self.assertTrue(frappe.db.exists("Serial No", row.serial_no))
			self.assertEqual(
				frappe.db.get_value("Serial No", row.serial_no, "custom_source_serial_no"), self.serial
			)

	# ------------------------------------------------------------- validate

	def test_the_plate_must_sit_in_a_warehouse(self):
		frappe.db.set_value("Serial No", self.serial, "warehouse", None)

		document = offcut_for(self.serial, ROWS)
		with self.assertRaises(frappe.ValidationError) as caught:
			document.insert()

		self.assertIn("not in any warehouse", str(caught.exception))

	def test_at_least_one_offcut_is_required(self):
		document = offcut_for(self.serial, [])
		with self.assertRaises(frappe.ValidationError) as caught:
			document.insert()

		self.assertIn("Add at least one offcut", str(caught.exception))

	def test_the_serial_must_be_active(self):
		frappe.db.set_value("Serial No", self.serial, "status", "Inactive")

		document = offcut_for(self.serial, ROWS)
		with self.assertRaises(frappe.ValidationError) as caught:
			document.insert()

		self.assertIn("is Inactive", str(caught.exception))

	def test_an_offcut_that_does_not_fit_is_refused(self):
		document = offcut_for(self.serial, [{"length_mm": 3000, "width_mm": 1250}])
		with self.assertRaises(frappe.ValidationError) as caught:
			document.insert()

		self.assertIn("does not fit inside", str(caught.exception))

	def test_an_offcut_below_the_minimum_is_refused(self):
		frappe.db.set_value("Item Group", GROUP, "custom_min_offcut_length_mm", 1200)

		document = offcut_for(self.serial, [{"length_mm": 1000, "width_mm": 500}])
		with self.assertRaises(frappe.ValidationError) as caught:
			document.insert()

		self.assertIn(cutting.TOO_SMALL, str(caught.exception))

	def test_scrap_that_would_result_needs_a_scrap_item(self):
		frappe.db.set_single_value("Plate Settings", "scrap_item", "")

		document = offcut_for(self.serial, ROWS)
		with self.assertRaises(frappe.ValidationError) as caught:
			document.insert()

		self.assertIn("no scrap Item set", str(caught.exception))

	def test_offcuts_heavier_than_the_plate_are_refused(self):
		# A plate light enough that the two standard rows outweigh it.
		serial = source_serial(self.item, 50.0, warehouse=self.warehouse)

		document = offcut_for(serial, ROWS)
		with self.assertRaises(frappe.ValidationError) as caught:
			document.insert()

		self.assertIn("add up to more than the plate weighs", str(caught.exception))
