"""Move the purchase inputs and plate details above Description on Purchase Orders."""

import json

import frappe

DOCTYPE = "Purchase Order Item"
DESCRIPTION_SECTION = "section_break_5"
QUANTITY_SECTION = "quantity_and_rate"


def execute():
	"""Reorder the live fields while preserving the rest of this site's layout.

	This runs after fixture sync on install and from the after_migrate hook.
	Rebuilding the field order from live metadata avoids pinning this
	customization to one ERPNext release's full list of Purchase Order Item
	fields.
	"""
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	fields = frappe.get_meta(DOCTYPE).fields
	field_order = [field.fieldname for field in fields if field.fieldname]
	field_type_by_name = {field.fieldname: field.fieldtype for field in fields if field.fieldname}

	if DESCRIPTION_SECTION not in field_order or QUANTITY_SECTION not in field_order:
		return

	# Move Quantity and Rate, then Plate Details, before Description. Frappe
	# treats each Section Break as the start of a new block, so Plate Details
	# must be repositioned separately from the preceding Quantity and Rate block.
	field_order = move_section_before(
		field_order, QUANTITY_SECTION, DESCRIPTION_SECTION, field_type_by_name
	)
	if "custom_plate_details_section" in field_order:
		field_order = move_section_before(
			field_order,
			"custom_plate_details_section",
			DESCRIPTION_SECTION,
			field_type_by_name,
		)

	value = json.dumps(field_order)
	setter_name = f"{DOCTYPE}-main-field_order"
	if value == json.dumps([field.fieldname for field in fields if field.fieldname]):
		return

	if frappe.db.exists("Property Setter", setter_name):
		frappe.db.set_value("Property Setter", setter_name, "value", value, update_modified=False)
		frappe.clear_cache(doctype=DOCTYPE)
	else:
		frappe.make_property_setter(
			{
				"doctype": DOCTYPE,
				"doctype_or_field": "DocType",
				"fieldname": None,
				"property": "field_order",
				"value": value,
				"property_type": "Data",
			},
			validate_fields_for_doctype=False,
		)
	print("Moved Purchase Order quantity, rate, and plate fields above Description")


def move_section_before(field_order, section_name, target_section, field_type_by_name):
	"""Move one Section Break and its fields immediately before another section."""
	try:
		section_start = field_order.index(section_name)
		target_start = field_order.index(target_section)
	except ValueError:
		return field_order

	if section_start < target_start:
		return field_order

	section_end = next(
		(
			index
			for index, fieldname in enumerate(field_order[section_start + 1 :], start=section_start + 1)
			if field_type_by_name.get(fieldname) == "Section Break"
		),
		len(field_order),
	)
	section_fields = field_order[section_start:section_end]
	remaining = field_order[:section_start] + field_order[section_end:]
	target_start = remaining.index(target_section)
	return remaining[:target_start] + section_fields + remaining[target_start:]
