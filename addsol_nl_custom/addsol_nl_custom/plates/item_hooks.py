# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe

from addsol_nl_custom.addsol_nl_custom.plates.grouping import is_weighed_group
from addsol_nl_custom.addsol_nl_custom.plates.item_defaults import (
	apply_plate_item_defaults,
	item_has_transactions,
)
from addsol_nl_custom.addsol_nl_custom.plates.utils import build_plate_description, build_plate_item_name
from addsol_nl_custom.addsol_nl_custom.plates.weight import compute_theoretical_weight, get_item_thickness_mm

# The fields that decide an Item's size. If any of them moves on an Item that
# is already in use, the size is frozen.
DIMENSION_FIELDS = ("item_group", "custom_thickness_dropdown", "custom_length_mm", "custom_width_mm")

DIMENSION_LOCK_MESSAGE = "Dimensions cannot be changed because this item has transactions. Create a new item."


def item_autoname(doc, method):
	"""Name a weighed Item from its grade, thickness, length and width.

	For items without dimensions, fall back to whatever the user typed.
	"""
	if doc.custom_thickness_dropdown and doc.item_group:
		doc.name = build_plate_item_name(
			doc.item_group,
			get_item_thickness_mm(doc),
			doc.custom_length_mm,
			doc.custom_width_mm,
		)
	elif doc.item_name:
		doc.name = doc.item_name
	else:
		frappe.throw("Item Name is required for items without thickness.")

	# Item links are stored against the name, so item_code has to follow it.
	# ERPNext's Item controller keeps the two in step on a plain save, but this
	# hook replaces doc.name, so item_code has to be set here too.
	doc.item_code = doc.name


def item_validate(doc, method):
	"""Keep an Item's name, description, weight and stock options in step."""
	if not (doc.custom_thickness_dropdown and doc.item_group):
		return

	thickness_mm = get_item_thickness_mm(doc)
	length_mm = doc.custom_length_mm
	width_mm = doc.custom_width_mm

	expected_name = build_plate_item_name(doc.item_group, thickness_mm, length_mm, width_mm)

	if doc.get("__islocal"):
		doc.name = expected_name
		doc.item_code = expected_name
	else:
		lock_dimensions(doc)
		if doc.name != expected_name:
			frappe.msgprint(
				f"Item name is {doc.name} but its dimensions give {expected_name}. "
				"The name is not changed on save.",
				alert=True,
			)

	if doc.item_name != expected_name:
		doc.item_name = expected_name

	if doc.description == "*New*" or not doc.description:
		doc.description = build_plate_description(thickness_mm, length_mm, width_mm)

	if is_weighed_group(doc.item_group):
		set_estimated_weight(doc, thickness_mm, length_mm, width_mm)
		apply_plate_item_defaults(doc)


def set_estimated_weight(doc, thickness_mm, length_mm, width_mm) -> None:
	"""Store the theoretical weight of one piece on the Item.

	Both custom_estimated_weight and weight_per_unit get the same number so
	purchasing can quote a weight per piece without recomputing anything.
	"""
	weight = compute_theoretical_weight(doc.item_group, thickness_mm, length_mm, width_mm)

	doc.set("custom_estimated_weight", weight)
	doc.set("weight_per_unit", weight)
	doc.set("weight_uom", "Kg")


def lock_dimensions(doc) -> None:
	"""Stop the size of an Item that is already in use from moving.

	A purchase order, a receipt or a bill of materials quotes the old size, and
	renaming the Item would leave all of them pointing at a plate whose
	dimensions no longer match.
	"""
	changed = [field for field in DIMENSION_FIELDS if doc.has_value_changed(field)]
	if not changed:
		return

	if item_has_transactions(doc.name):
		frappe.throw(
			DIMENSION_LOCK_MESSAGE,
			title="Dimensions cannot be changed",
		)


@frappe.whitelist()
def get_item_has_transactions(item_code) -> bool:
	"""Whether an Item is already in use, so the desk can lock its dimensions."""
	return item_has_transactions(item_code)
