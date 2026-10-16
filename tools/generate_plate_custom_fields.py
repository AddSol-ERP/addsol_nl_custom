#!/usr/bin/env python3
"""Regenerate the plate Custom Fields in fixtures/custom_field.json.

Run from the app directory:

    python3 ../../../tools/generate_plate_custom_fields.py

The Custom Fields are declared once in FIELD_SPECS below and written out in the
same shape Frappe exports, so they stay editable through the Customize Form UI
after they land. Editing this generator and re-running is how the schema
changes; editing the JSON by hand is not.

The `custom_%` filter already in hooks.py picks all of these up, so nothing
else needs to change when a field is added here.
"""

import json
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(APP_DIR, "addsol_nl_custom", "fixtures", "custom_field.json")

# (dt, fieldname, fieldtype, label, options, extra keys)
FIELD_SPECS = [
	# ---------------------------------------------------------------- C1 Item
	("Item", "custom_is_offcut", "Check", "Is Offcut", None,
	 {"read_only": 1, "description": "Set by the cutting process, not by hand."}),
	("Item", "custom_source_item", "Link", "Source Item", "Item",
	 {"read_only": 1, "depends_on": "eval:doc.custom_is_offcut"}),

	# ------------------------------------------------- C1 Item Group additions
	("Item Group", "custom_min_offcut_length_mm", "Float", "Minimum Offcut Length (mm)", None,
	 {"depends_on": "eval:doc.custom_formula",
	  "description": "Offcuts shorter than this must be booked as scrap. Per grade, because "
	                 "a usable offcut off 2.5 mm plate is not a usable offcut off 25 mm plate. "
	                 "Falls back to Plate Settings when blank."}),
	("Item Group", "custom_min_offcut_width_mm", "Float", "Minimum Offcut Width (mm)", None,
	 {"depends_on": "eval:doc.custom_formula",
	  "description": "Offcuts narrower than this must be booked as scrap. See Minimum "
	                 "Offcut Length. Falls back to Plate Settings when blank."}),

	# ------------------------------------------------------------- C2 Grade opt-in
	("Item Group", "custom_is_weighed_grade", "Check", "Is Weighed Grade", None,
	 {"default": 0, "description": "Opt in. Only a grade ticked here gets plate weights, "
	                 "Nos enforcement, heat numbers, serial and batch stamping, and a "
	                 "rate per kg. A Formula on its own no longer makes a grade a "
	                 "weighed grade, so an unticked grade is an ordinary group."}),

	# ---------------------------------------------- C4 Purchase Order / Item
	("Purchase Order Item", "custom_is_plate", "Check", "Is Plate", None,
	 {"read_only": 1, "hidden": 1, "print_hide": 1}),
	("Purchase Order Item", "custom_rate_per_kg", "Currency", "Rate per Kg", "currency",
	 {"read_only": 0, "in_list_view": 1, "precision": "4", "depends_on": "eval:doc.custom_is_plate",
	  "description": "Entered by the buyer. Nothing overwrites it; an empty line is offered "
	                 "the last rate agreed for this item."}),
	("Purchase Order Item", "custom_unit_weight_kg", "Float", "Theoretical Wt per Plate (Kg)", None,
	 {"read_only": 1, "precision": "3", "depends_on": "eval:doc.custom_is_plate",
	  "fetch_from": "item_code.weight_per_unit", "fetch_if_empty": 1}),
	("Purchase Order Item", "custom_est_weight_kg", "Float", "Estimated Weight (Kg)", None,
	 {"read_only": 1, "precision": "3", "depends_on": "eval:doc.custom_is_plate",
	  "description": "Quantity times the theoretical weight per plate."}),
	("Purchase Order", "custom_total_est_weight_kg", "Float", "Total Estimated Weight (Kg)", None,
	 {"read_only": 1, "precision": "3"}),

	# --------------------------------------------- C4 Purchase Receipt / Item
	("Purchase Receipt Item", "custom_is_plate", "Check", "Is Plate", None,
	 {"read_only": 1, "hidden": 1, "print_hide": 1}),
	("Purchase Receipt Item", "custom_rate_per_kg", "Currency", "Rate per Kg", "currency",
	 {"read_only": 1, "in_list_view": 1, "precision": "4", "depends_on": "eval:doc.custom_is_plate",
	  "description": "Taken from the Purchase Order line. It is not typed here."}),
	("Purchase Receipt Item", "custom_unit_weight_kg", "Float", "Theoretical Wt per Plate (Kg)", None,
	 {"read_only": 1, "precision": "3", "depends_on": "eval:doc.custom_is_plate",
	  "fetch_from": "item_code.weight_per_unit", "fetch_if_empty": 1}),
	("Purchase Receipt Item", "custom_est_weight_kg", "Float", "Estimated Weight (Kg)", None,
	 {"read_only": 1, "precision": "3", "depends_on": "eval:doc.custom_is_plate"}),
	("Purchase Receipt Item", "custom_supplier_weight_kg", "Float", "Supplier Weight (Kg)", None,
	 {"precision": "3", "depends_on": "eval:doc.custom_is_plate",
	  "description": "From the supplier's invoice or challan."}),
	("Purchase Receipt Item", "custom_weighbridge_weight_kg", "Float", "Weighbridge Weight (Kg)", None,
	 {"precision": "3", "depends_on": "eval:doc.custom_is_plate"}),
	("Purchase Receipt Item", "custom_variance_pct", "Percent", "Variance %", None,
	 {"read_only": 1, "depends_on": "eval:doc.custom_is_plate",
	  "description": "Supplier weight against the estimated weight, as a percentage."}),
	("Purchase Receipt Item", "custom_weight_decision", "Select", "Weight Decision", None,
	 {"permlevel": 1, "options": "\nAccept Supplier Weight\nAccept Estimated Weight\n"
	                             "Accept Weighbridge Weight",
	  "depends_on": "eval:doc.custom_variance_pct > doc.__plate_tolerance",
	  "description": "Only shown when the variance is above tolerance. Permlevel 1, so only "
	                 "the approver role may set it."}),
	("Purchase Receipt Item", "custom_billable_weight_kg", "Float", "Accepted Weight (Kg)", None,
	 {"read_only": 1, "in_list_view": 1, "precision": "3", "depends_on": "eval:doc.custom_is_plate"}),
	("Purchase Receipt Item", "custom_weight_per_plate_kg", "Float", "Weight per Plate (Kg)", None,
	 {"read_only": 1, "precision": "3", "depends_on": "eval:doc.custom_is_plate"}),
	("Purchase Receipt Item", "custom_heat_number", "Data", "Heat Number", None,
	 {"depends_on": "eval:doc.custom_is_plate",
	  "description": "One receipt line is one heat number."}),
	("Purchase Receipt Item", "custom_mtc_no", "Data", "MTC No", None,
	 {"depends_on": "eval:doc.custom_is_plate", "description": "Mill test certificate number."}),
	("Purchase Receipt", "custom_total_est_weight_kg", "Float", "Total Estimated Weight (Kg)", None,
	 {"read_only": 1, "precision": "3"}),
	("Purchase Receipt", "custom_total_billable_weight_kg", "Float", "Total Accepted Weight (Kg)", None,
	 {"read_only": 1, "precision": "3"}),

	# ------------------------------------------ C4 Purchase Invoice / Item
	("Purchase Invoice Item", "custom_is_plate", "Check", "Is Plate", None,
	 {"read_only": 1, "hidden": 1, "print_hide": 1}),
	("Purchase Invoice Item", "custom_rate_per_kg", "Currency", "Rate per Kg", "currency",
	 {"read_only": 1, "precision": "4", "depends_on": "eval:doc.custom_is_plate"}),
	("Purchase Invoice Item", "custom_billable_weight_kg", "Float", "Accepted Weight (Kg)", None,
	 {"read_only": 1, "precision": "3", "depends_on": "eval:doc.custom_is_plate"}),
	("Purchase Invoice Item", "custom_weight_per_plate_kg", "Float", "Weight per Plate (Kg)", None,
	 {"read_only": 1, "precision": "3", "depends_on": "eval:doc.custom_is_plate"}),
	("Purchase Invoice Item", "custom_heat_number", "Data", "Heat Number", None,
	 {"depends_on": "eval:doc.custom_is_plate"}),
	("Purchase Invoice", "custom_total_billable_weight_kg", "Float", "Total Accepted Weight (Kg)", None,
	 {"read_only": 1, "precision": "3"}),

	# ------------------------------------------------------------------ C5 Batch
	("Batch", "custom_heat_number", "Data", "Heat Number", None,
	 {"in_list_view": 1, "in_standard_filter": 1, "search_index": 1}),
	("Batch", "custom_mtc_no", "Data", "MTC No", None, {}),
	("Batch", "custom_grade", "Link", "Grade", "Item Group", {"in_standard_filter": 1}),
	("Batch", "custom_weight_per_plate_kg", "Float", "Weight per Plate (Kg)", None,
	 {"precision": "3"}),
	("Batch", "custom_cost_per_kg", "Currency", "Cost per Kg", "currency", {"precision": "4"}),
	("Batch", "custom_actual_to_theoretical_ratio", "Float", "Actual / Theoretical Ratio", None,
	 {"precision": "4", "description": "Weight per plate divided by theoretical weight per plate."}),
	("Batch", "custom_source_batch", "Link", "Source Batch", "Batch", {}),

	# --------------------------------------------------------------- C5 Serial
	("Serial No", "custom_weight_kg", "Float", "Weight (Kg)", None,
	 {"in_list_view": 1, "precision": "3"}),
	("Serial No", "custom_heat_number", "Data", "Heat Number", None,
	 {"fetch_from": "batch_no.custom_heat_number", "fetch_if_empty": 1}),
	("Serial No", "custom_source_serial_no", "Link", "Source Serial No", "Serial No", {}),

	# ----------------------------------------------- C6 Stock Entry Detail
	("Stock Entry Detail", "custom_cutting_record", "Link", "Cutting Record", "Plate Cutting Record",
	 {"read_only": 1,
	  "description": "Set by the offcut hooks on Manufacture rows that carry a plate "
	                 "cutting record's offcuts or scrap. Used to follow the stock "
	                 "entry back onto the record."}),
]

