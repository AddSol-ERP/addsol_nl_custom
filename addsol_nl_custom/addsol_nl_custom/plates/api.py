# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Whitelisted helpers the desk forms call."""

import frappe

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
