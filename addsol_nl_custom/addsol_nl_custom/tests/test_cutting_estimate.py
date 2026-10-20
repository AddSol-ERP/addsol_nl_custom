# Copyright (c) 2026, Your Company and contributors
# For license information, see license.txt

"""The form must preview the same weights the save writes, and name the overage.

A Plate Offcut only produced its weights inside validate(), so the operator
learned offcuts were too heavy from the throw itself - with nothing on screen
to say by how much, and no way to see a row's weight until the document had
saved. `estimate_offcut_weights` asks for the same arithmetic earlier; these
tests pin that it really is the same arithmetic, that it flags a cutting the
save rejects, and that a line still being drawn does not blow the preview up.

`bench --site <site> run-tests --app addsol_nl_custom`
"""

import uuid

import frappe
from frappe.model.naming import make_autoname
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.addsol_nl_custom.plates.api import estimate_offcut_weights
from addsol_nl_custom.addsol_nl_custom.plates.settings import get_setting

from .test_item import make_group, make_plate_item, make_thickness

GROUP = "PCR Estimate Test"
THICKNESS = "10 mm"
COMPANY = "_Test Company"
WAREHOUSE_NAME = "PCR Estimate Store"
PROJECT_NAME = "PCR Estimate Project"

# The group's formula is (L * W * T * MF) / 100000 with MF 0.785, so a
# 2500 x 1250 x 10 plate weighs 245.3125 kg and is recorded as 245.313.
PLATE_WEIGHT = 245.313
RATIO = 1.02
COST_PER_KG = 50.0

# 1000 x 500 -> 39.25 theoretical -> 40.035 at ratio 1.02 -> 2001.75 at 50/kg
# 800 x 400  -> 25.12 theoretical -> 25.622 at ratio 1.02 -> 1281.10 at 50/kg
#   total 65.657 kg


def make_project(name=PROJECT_NAME):
	"""The order a cutting is made for. Plate Offcut will not save without one.

	The remainder's running number counts PER PROJECT in `tabSeries`, and
	that counter lives in the database - it survives the suite's rollback,
	and a Project's autonamed `name` (W-0007 here) is reused across tests
	because the Project numbering counter is itself rolled back. So a fresh
	call can inherit a counter an earlier test or run already advanced, and
	the first piece would not be `-00001`. Clearing this project's remainder
	counter makes the starting number deterministic.

	The Project must also belong to the SAME company as the warehouse the
	plate sits in, or ERPNext refuses the Material Issue that spends the
	remainder (accounts_controller.validate_company).
	"""
	existing = frappe.db.get_value("Project", {"project_name": name}, "name")
	if existing:
		project = existing
	else:
		project = (
			frappe.get_doc({"doctype": "Project", "project_name": name, "company": COMPANY})
			.insert(ignore_permissions=True)
			.name
		)

	# The series key embeds the project name (RMD-<project>-), so this wipes
	# only this project's remainder counter and leaves every other series be.
	frappe.db.delete("Series", {"name": ("like", f"%{project}%")})

	return project


def make_warehouse(name=WAREHOUSE_NAME):
	"""A warehouse of the test company to hang the plate off."""
	existing = frappe.db.get_value("Warehouse", {"warehouse_name": name, "company": COMPANY}, "name")
	if existing:
		return existing

	parent = frappe.db.get_value(
		"Warehouse", {"company": COMPANY, "is_group": 1, "parent_warehouse": ["is", "not set"]}, "name"
	)
	warehouse = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": name,
			"company": COMPANY,
			"parent_warehouse": parent,
		}
	).insert(ignore_permissions=True)

	return warehouse.name


