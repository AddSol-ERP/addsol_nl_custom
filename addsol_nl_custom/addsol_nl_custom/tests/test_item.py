# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.addsol_nl_custom.plates import item_defaults
from addsol_nl_custom.addsol_nl_custom.plates.item_defaults import (
	PLATE_ITEM_DEFAULTS,
	apply_plate_item_defaults,
	item_has_transactions,
)

THREE_D_FORMULA = "(L * W * T * MF) / 100000"
GROUP = "MS Plate 250 Test"
THICKNESS = "10 mm"

# India Compliance makes HSN/SAC mandatory on sales Items when GST Settings
# says so, and reads the code back out of the HSN master while saving the
# Item's taxes. 999999 is what this site's plate Items carry, so the tests
# create Items the way production does instead of depending on a site where
# the setting happens to be off.
TEST_HSN_CODE = "999999"


def hsn_for_tests() -> dict:
	"""The HSN fields for a test Item, or nothing when they cannot apply.

	Item.gst_hsn_code and the GST HSN Code master only exist when India
	Compliance is installed, so a plain Frappe site gets no field at all
	rather than one it has nowhere to store.
	"""
	if not frappe.get_meta("Item").has_field("gst_hsn_code"):
		return {}
	if not frappe.db.exists("GST HSN Code", TEST_HSN_CODE):
		return {}
	return {"gst_hsn_code": TEST_HSN_CODE}


def make_group(group_name=GROUP, mf=0.785, formula=THREE_D_FORMULA, weighed=True):
	if frappe.db.exists("Item Group", group_name):
		frappe.delete_doc("Item Group", group_name, force=True, ignore_missing=True)

	frappe.get_doc(
		{
			"doctype": "Item Group",
			"item_group_name": group_name,
			"parent_item_group": "All Item Groups",
			"is_group": 0,
			"custom_is_weighed_grade": 1 if weighed else 0,
			"custom_multiplication_factor": mf,
			"custom_formula": formula,
			"custom_batch_number_series": "PLB-.YY.-.#####",
			"custom_serial_no_series": "PL-.######",
		}
	).insert(ignore_permissions=True)

	return group_name


def make_thickness(value=THICKNESS):
	if frappe.db.exists("Thickness", value):
		frappe.delete_doc("Thickness", value, force=True, ignore_missing=True)

	return frappe.get_doc({"doctype": "Thickness", "thickness_value": value}).insert(ignore_permissions=True)


def make_plate_item(group=GROUP, length=2500, width=1250):
	return frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": "PLACEHOLDER",
			"item_name": "PLACEHOLDER",
			"item_group": group,
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"custom_thickness_dropdown": THICKNESS,
			"custom_length_mm": length,
			"custom_width_mm": width,
			**hsn_for_tests(),
		}
	).insert(ignore_permissions=True)