# Insert position for each custom field, so they land in a sensible place in the
# existing section rather than at the bottom of the form.
INSERT_AFTER = {
	("Item", "custom_is_offcut"): "custom_width_mm",
	("Item", "custom_source_item"): "custom_is_offcut",
	("Item Group", "custom_is_weighed_grade"): "custom_formula",
	("Item Group", "custom_min_offcut_length_mm"): "custom_serial_no_series",
	("Item Group", "custom_min_offcut_width_mm"): "custom_min_offcut_length_mm",
	("Purchase Order Item", "custom_is_plate"): "rate",
	("Purchase Order Item", "custom_rate_per_kg"): "qty",
	("Purchase Order Item", "custom_unit_weight_kg"): "custom_rate_per_kg",
	("Purchase Order Item", "custom_est_weight_kg"): "custom_unit_weight_kg",
	("Purchase Order", "custom_total_est_weight_kg"): "total_net_weight",
	("Purchase Receipt Item", "custom_is_plate"): "rate",
	("Purchase Receipt Item", "custom_rate_per_kg"): "rate",
	("Purchase Receipt Item", "custom_unit_weight_kg"): "custom_rate_per_kg",
	("Purchase Receipt Item", "custom_est_weight_kg"): "custom_unit_weight_kg",
	("Purchase Receipt Item", "custom_supplier_weight_kg"): "custom_est_weight_kg",
	("Purchase Receipt Item", "custom_weighbridge_weight_kg"): "custom_supplier_weight_kg",
	("Purchase Receipt Item", "custom_variance_pct"): "custom_weighbridge_weight_kg",
	("Purchase Receipt Item", "custom_weight_decision"): "custom_variance_pct",
	("Purchase Receipt Item", "custom_billable_weight_kg"): "custom_weight_decision",
	("Purchase Receipt Item", "custom_weight_per_plate_kg"): "custom_billable_weight_kg",
	("Purchase Receipt Item", "custom_heat_number"): "custom_weight_per_plate_kg",
	("Purchase Receipt Item", "custom_mtc_no"): "custom_heat_number",
	("Purchase Receipt", "custom_total_est_weight_kg"): "custom_total_billable_weight_kg",
	("Purchase Receipt", "custom_total_billable_weight_kg"): "total_net_weight",
	("Purchase Invoice Item", "custom_is_plate"): "rate",
	("Purchase Invoice Item", "custom_rate_per_kg"): "custom_is_plate",
	("Purchase Invoice Item", "custom_billable_weight_kg"): "custom_rate_per_kg",
	("Purchase Invoice Item", "custom_weight_per_plate_kg"): "custom_billable_weight_kg",
	("Purchase Invoice Item", "custom_heat_number"): "custom_weight_per_plate_kg",
	("Purchase Invoice", "custom_total_billable_weight_kg"): "total_net_weight",
	("Batch", "custom_heat_number"): "manufacturing_date",
	("Batch", "custom_mtc_no"): "custom_heat_number",
	("Batch", "custom_grade"): "custom_mtc_no",
	("Batch", "custom_weight_per_plate_kg"): "custom_grade",
	("Batch", "custom_cost_per_kg"): "custom_weight_per_plate_kg",
	("Batch", "custom_actual_to_theoretical_ratio"): "custom_cost_per_kg",
	("Batch", "custom_source_batch"): "custom_actual_to_theoretical_ratio",
	("Serial No", "custom_weight_kg"): "batch_no",
	("Serial No", "custom_heat_number"): "custom_weight_kg",
	("Serial No", "custom_source_serial_no"): "custom_heat_number",
	("Stock Entry Detail", "custom_cutting_record"): "is_scrap_item",
}