def source_serial(item, weight, warehouse=None):
	"""An Active serial on `item`, weighed, in a warehouse, off a batch with a ratio.

	A plate's offcut weight is its theoretical weight times the batch's actual
	to theoretical ratio, so the batch is not optional here: without it the
	preview would only ever be tested against ratio 1.0 and could quietly drop
	the one multiplier that makes an offcut weigh what it really weighs.

	When `warehouse` is given the plate is also really IN stock: a Material
	Receipt posts the serial in. ERPNext always checks stock levels for
	serial-numbered ledger entries, even with allow_negative_stock on
	(stock_ledger.py:1007), so a fixture serial with no ledger history could
	never be cut - the Repack would die on NegativeStockError.
	"""
	batch = frappe.get_doc(
		{
			"doctype": "Batch",
			"batch_id": f"PCRE-{uuid.uuid4().hex[:8]}",
			"item": item.name,
		}
	).insert(ignore_permissions=True)

	serial = frappe.get_doc(
		{
			"doctype": "Serial No",
			"serial_no": f"PCRE-SN-{uuid.uuid4().hex[:8].upper()}",
			"item_code": item.name,
			"company": COMPANY,
		}
	).insert(ignore_permissions=True)

	frappe.db.set_value(
		"Batch",
		batch.name,
		{"custom_actual_to_theoretical_ratio": RATIO, "custom_cost_per_kg": COST_PER_KG},
	)

	if warehouse:
		receipt = frappe.new_doc("Stock Entry")
		receipt.stock_entry_type = "Material Receipt"
		receipt.purpose = "Material Receipt"
		receipt.company = COMPANY
		receipt.flags.ignore_permissions = True
		receipt.append(
			"items",
			{
				"t_warehouse": warehouse,
				"item_code": item.name,
				"qty": 1,
				"uom": "Nos",
				"conversion_factor": 1,
				"serial_no": serial.name,
				"batch_no": batch.name,
				"use_serial_batch_fields": 1,
			},
		)
		receipt.insert()
		receipt.submit()

	# ERPNext refuses a Serial No born with a status or a weight, so those are
	# set afterwards to the state a submitted receipt leaves behind (the
	# receipt itself moves the serial into the warehouse).
	frappe.db.set_value(
		"Serial No",
		serial.name,
		{
			"status": "Active",
			"custom_weight_kg": weight,
			"batch_no": batch.name,
			"warehouse": warehouse,
		},
	)

	return serial.name


def offcut_for(source_serial_no, rows, project=None, scrap_weight_kg=None):
	"""A Plate Offcut as the desk would build it.

	`project` defaults to the suite's own order, because the document is not
	saveable without one - a cutting belongs to an order, and the piece that
	is neither offcut nor scrap is issued against it.
	"""
	document = frappe.get_doc(
		{
			"doctype": "Plate Offcut",
			"source_serial_no": source_serial_no,
			"project": project or make_project(),
			"offcuts": [
				{
					"shape": row.get("shape", "Rectangle"),
					"length_mm": row.get("length_mm"),
					"width_mm": row.get("width_mm"),
					"diameter_mm": row.get("diameter_mm"),
				}
				for row in rows
			],
		}
	)

	if scrap_weight_kg is not None:
		document.scrap_weight_kg = scrap_weight_kg

	return document


