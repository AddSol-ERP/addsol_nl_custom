# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Deciding what is a weight-managed item.

A grade has to say so. Item Group.custom_is_weighed_grade is the gate: a group
that carries a Formula is only a weighed grade once that flag is ticked, and
every Item under a weighed grade is weighed. Anything else is an ordinary Item
and none of the plate rules touch it.

Kept deliberately generic so the same machinery serves the next product that is
sold per piece but valued per kilo, without any renaming.
"""

import frappe

from addsol_nl_custom.addsol_nl_custom.plates.weight import is_safe_formula

WEIGHED_GRADE_FLAG = "custom_is_weighed_grade"


def is_weighed_group(item_group) -> bool:
	"""True when this Item Group has opted in and can actually be weighed.

	The flag alone is not enough - a multiplication factor has to be there too,
	and the formula has to be one we can evaluate. A group cannot be saved with
	the flag on and an unusable formula (item_group_validate refuses it), so
	requiring all three cannot exclude a real weighed grade, while it does stop
	a half-configured one from quietly pricing documents.

	Validity is deliberately *not* tested here: a group carrying a broken
	formula is still a weighed group, which is what lets the Item Group
	validation reject that formula.
	"""
	if not item_group:
		return False

	group = frappe.db.get_value(
		"Item Group",
		item_group,
		[WEIGHED_GRADE_FLAG, "custom_formula", "custom_multiplication_factor"],
		as_dict=True,
	)
	group = group or frappe._dict()

	if not group.get(WEIGHED_GRADE_FLAG):
		return False

	formula = group.custom_formula
	if not formula or not is_safe_formula(formula):
		return False

	return frappe.utils.flt(group.custom_multiplication_factor) > 0


def is_weighed_item(item) -> bool:
	"""True when this Item sits under a weighed Item Group.

	Accepts an Item document or anything with an item_group key.
	"""
	if not item:
		return False

	if isinstance(item, str):
		item_group = frappe.db.get_value("Item", item, "item_group")
	else:
		item_group = frappe._dict(item).get("item_group")

	return is_weighed_group(item_group)
