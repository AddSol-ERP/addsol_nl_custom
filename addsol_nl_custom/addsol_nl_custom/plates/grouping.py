# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Deciding what is a weight-managed item.

There is no "is plate" flag. An Item Group that carries a weight formula is a
weighed grade, and every Item under it is weighed. Anything without one is an
ordinary Item and none of the plate rules touch it.

Kept deliberately generic so the same machinery serves the next product that is
sold per piece but valued per kilo, without any renaming.
"""

import frappe

from addsol_nl_custom.addsol_nl_custom.plates.weight import is_safe_formula


def is_weighed_group(item_group) -> bool:
	"""True when this Item Group really defines a weight formula.

	Presence of the formula alone is not enough - a multiplication factor has
	to be there too. A group cannot be saved with a formula and no MF (the
	Item Group validate refuses it), so requiring both cannot exclude a real
	weighed grade, while it does stop a stray or default formula value from
	turning every Item Group on the site into a plate group.

	Validity is deliberately *not* tested here: a group carrying a broken
	formula is still a weighed group, which is what lets the Item Group
	validation reject that formula.
	"""
	if not item_group:
		return False

	formula, mf = (
		frappe.db.get_value(
			"Item Group",
			item_group,
			["custom_formula", "custom_multiplication_factor"],
			as_dict=True,
		)
		or frappe._dict()
	)

	if not formula or not is_safe_formula(formula):
		return False

	return frappe.utils.flt(mf) > 0


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
