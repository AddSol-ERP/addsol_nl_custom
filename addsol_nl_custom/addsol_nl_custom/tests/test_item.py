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


def make_group(group_name=GROUP, mf=0.785, formula=THREE_D_FORMULA):
	if frappe.db.exists("Item Group", group_name):
		frappe.delete_doc("Item Group", group_name, force=True, ignore_missing=True)

	frappe.get_doc(
		{
			"doctype": "Item Group",
			"item_group_name": group_name,
			"parent_item_group": "All Item Groups",
			"is_group": 0,
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
		}
	).insert(ignore_permissions=True)


class TestPlateItem(FrappeTestCase):
	"""Part B1 to B5."""

	def setUp(self):
		super().setUp()
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
		make_group("Plain Consumable Group", mf=None, formula=None)
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "PLAIN-CONSUMABLE",
				"item_name": "Plain Consumable",
				"item_group": "Plain Consumable Group",
				"stock_uom": "Kg",
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)

		self.assertEqual(item.stock_uom, "Kg")
		self.assertEqual(item.has_serial_no, 0)
		self.assertEqual(item.valuation_method, "FIFO")  # ERPNext's own default

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

	def test_b5_refuses_to_move_the_stock_uom_of_an_item_with_stock(self):
		item = make_plate_item()
		item.stock_uom = "Kg"

		with patch.object(item_defaults, "item_has_stock", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				apply_plate_item_defaults(item)

	def test_b4_locks_the_dimensions_once_the_item_is_used(self):
		item = make_plate_item()
		self.assertFalse(item_has_transactions(item.name))

		# Put the plate into a bill of materials, which is enough to freeze it.
		frappe.get_doc(
			{
				"doctype": "BOM",
				"item": make_sink_item(),
				"bom_items": [{"item_code": item.name, "qty": 1}],
			}
		).insert(ignore_permissions=True)

		self.assertTrue(item_has_transactions(item.name))

		reloaded = frappe.get_doc("Item", item.name)
		reloaded.custom_length_mm = 3000

		with self.assertRaises(frappe.ValidationError):
			reloaded.save()

	def test_b4_lets_an_unused_item_change_its_dimensions(self):
		item = make_plate_item()
		self.assertFalse(item_has_transactions(item.name))

		reloaded = frappe.get_doc("Item", item.name)
		reloaded.custom_length_mm = 3000
		reloaded.save()

		# The name does not move under an Item that is still unused.
		self.assertEqual(reloaded.name, "MS Plate 250 Test-10x2500x1250")
		self.assertEqual(reloaded.custom_length_mm, 3000)


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
			}
		).insert(ignore_permissions=True)
	return name