class TestEstimateOffcutWeights(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# Per-test undo, the way the rest of the suite rebuilds its world.
		self.addCleanup(frappe.db.rollback)
		# The minimum offcut is the suite's choice, not the site's. The rows
		# drawn below are of no particular size, so inheriting whatever a site
		# has configured would make these tests pass or fail by accident.
		frappe.db.set_single_value("Plate Settings", "min_offcut_length_mm", 0)
		frappe.db.set_single_value("Plate Settings", "min_offcut_width_mm", 0)
		self.group = make_group(GROUP)
		self.thickness = make_thickness(THICKNESS)
		self.item = make_plate_item(group=GROUP, length=2500, width=1250)
		self.warehouse = make_warehouse()

	def test_the_preview_and_the_save_write_the_same_weights(self):
		serial = source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse)
		rows = [
			{"name": "row-1", "length_mm": 1000, "width_mm": 500},
			{"name": "row-2", "length_mm": 800, "width_mm": 400},
		]

		preview = estimate_offcut_weights(serial, rows)

		document = offcut_for(serial, rows)
		document.validate()

		for estimate, offcut in zip(preview["rows"], document.offcuts, strict=True):
			with self.subTest(length=offcut.length_mm):
				self.assertEqual(estimate["weight_kg"], offcut.weight_kg)
				self.assertEqual(estimate["theoretical_weight_kg"], offcut.theoretical_weight_kg)
				self.assertEqual(estimate["value"], offcut.value)

		self.assertEqual(preview["total_offcut_weight_kg"], document.total_offcut_weight_kg)
		self.assertEqual(preview["total_offcut_value"], document.total_offcut_value)
		self.assertEqual(preview["over_by_kg"], 0.0)

	def test_the_preview_reports_the_scrap_that_was_booked_and_the_piece_left_over(self):
		"""Scrap is typed; the preview must show it back and name the remainder."""
		serial = source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse)
		rows = [{"name": "row-1", "length_mm": 1000, "width_mm": 500}]

		preview = estimate_offcut_weights(serial, rows, scrap_weight_kg=100)

		# 245.313 - 40.035 - 100 = 105.278 kg carried on as the project's piece.
		self.assertEqual(preview["scrap_weight_kg"], 100.0)
		self.assertEqual(preview["scrap_value"], 5000.00)
		self.assertEqual(preview["consumed_weight_kg"], 105.278)
		self.assertEqual(preview["consumed_value"], 5263.90)

		document = offcut_for(serial, rows, scrap_weight_kg=100)
		document.validate()

		self.assertEqual(document.scrap_weight_kg, preview["scrap_weight_kg"])
		self.assertEqual(document.scrap_value, preview["scrap_value"])
		self.assertEqual(document.consumed_weight_kg, preview["consumed_weight_kg"])
		self.assertEqual(document.consumed_value, preview["consumed_value"])

	def test_booking_no_scrap_leaves_the_whole_rest_as_the_remainder(self):
		"""The default: nothing wasted, so everything not cut off is the piece."""
		serial = source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse)
		rows = [{"name": "row-1", "length_mm": 1000, "width_mm": 500}]

		preview = estimate_offcut_weights(serial, rows)

		self.assertEqual(preview["scrap_weight_kg"], 0.0)
		self.assertEqual(preview["scrap_value"], 0.0)
		self.assertEqual(preview["consumed_weight_kg"], 205.278)
		self.assertEqual(preview["consumed_value"], 10263.90)
		self.assertEqual(preview["over_by_kg"], 0.0)

	def test_a_circular_offcut_weighs_what_the_square_across_it_does_times_pi_over_4(self):
		"""A round cut is entered by diameter and weighs as a circle, not a square.

		400 mm across, 10 mm thick: the square is 12.56 kg theoretical, and the
		circle is that times pi/4 = 9.865 kg, 10.062 at the batch's 1.02 ratio.
		Checked against the number worked out by hand, because a preview that
		merely agreed with the save would still pass if both had dropped the
		shape factor.
		"""
		serial = source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse)
		rows = [{"name": "row-1", "shape": "Circle", "diameter_mm": 400}]

		preview = estimate_offcut_weights(serial, rows)
		estimate = preview["rows"][0]

		self.assertEqual(estimate["theoretical_weight_kg"], 9.865)
		self.assertEqual(estimate["weight_kg"], 10.062)
		self.assertEqual(estimate["value"], 503.10)

		document = offcut_for(serial, rows)
		document.validate()

		self.assertEqual(document.offcuts[0].weight_kg, estimate["weight_kg"])
		self.assertEqual(document.offcuts[0].value, estimate["value"])

	def test_a_circle_bigger_than_the_plate_is_refused(self):
		"""A round cut is measured across, so it cannot be wider than the plate."""
		serial = source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse)
		rows = [{"name": "row-1", "shape": "Circle", "diameter_mm": 1300}]

		document = offcut_for(serial, rows)
		with self.assertRaises(frappe.ValidationError) as caught:
			document.validate()

		self.assertIn("does not fit inside", str(caught.exception))
		self.assertIn("circle of 1300 mm", str(caught.exception))

	def test_the_preview_carries_the_batchs_ratio_not_just_the_formula(self):
		"""Guard against both sides agreeing on a wrong answer.

		Preview matching save would still pass if the ratio were dropped from
		both, so one row is checked against the number worked out by hand.
		"""
		serial = source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse)
		rows = [{"name": "row-1", "length_mm": 1000, "width_mm": 500}]

		preview = estimate_offcut_weights(serial, rows)
		estimate = preview["rows"][0]

		self.assertEqual(estimate["theoretical_weight_kg"], 39.25)
		self.assertEqual(estimate["weight_kg"], 40.035)
		self.assertEqual(estimate["value"], 2001.75)

	def test_the_preview_names_an_overage_the_save_rejects(self):
		"""The whole point: how much too heavy, before pressing Save."""
		serial = source_serial(self.item, 50.0, warehouse=self.warehouse)
		rows = [
			{"name": "row-1", "length_mm": 1000, "width_mm": 500},
			{"name": "row-2", "length_mm": 800, "width_mm": 400},
		]

		preview = estimate_offcut_weights(serial, rows)

		# 65.657 out of a 50 kg plate, no scrap booked: 15.657 kg more out
		# than in, and no remainder to speak of.
		self.assertEqual(preview["over_by_kg"], 15.657)
		self.assertEqual(preview["total_offcut_weight_kg"], 65.657)
		self.assertEqual(preview["scrap_weight_kg"], 0.0)
		self.assertEqual(preview["consumed_weight_kg"], 0.0)

		document = offcut_for(serial, rows)
		with self.assertRaises(frappe.ValidationError) as caught:
			document.validate()

		self.assertIn("add up to more than the plate weighs", str(caught.exception))

	def test_a_line_still_being_drawn_is_not_estimated(self):
		"""A length typed before its width must not throw on a zero size.

		compute_theoretical_weight refuses to guess the weight of a zero-size
		plate - correctly, because that is what the save needs from it. The
		preview has nothing to say yet, so it reports zeroes and lets the save
		reject the half-drawn line through check_offcut_fits as it always has.
		"""
		serial = source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse)
		rows = [
			{"name": "row-1", "length_mm": 1000, "width_mm": 0},
			{"name": "row-2", "length_mm": 0, "width_mm": 400},
			{"name": "row-3", "shape": "Circle", "diameter_mm": 0},
		]

		preview = estimate_offcut_weights(serial, rows)

		self.assertEqual([row["weight_kg"] for row in preview["rows"]], [0.0, 0.0, 0.0])
		self.assertEqual(preview["total_offcut_weight_kg"], 0.0)
		self.assertEqual(preview["over_by_kg"], 0.0)

	def test_each_line_name_comes_back_so_a_reply_can_be_matched(self):
		"""The client matches replies on the row's own name, never on position."""
		serial = source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse)
		rows = [
			{"name": "row-a", "length_mm": 1000, "width_mm": 500},
			{"name": "row-b", "length_mm": 800, "width_mm": 400},
		]

		preview = estimate_offcut_weights(serial, rows)

		self.assertEqual([row["name"] for row in preview["rows"]], ["row-a", "row-b"])

	def test_the_endpoint_is_not_reachable_by_a_guest(self):
		"""AGENTS.md: whitelisted APIs run for a signed-in user only."""
		self.assertIn(estimate_offcut_weights, frappe.whitelisted)
		self.assertNotIn(estimate_offcut_weights, frappe.guest_methods)

	def test_a_blank_setting_falls_back_to_its_default(self):
		"""A Single DocType nobody has saved must still behave as shipped.

		`get_single_value` returns '' - never None - for a Single field that
		has never been written. Testing only for None meant a field shipped
		with a default in its DocType JSON resolved to '' on every site that
		had not opened the form yet. `remainder_naming_series` was blank that
		way, so every cutting's remainder drew from one global '' counter
		instead of one per Project, and the two running-number tests failed
		only because an earlier run had advanced that shared counter.
		"""
		fieldname = "remainder_naming_series"
		shipped = "RMD-.{project}.-.#####"
		previous = frappe.db.get_single_value("Plate Settings", fieldname)
		self.addCleanup(
			lambda: frappe.db.set_single_value("Plate Settings", fieldname, previous)
		)

		frappe.db.set_single_value("Plate Settings", fieldname, "")

		self.assertEqual(get_setting(fieldname, shipped), shipped)

		# And a real per-Project series really is per-Project: the blank
		# series would mint a bare number with no project in it at all.
		number = make_autoname(get_setting(fieldname, shipped), doc={"project": "W-0007"})
		self.assertIn("-W-0007-", number)