# Fields this app shipped once and must never come back. Taking a row out of
# FIELD_SPECS is not enough to drop one: main() carries every field it does not
# manage over from the existing fixture, so a removed row would be preserved
# forever. This list is the only thing that actually deletes it.
REMOVED = {
	("Supplier", "custom_grade_rates"),
}

BOOLEAN_KEYS = {
	"bold", "collapsible", "hidden", "hide_days", "hide_border", "hide_seconds",
	"ignore_user_permissions", "ignore_xss_filter", "in_global_search", "in_list_view",
	"in_standard_filter", "in_preview", "is_system_generated", "is_virtual",
	"no_copy", "non_negative", "permlevel", "print_hide", "print_hide_if_no_value",
	"read_only", "report_hide", "reqd", "search_index", "show_dashboard", "translatable",
	"unique", "allow_on_submit", "allow_in_quick_entry", "columns", "fetch_if_empty",
}

TEXT_KEYS = {
	"default", "depends_on", "description", "fetch_from", "fieldname", "fieldtype",
	"insert_after", "label", "link_filters", "mandatory_depends_on", "options",
	"placeholder", "precision", "print_width", "read_only_depends_on",
	"collapsible_depends_on", "width",
}


def build_field(dt, fieldname, fieldtype, label, options, extra):
	# Blank every key first, then set this field's own values. Anything named in
	# the dict literal has to be applied after the loops, or the loops wipe it.
	field = {"doctype": "Custom Field", "docstatus": 0, "module": None}
	for key in BOOLEAN_KEYS:
		field[key] = 0
	for key in TEXT_KEYS:
		field[key] = None

	field.update({
		"dt": dt,
		"fieldname": fieldname,
		"fieldtype": fieldtype,
		"label": label,
		"name": f"{dt}-{fieldname}",
		"options": options,
		"insert_after": INSERT_AFTER.get((dt, fieldname)),
	})

	for key, value in extra.items():
		if key in BOOLEAN_KEYS or key in TEXT_KEYS:
			field[key] = value
		else:
			raise ValueError(f"{dt}-{fieldname}: unknown key {key!r}")

	return field


