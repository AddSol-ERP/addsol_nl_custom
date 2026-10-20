# Copyright (c) 2026, Your Company and contributors
# For license information, see license.txt

"""Submitting a Plate Offcut must repack the plate and issue its remainder.

The whole flow lives in on_submit - Items, Batches, reserved Serial Nos, the
Repack Stock Entry and the Material Issue that spends the remainder against
the Project - and nothing outside this module had ever run it. These tests
pin the Repack's shape (plate out, pieces back into the same warehouse,
every destination row carrying its own rate), the Material Issue against the
Project, circular offcuts, the traceability chain back to the parent plate,
and the cancel path that puts the plate back.

`bench --site <site> run-tests --app addsol_nl_custom`
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.addsol_nl_custom.plates import cutting
from addsol_nl_custom.addsol_nl_custom.plates.utils import round_half_up

from .test_cutting_estimate import (
	COMPANY,
	COST_PER_KG,
	GROUP,
	PLATE_WEIGHT,
	RATIO,
	THICKNESS,
	make_project,
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

# 245.313 - 65.657: what the offcuts do not weigh, when nothing is booked as
# scrap, is the piece the order keeps.
OFFCUTS_ONLY_KG = 179.656


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
		self.project = make_project()
		self.serial = source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse)

	def submit_offcut(self, serial=None, rows=ROWS, scrap_weight_kg=None, project=None):
		document = offcut_for(
			serial or self.serial,
			rows,
			project=project or self.project,
			scrap_weight_kg=scrap_weight_kg,
		)
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

		# Two offcuts plus the remainder piece. Scrap was not booked, so there
		# is no scrap row: whatever is not an offcut is the order's piece.
		self.assertEqual(len(destination_rows), len(ROWS) + 1)
		self.assertIn(document.remainder_item, [row.item_code for row in destination_rows])
		for row in destination_rows:
			with self.subTest(item=row.item_code):
				self.assertEqual(row.t_warehouse, self.warehouse)
				self.assertFalse(row.s_warehouse)

	def test_the_plate_is_consumed_and_the_offcut_serials_become_active(self):
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

	def test_the_scrap_row_is_booked_when_scrap_is_entered(self):
		document = self.submit_offcut(scrap_weight_kg=50)

		self.assertEqual(document.scrap_weight_kg, 50.0)
		self.assertEqual(document.scrap_value, round_half_up(50 * COST_PER_KG, 2))
		# 245.313 - 65.657 - 50 = 129.656 carried on as the order's piece.
		self.assertEqual(document.consumed_weight_kg, OFFCUTS_ONLY_KG - 50)
		self.assertEqual(document.consumed_value, round_half_up((OFFCUTS_ONLY_KG - 50) * COST_PER_KG, 2))

		scrap_rows = [
			row
			for row in frappe.get_doc("Stock Entry", document.stock_entry).items
			if row.item_code == SCRAP_ITEM
		]
		self.assertEqual(len(scrap_rows), 1)
		self.assertEqual(scrap_rows[0].qty, 50)
		self.assertEqual(scrap_rows[0].basic_rate, COST_PER_KG)
		self.assertEqual(scrap_rows[0].t_warehouse, self.warehouse)

	def test_no_scrap_booked_means_no_scrap_row_and_the_rest_is_the_remainder(self):
		document = self.submit_offcut()

		self.assertEqual(document.scrap_weight_kg, 0.0)
		self.assertEqual(document.consumed_weight_kg, OFFCUTS_ONLY_KG)
		items = frappe.get_doc("Stock Entry", document.stock_entry).items
		self.assertFalse(any(row.item_code == SCRAP_ITEM for row in items))

	def test_when_the_offcuts_take_the_whole_plate_there_is_no_remainder(self):
		# Same-size cut at ratio 1.0: the one offcut weighs exactly what the
		# plate does, so there is nothing left to book as scrap or as a piece.
		batch = frappe.db.get_value("Serial No", self.serial, "batch_no")
		frappe.db.set_value("Batch", batch, "custom_actual_to_theoretical_ratio", 1.0)

		document = offcut_for(self.serial, [{"length_mm": 2500, "width_mm": 1250}], project=self.project)
		document.insert()
		document.submit()

		self.assertEqual(document.scrap_weight_kg, 0.0)
		self.assertEqual(document.consumed_weight_kg, 0.0)
		self.assertFalse(document.remainder_item)
		self.assertFalse(document.material_issue)
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
		self.assertEqual(
			cutting.get_or_create_offcut_item(
				self.item.name, frappe._dict({"length_mm": 1000, "width_mm": 500})
			),
			offcut_item,
		)
		self.assertEqual(frappe.db.count("Item", {"item_code": offcut_item}), 1)

		item = frappe.get_doc("Item", offcut_item)
		self.assertEqual(item.item_group, GROUP)
		self.assertEqual(item.custom_source_item, self.item.name)
		self.assertEqual(item.custom_is_offcut, 1)
		self.assertEqual(item.custom_length_mm, 1000)
		self.assertEqual(item.custom_width_mm, 500)

	# ------------------------------------------------------------ circle cuts

	def test_a_circular_offcut_gets_its_own_item_named_by_diameter(self):
		document = self.submit_offcut(rows=[{"shape": "Circle", "diameter_mm": 400}])

		row = document.offcuts[0]
		self.assertEqual(row.offcut_item, f"{GROUP}-10-D400")

		item = frappe.get_doc("Item", row.offcut_item)
		self.assertEqual(item.custom_is_offcut, 1)
		self.assertEqual(item.custom_diameter_mm, 400)
		self.assertFalse(item.custom_length_mm)
		self.assertFalse(item.custom_width_mm)

		# The weight is the square across it, times pi/4: 400x400x10 square is
		# 12.56 theoretical, the circle 9.865, and 10.062 at the batch's ratio.
		self.assertEqual(row.theoretical_weight_kg, 9.865)
		self.assertEqual(row.weight_kg, 10.062)

	def test_a_circle_and_a_square_of_the_same_number_never_share_an_item(self):
		circle = self.submit_offcut(rows=[{"shape": "Circle", "diameter_mm": 400}])
		square = self.submit_offcut(
			serial=source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse),
			rows=[{"length_mm": 400, "width_mm": 400}],
		)

		self.assertEqual(circle.offcuts[0].offcut_item, f"{GROUP}-10-D400")
		self.assertEqual(square.offcuts[0].offcut_item, f"{GROUP}-10x400x400")
		self.assertNotEqual(circle.offcuts[0].offcut_item, square.offcuts[0].offcut_item)

	# ------------------------------------------------------- remainder piece

	def test_the_piece_that_is_neither_offcut_nor_scrap_is_issued_to_the_project(self):
		document = self.submit_offcut()

		# One Item per piece, named after the grade, the order and its number.
		self.assertTrue(document.remainder_item.startswith(f"{GROUP}-10-{self.project}-"))
		self.assertTrue(document.remainder_serial_no)
		self.assertTrue(document.remainder_batch_no)
		self.assertEqual(document.remainder_weight_kg, OFFCUTS_ONLY_KG)
		self.assertEqual(document.remainder_value, round_half_up(OFFCUTS_ONLY_KG * COST_PER_KG, 2))

		item = frappe.get_doc("Item", document.remainder_item)
		self.assertEqual(item.custom_is_remainder, 1)
		self.assertEqual(item.custom_remainder_project, self.project)
		# A remainder is a piece of plate, not an offcut: the Plate Stock
		# Register must keep listing it as stock, so the offcut flag stays off.
		self.assertFalse(item.custom_is_offcut)

		# The Material Issue is what spends the piece: one row, the serial,
		# the Project carried on the row so the GL entry lands on the order.
		issue = frappe.get_doc("Stock Entry", document.material_issue)
		self.assertEqual(issue.purpose, "Material Issue")
		self.assertEqual(len(issue.items), 1)
		row = issue.items[0]
		self.assertEqual(row.item_code, document.remainder_item)
		self.assertEqual(row.serial_no, document.remainder_serial_no)
		self.assertEqual(row.batch_no, document.remainder_batch_no)
		self.assertEqual(row.s_warehouse, self.warehouse)
		self.assertEqual(row.project, self.project)

	def test_the_remainder_serial_points_back_at_the_plate_it_was_cut_from(self):
		document = self.submit_offcut()

		serial = frappe.db.get_value(
			"Serial No", document.remainder_serial_no, ["custom_source_serial_no", "custom_weight_kg"], as_dict=True
		)
		self.assertEqual(serial.custom_source_serial_no, self.serial)
		self.assertEqual(serial.custom_weight_kg, document.consumed_weight_kg)

	def test_the_repack_prices_the_remainder_so_the_issue_spends_exactly_that(self):
		document = self.submit_offcut()

		repack_rows = [
			row
			for row in frappe.get_doc("Stock Entry", document.stock_entry).items
			if row.item_code == document.remainder_item
		]
		self.assertEqual(len(repack_rows), 1)
		self.assertEqual(repack_rows[0].set_basic_rate_manually, 1)
		self.assertEqual(repack_rows[0].basic_rate, document.remainder_value)
		self.assertEqual(repack_rows[0].basic_amount, document.remainder_value)

	def test_two_cuttings_for_one_project_take_their_own_running_numbers(self):
		first = self.submit_offcut()
		second = self.submit_offcut(serial=source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse))

		self.assertNotEqual(first.remainder_item, second.remainder_item)
		self.assertNotEqual(first.remainder_serial_no, second.remainder_serial_no)
		# Same project, so the same prefix, but the numbers move on.
		self.assertTrue(first.remainder_item.endswith("-00001"))
		self.assertTrue(second.remainder_item.endswith("-00002"))

	def test_another_projects_remainder_counts_from_its_own_number(self):
		other_project = make_project("PCR Estimate Other Project")

		first = self.submit_offcut()
		other = self.submit_offcut(
			serial=source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse), project=other_project
		)

		self.assertTrue(first.remainder_item.endswith(f"{self.project}-00001"))
		self.assertTrue(other.remainder_item.endswith(f"{other_project}-00001"))
		self.assertNotEqual(first.remainder_item, other.remainder_item)

	# ---------------------------------------------------------------- cancel

	def test_cancel_reverses_the_issue_and_the_repack_and_restores_the_plate(self):
		document = self.submit_offcut()
		serials = [row.serial_no for row in document.offcuts]
		batches = [row.batch_no for row in document.offcuts]
		remainder_serial = document.remainder_serial_no
		remainder_batch = document.remainder_batch_no

		document.cancel()

		self.assertEqual(document.docstatus, 2)
		# The Material Issue goes first - while it stood the remainder serial
		# was out of stock and the Repack could not have taken it back.
		self.assertEqual(frappe.db.get_value("Stock Entry", document.material_issue, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Stock Entry", document.stock_entry, "docstatus"), 2)

		parent = frappe.db.get_value("Serial No", self.serial, ["status", "warehouse"], as_dict=True)
		self.assertEqual(parent.status, "Active")
		self.assertEqual(parent.warehouse, self.warehouse)

		for serial in serials:
			self.assertEqual(frappe.db.get_value("Serial No", serial, "status"), "Inactive")

		self.assertEqual(frappe.db.get_value("Serial No", remainder_serial, "status"), "Inactive")

		for batch in [*batches, remainder_batch]:
			self.assertFalse(frappe.db.exists("Batch", batch))

		document.reload()
		for row in document.offcuts:
			self.assertFalse(row.serial_no)
			self.assertFalse(row.batch_no)
		self.assertFalse(document.remainder_serial_no)
		self.assertFalse(document.remainder_batch_no)

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

	def test_scrap_booked_needs_a_scrap_item(self):
		frappe.db.set_single_value("Plate Settings", "scrap_item", "")

		document = offcut_for(self.serial, ROWS, scrap_weight_kg=50)
		with self.assertRaises(frappe.ValidationError) as caught:
			document.insert()

		self.assertIn("no scrap Item set", str(caught.exception))

	def test_no_scrap_item_is_fine_when_nothing_is_booked(self):
		"""Zero scrap is the default and needs no scrap Item at all."""
		frappe.db.set_single_value("Plate Settings", "scrap_item", "")

		document = offcut_for(self.serial, ROWS)
		document.insert()

		self.assertEqual(document.scrap_weight_kg, 0.0)
		self.assertTrue(document.consumed_weight_kg > 0)

	def test_a_cutting_without_a_project_is_refused(self):
		"""Every cutting belongs to an order; without one the cost has nowhere to go.

		The field is mandatory on the form, but a document built by an API or
		an import reaches validate without the desk, so the server says no too.
		"""
		document = offcut_for(self.serial, ROWS)
		document.project = ""
		with self.assertRaises(frappe.ValidationError) as caught:
			document.insert()

		self.assertIn("Project", str(caught.exception))

	def test_a_project_of_another_company_is_refused(self):
		"""The remainder is issued against the Project, so the two share a company.

		Left to ERPNext this only surfaces deep inside on_submit, as an
		inscrutable "Project: X does not belong to the Company: Y" from the
		Stock Entry's validate - after the operator has filled everything in.
		The form says it plainly instead.
		"""
		other_company = frappe.db.get_value(
			"Company", {"is_group": 0, "name": ["!=", COMPANY]}, "name"
		)
		if not other_company:
			self.skipTest("the site has no second company to differ from")

		foreign = (
			frappe.get_doc(
				{
					"doctype": "Project",
					"project_name": "PCR Estimate Foreign Project",
					"company": other_company,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

		document = offcut_for(self.serial, ROWS, project=foreign)
		with self.assertRaises(frappe.ValidationError) as caught:
			document.insert()

		# The message body, not the throw's title (a title never reaches the
		# exception), and matched where no <b> tag from frappe.bold splits it.
		self.assertIn("same company", str(caught.exception))
		self.assertIn(foreign, str(caught.exception))

	def test_negative_scrap_is_refused(self):
		document = offcut_for(self.serial, ROWS, scrap_weight_kg=-5)
		with self.assertRaises(frappe.ValidationError) as caught:
			document.insert()

		self.assertIn("Scrap cannot be negative", str(caught.exception))

	def test_offcuts_heavier_than_the_plate_are_refused(self):
		# A plate light enough that the two standard rows outweigh it.
		serial = source_serial(self.item, 50.0, warehouse=self.warehouse)

		document = offcut_for(serial, ROWS)
		with self.assertRaises(frappe.ValidationError) as caught:
			document.insert()

		self.assertIn("add up to more than the plate weighs", str(caught.exception))
