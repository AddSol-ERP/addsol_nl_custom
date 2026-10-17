# Copyright (c) 2026, Your Company and contributors
# For license information, see license.txt

"""The form must preview the same weights the save writes, and name the overage.

Before this, a Plate Cutting Record only produced its weights inside validate(),
so the operator learned offcuts and scrap were too heavy from the throw itself -
with nothing on screen to say by how much, and no way to see a row's weight
until the document had saved. `estimate_offcut_weights` asks for the same
arithmetic earlier; these tests pin that it really is the same arithmetic, that
it flags a cutting the save rejects, and that a line still being drawn does not
blow the preview up.

`bench --site <site> run-tests --app addsol_nl_custom`
"""

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.addsol_nl_custom.plates.api import estimate_offcut_weights

from .test_item import make_group, make_plate_item, make_thickness

GROUP = "PCR Estimate Test"
THICKNESS = "10 mm"
COMPANY = "_Test Company"

# The group's formula is (L * W * T * MF) / 100000 with MF 0.785, so a
# 2500 x 1250 x 10 plate weighs 245.3125 kg and is recorded as 245.313.
PLATE_WEIGHT = 245.313
RATIO = 1.02
COST_PER_KG = 50.0

# 1000 x 500 -> 39.25 theoretical -> 40.035 at ratio 1.02 -> 2001.75 at 50/kg
# 800 x 400  -> 25.12 theoretical -> 25.622 at ratio 1.02 -> 1281.10 at 50/kg
#   total 65.657 kg


def source_serial(item, weight):
	"""An Active serial on `item`, weighed, hanging off a batch with a ratio.

	A plate's offcut weight is its theoretical weight times the batch's actual
	to theoretical ratio, so the batch is not optional here: without it the
	preview would only ever be tested against ratio 1.0 and could quietly drop
	the one multiplier that makes an offcut weigh what it really weighs.
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
	# ERPNext refuses a Serial No born with a status or a weight, so both are
	# set afterwards to the state a submitted receipt leaves behind.
	frappe.db.set_value(
		"Serial No",
		serial.name,
		{"status": "Active", "custom_weight_kg": weight, "batch_no": batch.name},
	)

	return serial.name


def record_for(source_serial_no, rows, scrap=0):
	return frappe.get_doc(
		{
			"doctype": "Plate Cutting Record",
			"source_serial_no": source_serial_no,
			"scrap_weight_kg": scrap,
			"offcuts": [{"length_mm": row["length_mm"], "width_mm": row["width_mm"]} for row in rows],
		}
	)


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

	def test_the_preview_and_the_save_write_the_same_weights(self):
		serial = source_serial(self.item, PLATE_WEIGHT)
		rows = [
			{"name": "row-1", "length_mm": 1000, "width_mm": 500},
			{"name": "row-2", "length_mm": 800, "width_mm": 400},
		]

		preview = estimate_offcut_weights(serial, rows, scrap_weight_kg=10)

		record = record_for(serial, rows, scrap=10)
		record.validate()

		for estimate, offcut in zip(preview["rows"], record.offcuts, strict=True):
			with self.subTest(length=offcut.length_mm):
				self.assertEqual(estimate["weight_kg"], offcut.weight_kg)
				self.assertEqual(estimate["theoretical_weight_kg"], offcut.theoretical_weight_kg)
				self.assertEqual(estimate["value"], offcut.value)

		self.assertEqual(preview["total_offcut_weight_kg"], record.total_offcut_weight_kg)
		self.assertEqual(preview["total_offcut_value"], record.total_offcut_value)
		self.assertEqual(preview["consumed_weight_kg"], record.consumed_weight_kg)
		self.assertEqual(preview["over_by_kg"], 0.0)

	def test_the_preview_carries_the_batchs_ratio_not_just_the_formula(self):
		"""Guard against both sides agreeing on a wrong answer.

		Preview matching save would still pass if the ratio were dropped from
		both, so one row is checked against the number worked out by hand.
		"""
		serial = source_serial(self.item, PLATE_WEIGHT)
		rows = [{"name": "row-1", "length_mm": 1000, "width_mm": 500}]

		preview = estimate_offcut_weights(serial, rows, scrap_weight_kg=0)
		estimate = preview["rows"][0]

		self.assertEqual(estimate["theoretical_weight_kg"], 39.25)
		self.assertEqual(estimate["weight_kg"], 40.035)
		self.assertEqual(estimate["value"], 2001.75)

	def test_the_preview_names_an_overage_the_save_rejects(self):
		"""The whole point: how much too heavy, before pressing Save."""
		serial = source_serial(self.item, 50.0)
		rows = [
			{"name": "row-1", "length_mm": 1000, "width_mm": 500},
			{"name": "row-2", "length_mm": 800, "width_mm": 400},
		]

		preview = estimate_offcut_weights(serial, rows, scrap_weight_kg=0)

		# 65.657 out of a 50 kg plate.
		self.assertEqual(preview["over_by_kg"], 15.657)
		self.assertEqual(preview["total_offcut_weight_kg"], 65.657)

		record = record_for(serial, rows, scrap=0)
		with self.assertRaises(frappe.ValidationError) as caught:
			record.validate()

		self.assertIn("add up to more than the plate weighs", str(caught.exception))

	def test_a_line_still_being_drawn_is_not_estimated(self):
		"""A length typed before its width must not throw on a zero size.

		compute_theoretical_weight refuses to guess the weight of a zero-size
		plate - correctly, because that is what the save needs from it. The
		preview has nothing to say yet, so it reports zeroes and lets the save
		reject the half-drawn line through check_offcut_fits as it always has.
		"""
		serial = source_serial(self.item, PLATE_WEIGHT)
		rows = [
			{"name": "row-1", "length_mm": 1000, "width_mm": 0},
			{"name": "row-2", "length_mm": 0, "width_mm": 400},
		]

		preview = estimate_offcut_weights(serial, rows, scrap_weight_kg=0)

		self.assertEqual([row["weight_kg"] for row in preview["rows"]], [0.0, 0.0])
		self.assertEqual(preview["total_offcut_weight_kg"], 0.0)
		self.assertEqual(preview["over_by_kg"], 0.0)

	def test_each_line_name_comes_back_so_a_reply_can_be_matched(self):
		"""The client matches replies on the row's own name, never on position."""
		serial = source_serial(self.item, PLATE_WEIGHT)
		rows = [
			{"name": "row-a", "length_mm": 1000, "width_mm": 500},
			{"name": "row-b", "length_mm": 800, "width_mm": 400},
		]

		preview = estimate_offcut_weights(serial, rows, scrap_weight_kg=0)

		self.assertEqual([row["name"] for row in preview["rows"]], ["row-a", "row-b"])

	def test_the_endpoint_is_not_reachable_by_a_guest(self):
		"""AGENTS.md: whitelisted APIs run for a signed-in user only."""
		self.assertIn(estimate_offcut_weights, frappe.whitelisted)
		self.assertNotIn(estimate_offcut_weights, frappe.guest_methods)