def main():
	with open(FIXTURE) as f:
		existing = json.load(f)

	# Keep everything this app shipped before, plus the hand-tuned Item Group
	# fields, and replace only the plate ones this generator owns.
	hand_tuned = {
		("Item", "custom_thickness_dropdown"),
		("Item", "custom_length_mm"),
		("Item", "custom_width_mm"),
		("Item", "custom_estimated_weight"),
		("Item Group", "custom_formula"),
		("Item Group", "custom_multiplication_factor"),
		("Item Group", "custom_batch_number_series"),
		("Item Group", "custom_serial_no_series"),
	}
	managed = {(dt, fn) for dt, fn, *_ in FIELD_SPECS}

	kept = [
		f
		for f in existing
		if (f["dt"], f["fieldname"]) not in REMOVED
		and ((f["dt"], f["fieldname"]) in hand_tuned or (f["dt"], f["fieldname"]) not in managed)
	]
	kept.extend(build_field(*spec) for spec in FIELD_SPECS)
	kept.sort(key=lambda f: (f["dt"], f["fieldname"]))

	with open(FIXTURE, "w") as f:
		json.dump(kept, f, indent=1, ensure_ascii=False, sort_keys=True)
		f.write("\n")

	print(f"custom_field.json: {len(kept)} entries ({len(FIELD_SPECS)} generated by this tool)")


if __name__ == "__main__":
	main()