class TestPlateItem(FrappeTestCase):
	"""Part B1 to B5."""

	def setUp(self):
		super().setUp()
		# FrappeTestCase rolls the database back once per class, not once per
		# test, so an Item an earlier test in this class created would still be
		# there and make_plate_item would hit it as a duplicate entry. Undo
		# whatever the last test left; the two helpers below rebuild the world
		# this test needs.
		self.addCleanup(frappe.db.rollback)
		self.group = make_group()
		self.thickness = make_thickness()

	def test_t1_item_is_named_and_weighed(self):
		item = make_plate_item()

		# Acceptance test T1 from the specification.
		self.assertEqual(item.name, "MS Plate 250 Test-10x2500x1250")
		self.assertEqual(item.item_code, item.name)  # B1
		self.assertEqual(item.custom_estimated_weight, 245.313)  # B3
		self.assertEqual(item.weight_per_unit, 245.313)
		self.assertEqual(item.weight_uom, "Kg")

	def test_name_has_no_trailing_zeros(self):
		# B2 - the Float fields used to produce 2500.0x1250.0.
		self.assertNotIn(".0", make_plate_item().name)

	def test_b5_forces_the_stock_options(self):
		item = make_plate_item()

		for field, expected in PLATE_ITEM_DEFAULTS.items():
			with self.subTest(field=field):
				self.assertEqual(item.get(field), expected)

		self.assertEqual(item.stock_uom, "Nos")
		self.assertEqual(item.has_batch_no, 1)
		self.assertEqual(item.create_new_batch, 1)
		self.assertEqual(item.has_serial_no, 1)
		self.assertEqual(item.valuation_method, "FIFO")
		self.assertEqual(item.is_purchase_item, 1)

	def test_b5_copies_the_series_from_the_group(self):
		item = make_plate_item()
		self.assertEqual(item.batch_number_series, "PLB-.YY.-.#####")
		self.assertEqual(item.serial_no_series, "PL-.######")

	def test_a_series_typed_on_the_item_is_not_overwritten(self):
		item = make_plate_item()
		item.batch_number_series = "MY-OWN-.#####"
		item.save()

		reloaded = frappe.get_doc("Item", item.name)
		self.assertEqual(reloaded.batch_number_series, "MY-OWN-.#####")

	def test_an_item_under_a_plain_group_is_left_alone(self):
		make_group("Plain Consumable Group", mf=None, formula=None, weighed=False)
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "PLAIN-CONSUMABLE",
				"item_name": "Plain Consumable",
				"item_group": "Plain Consumable Group",
				"stock_uom": "Kg",
				"is_stock_item": 1,
				**hsn_for_tests(),
			}
		).insert(ignore_permissions=True)

		self.assertEqual(item.stock_uom, "Kg")
		self.assertEqual(item.has_serial_no, 0)
		# ERPNext leaves valuation_method blank on a fresh Item and resolves it
		# from Stock Settings (FIFO unless the company changed it) at valuation
		# time. The plate defaults would have written FIFO here, so whatever
		# ERPNext itself ships as the default is the "left alone" proof.
		erpnext_default = frappe.get_meta("Item").get_field("valuation_method").default or ""
		self.assertEqual(item.valuation_method, erpnext_default)

	def test_b5_never_flips_serial_tracking_onto_existing_stock(self):
		item = make_plate_item()
		item.has_serial_no = 0
		item.has_batch_no = 0
		item.create_new_batch = 0

		with patch.object(item_defaults, "item_has_stock", return_value=True):
			apply_plate_item_defaults(item)

		self.assertEqual(item.has_serial_no, 0)
		self.assertEqual(item.has_batch_no, 0)
		self.assertEqual(item.create_new_batch, 0)

	def test_b5_leaves_a_legacy_kg_item_alone_and_stays_editable(self):
		# A Kg-era plate Item that already holds stock must not be locked
		# against edits, and must not have per-piece options forced onto it.
		item = make_plate_item()
		item.stock_uom = "Kg"
		item.has_serial_no = 0
		item.has_batch_no = 0
		item.create_new_batch = 0
		item.valuation_method = "FIFO"
		item.serial_no_series = "OLD-SERIES-.#####"

		messages = []
		with (
			patch.object(item_defaults, "item_has_stock", return_value=True),
			# A lambda rather than side_effect=messages.append: msgprint is
			# called with keyword arguments, and list.append takes none.
			patch.object(
				item_defaults.frappe,
				"msgprint",
				lambda *args, **kwargs: messages.append(args[0]),
			),
		):
			apply_plate_item_defaults(item)

		# Untouched.
		self.assertEqual(item.stock_uom, "Kg")
		self.assertEqual(item.has_serial_no, 0)
		self.assertEqual(item.has_batch_no, 0)
		self.assertEqual(item.create_new_batch, 0)
		self.assertEqual(item.serial_no_series, "OLD-SERIES-.#####")

		# And told why, rather than refused.
		self.assertEqual(len(messages), 1)
		self.assertIn("Kg", messages[0])
		self.assertIn("Nos", messages[0])

	def test_b5_leaves_a_legacy_kg_item_editable_on_save(self):
		item = make_plate_item()
		item.stock_uom = "Kg"

		reloaded = frappe.get_doc("Item", item.name)
		reloaded.stock_uom = "Kg"

		with patch.object(item_defaults, "item_has_stock", return_value=True):
			reloaded.save()  # must not raise

		self.assertEqual(frappe.db.get_value("Item", item.name, "stock_uom"), "Kg")

	def test_b4_allows_dimension_changes_after_the_item_is_used(self):
		item = make_plate_item()
		self.assertFalse(item_has_transactions(item.name))

		# Put the plate into a bill of materials, which is enough to freeze it.
		# BOM.project is mandatory on this bench (a Property Setter), and a
		# Project names itself from its naming series, so the BOM gets the
		# name the insert came back with rather than the title typed in.
		project = frappe.db.get_value("Project", {"project_name": "Test Plate BOM Project"})
		if not project:
			project = (
				frappe.get_doc({"doctype": "Project", "project_name": "Test Plate BOM Project"})
				.insert(ignore_permissions=True)
				.name
			)

		frappe.get_doc(
			{
				"doctype": "BOM",
				"item": make_sink_item(),
				"project": project,
				"items": [{"item_code": item.name, "qty": 1}],
			}
		).insert(ignore_permissions=True)

		self.assertTrue(item_has_transactions(item.name))

		reloaded = frappe.get_doc("Item", item.name)
		reloaded.custom_length_mm = 3000

		reloaded.save()
		self.assertEqual(reloaded.custom_length_mm, 3000)

	def test_b4_lets_an_unused_item_change_its_dimensions(self):
		item = make_plate_item()
		self.assertFalse(item_has_transactions(item.name))

		reloaded = frappe.get_doc("Item", item.name)
		reloaded.custom_length_mm = 3000
		reloaded.save()

		# The name does not move under an Item that is still unused.
		self.assertEqual(reloaded.name, "MS Plate 250 Test-10x2500x1250")
		self.assertEqual(reloaded.custom_length_mm, 3000)

	def test_a_new_item_must_be_weighable(self):
		# Strict on the way in: a missing dimension is a setup mistake and is
		# reported when the Item is created, not on a receipt six weeks later.
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": "NO-WIDTH",
					"item_name": "No Width",
					"item_group": GROUP,
					"stock_uom": "Nos",
					"is_stock_item": 1,
					"custom_thickness_dropdown": THICKNESS,
					"custom_length_mm": 2500,
					"custom_width_mm": 0,
					**hsn_for_tests(),
				}
			).insert(ignore_permissions=True)

	def test_an_existing_item_stays_editable_when_its_weight_cannot_be_recomputed(self):
		# Half-configured legacy Items must not be locked out of edits. The
		# save is not wrapped in a msgprint patch: patching frappe.msgprint
		# would also swallow frappe.throw, which is how the weight calculation
		# refuses a zero dimension - the recomputation would quietly return 0
		# instead of failing and leaving the old weight standing.
		item = make_plate_item()
		reloaded = frappe.get_doc("Item", item.name)
		reloaded.custom_width_mm = 0

		reloaded.save()  # must not raise

		self.assertEqual(
			frappe.db.get_value("Item", item.name, "custom_estimated_weight"),
			245.313,  # the weight from before, left standing
		)


def make_sink_item():
	"""A finished good to hang the BOM off."""
	name = "Test Tank"
	if not frappe.db.exists("Item", name):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": name,
				"item_name": name,
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"is_manufactured_item": 1,
				**hsn_for_tests(),
			}
		).insert(ignore_permissions=True)
	return name
