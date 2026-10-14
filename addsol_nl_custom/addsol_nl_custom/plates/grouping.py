# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Deciding what is a weight-managed item.

There is no "is plate" flag. An Item Group that carries a weight formula and a
multiplication factor is a weighed grade, and every Item under it is weighed.
Anything without a formula is an ordinary Item and none of the plate rules
touch it.

Kept deliberately generic so the same machinery serves the next product that
is sold per piece but valued per kilo, without any renaming.
"""

import frappe


def is_weighed_group(item_group) -> bool:
	"""True when this Item Group defines a weight formula.

	Presence of the formula is the test, not its validity - a group carrying a
	broken formula is still a weighed group, which is what lets the Item Group
	validation reject that formula.
	"""
	if not item_group:
		return False

	return bool(
		frappe.db.get_value(
			"Item Group",
			item_group,
			"custom_formula",
			cache=True,
		)
	)


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
