"""Move the purchase inputs and plate details above Description on Purchase Orders."""

import json

import frappe

DOCTYPE = "Purchase Order Item"
DESCRIPTION_SECTION = "section_break_5"
QUANTITY_SECTION = "quantity_and_rate"


def execute():
	"""Reorder the live fields while preserving the rest of this site's layout.

	This runs after fixture sync on both install and migrate. Rebuilding the
	field order from live metadata avoids pinning this customization to one
	ERPNext release's full list of Purchase Order Item fields.
	"""
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	fields = frappe.get_meta(DOCTYPE).fields
	field_order = [field.fieldname for field in fields if field.fieldname]
	field_type_by_name = {field.fieldname: field.fieldtype for field in fields if field.fieldname}

	try:
		description_start = field_order.index(DESCRIPTION_SECTION)
		quantity_start = field_order.index(QUANTITY_SECTION)
	except ValueError:
		return

	# Already in the desired order; do not overwrite any other local layout edits.
	if quantity_start < description_start:
		return

	quantity_end = next(
		(
			index
			for index, fieldname in enumerate(field_order[quantity_start + 1 :], start=quantity_start + 1)
			if field_type_by_name.get(fieldname) == "Section Break"
		),
		len(field_order),
	)

	# Move the entire Quantity and Rate block, including Plate Details, as one
	# unit. Description and its child fields follow immediately after it.
	field_order = (
		field_order[:description_start]
		+ field_order[quantity_start:quantity_end]
		+ field_order[description_start:quantity_start]
		+ field_order[quantity_end:]
	)

	setter_name = f"{DOCTYPE}-main-field_order"
	value = json.dumps(field_order)
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
