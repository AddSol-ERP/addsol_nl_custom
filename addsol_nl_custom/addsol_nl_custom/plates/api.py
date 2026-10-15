# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Whitelisted helpers the desk forms call."""

import frappe

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
