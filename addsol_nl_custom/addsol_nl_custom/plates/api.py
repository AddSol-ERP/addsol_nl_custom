# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Whitelisted helpers the desk forms call."""

import frappe

from addsol_nl_custom.addsol_nl_custom.plates import cutting
from addsol_nl_custom.addsol_nl_custom.plates.settings import get_setting
from addsol_nl_custom.addsol_nl_custom.plates.weight import compute_theoretical_weight


@frappe.whitelist()
def get_theoretical_weight(
	item_group=None, thickness=None, thickness_mm=None, length_mm=None, width_mm=None
) -> float:
	"""Preview the theoretical weight of one piece while the Item form is open.

	public/js/item.js calls this whenever the grade or a dimension changes and
	shows the result in the read-only custom_estimated_weight field. The same
	calculation runs on save in item_hooks.set_estimated_weight; this one is
	only for the preview.

	Pass thickness as the Thickness record name - the browser must not turn a
	link value into a number, or the two paths would disagree.
	"""
	if thickness_mm is None and thickness:
		thickness_mm = frappe.db.get_value("Thickness", thickness, "thickness_mm")

	return compute_theoretical_weight(
		item_group=item_group,
		thickness_mm=thickness_mm,
		length_mm=length_mm,
		width_mm=width_mm,
	)


@frappe.whitelist(allow_guest=False)
def estimate_offcut_weights(source_serial_no, rows, scrap_weight_kg=0) -> dict:
	"""Preview every offcut's weight and the cutting's total while the form is open.

	public/js/plate_cutting_record.js asks for this whenever a dimension, the
	scrap weight or a row changes. It runs the same three functions the save
	will run - cutting.get_offcut_details, cutting.compute_offcut and
	cutting.offcut_totals - so the preview is not a second implementation that
	can drift; it is the same arithmetic, asked for earlier. The save keeps the
	say, and this deliberately does not reject a cutting that runs over - it
	reports over_by_kg and lets the operator decide.

	`rows` is the offcut lines as JSON: [{"name", "length_mm", "width_mm"}].
	Each line's `name` is echoed straight back, so a reply that lands after the
	operator has typed again is recognised and dropped instead of being written
	onto the wrong row.

	A line with a length but no width yet returns zeroes rather than asking for
	the weight of a zero-size plate, which the formula refuses to guess. That
	line is simply not drawn yet; the save rejects it properly through
	check_offcut_fits, as it always has.
	"""
	frappe.has_permission("Plate Cutting Record", "write", throw=True)

	details = cutting.get_offcut_details(source_serial_no)
	weights: list[float] = []
	values: list[float] = []
	previewed: list[dict] = []

	for line in frappe.parse_json(rows) or []:
		line = frappe._dict(line)
		estimate = {"name": line.get("name")}

		if frappe.utils.flt(line.length_mm) > 0 and frappe.utils.flt(line.width_mm) > 0:
			row = frappe._dict({"length_mm": line.length_mm, "width_mm": line.width_mm})
			cutting.compute_offcut(row, details)
			estimate.update(
				theoretical_weight_kg=row.theoretical_weight_kg,
				weight_kg=row.weight_kg,
				value=row.value,
			)
		else:
			estimate.update(theoretical_weight_kg=0.0, weight_kg=0.0, value=0.0)

		previewed.append(estimate)
		weights.append(estimate["weight_kg"])
		values.append(estimate["value"])

	totals = cutting.offcut_totals(
		source_weight_kg=details["weight"],
		scrap_weight_kg=scrap_weight_kg,
		row_weights=weights,
		row_values=values,
		cost_per_kg=details["cost_per_kg"],
	)

	return {
		"source_weight_kg": totals["source_weight_kg"],
		"rows": previewed,
		"total_offcut_weight_kg": totals["total_offcut_weight_kg"],
		"total_offcut_value": totals["total_offcut_value"],
		"scrap_value": totals["scrap_value"],
		"consumed_weight_kg": totals["consumed_weight_kg"],
		"over_by_kg": totals["over_by_kg"],
	}


@frappe.whitelist()
def get_cutting_operation():
	"""The Operation that should offer the Record Cutting button, if any."""
	return get_setting("cutting_operation")


@frappe.whitelist(allow_guest=False)
def get_plate_settings():
	"""Return plate-receipt UI capabilities for the signed-in user."""
	approver_role = get_setting("approver_role")
	user_roles = frappe.get_roles()
	return {
		"weight_tolerance_pct": get_setting("weight_tolerance_pct", 10),
		"enable_weight_based_purchasing": bool(get_setting("enable_weight_based_purchasing", 0)),
		"can_decide_weight": not approver_role or approver_role in user_roles,
		"cutting_operation": get_setting("cutting_operation"),
	}


@frappe.whitelist(allow_guest=False)
def is_weight_managed_item(item_code=None):
	"""Tell the purchase forms whether to show weight pricing for an Item."""
	if not item_code or not get_setting("enable_weight_based_purchasing", 0):
		return False

	from addsol_nl_custom.addsol_nl_custom.plates.grouping import is_weighed_item

	return bool(is_weighed_item(item_code))


@frappe.whitelist(allow_guest=False)
def get_last_rate(item_code=None, supplier=None) -> float:
	"""Offer the last rate per kg agreed for an Item when a line is still empty.

	Only ever a starting point. The desk calls this as the buyer picks an item
	or a supplier, and the client is written to fill the field only when it has
	not been typed into - a rate somebody entered is never replaced by this.
	"""
	if not item_code:
		return 0.0

	from addsol_nl_custom.addsol_nl_custom.plates.rate_history import last_rate

	return last_rate(item_code, supplier)
