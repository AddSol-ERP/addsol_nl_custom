"""Put the plate custom fields in a sensible place on their forms.

A `field_order` Property Setter replaces the DocType's *entire* field order, so
one built by guessing from the fixture file would hide every standard column -
the Purchase Order form would arrive with nothing on it but the weight columns.

This reads the live metadata instead: take whatever order the DocType already
resolves to, and append the plate fields to it. Anything already present is
left where it is, so running this twice is a no-op.
"""

import json

import frappe

# DocType -> custom fields, in the order they should appear.
FIELD_ORDER = {
	"Item": ["custom_is_offcut", "custom_source_item"],
	"Item Group": [
		"custom_min_offcut_length_mm",
		"custom_min_offcut_width_mm",
	],
	"Supplier": ["custom_grade_rates"],
	"Purchase Order": ["custom_total_est_weight_kg"],
	"Purchase Order Item": [
		"custom_is_plate",
		"custom_rate_per_kg",
		"custom_unit_weight_kg",
		"custom_est_weight_kg",
	],
	"Purchase Receipt": [
		"custom_total_billable_weight_kg",
		"custom_total_est_weight_kg",
	],
	"Purchase Receipt Item": [
		"custom_is_plate",
		"custom_rate_per_kg",
		"custom_unit_weight_kg",
		"custom_est_weight_kg",
		"custom_supplier_weight_kg",
		"custom_weighbridge_weight_kg",
		"custom_variance_pct",
		"custom_weight_decision",
		"custom_billable_weight_kg",
		"custom_weight_per_plate_kg",
		"custom_heat_number",
		"custom_mtc_no",
	],
	"Purchase Invoice": ["custom_total_billable_weight_kg"],
	"Purchase Invoice Item": [
		"custom_is_plate",
		"custom_rate_per_kg",
		"custom_billable_weight_kg",
		"custom_weight_per_plate_kg",
		"custom_heat_number",
	],
	"Batch": [
		"custom_heat_number",
		"custom_mtc_no",
		"custom_grade",
		"custom_weight_per_plate_kg",
		"custom_cost_per_kg",
		"custom_actual_to_theoretical_ratio",
		"custom_source_batch",
	],
	"Serial No": ["custom_weight_kg", "custom_heat_number", "custom_source_serial_no"],
	"Stock Entry Detail": ["custom_cutting_record"],
}


def execute():
	for doctype, custom_fields in FIELD_ORDER.items():
		apply_field_order(doctype, custom_fields)


def apply_field_order(doctype, custom_fields):
	meta = frappe.get_meta(doctype)

	# What the DocType resolves to right now, property setters included. This is
	# the authoritative starting point; the fixture file is not.
	order = list(meta.get_field_order())

	live = {field.fieldname for field in meta.fields}
	missing = [fieldname for fieldname in custom_fields if fieldname not in live]

	if missing:
		# The custom field has not landed yet. Never write a field_order that
		# names a field the DocType does not have.
		print(f"{doctype}: skipped, custom field(s) not present yet: {', '.join(missing)}")
		return

	changed = False
	for fieldname in custom_fields:
		if fieldname not in order:
			order.append(fieldname)
			changed = True

	if not changed:
		return

	name = f"{doctype}-main-field_order"
	if frappe.db.exists("Property Setter", name):
		frappe.db.set_value(
			"Property Setter",
			name,
			{"value": json.dumps(order, indent=1)},
			update_modified=False,
		)
	else:
		frappe.get_doc(
			{
				"doctype": "Property Setter",
				"doc_type": doctype,
				"doctype_or_field": "DocType",
				"field_name": None,
				"property": "field_order",
				"property_type": "Data",
				"value": json.dumps(order, indent=1),
			}
		).insert(ignore_permissions=True)

	frappe.clear_cache(doctype=doctype)
	print(f"{doctype}: field order set, {len(order)} fields ({len(custom_fields)} plate).")
