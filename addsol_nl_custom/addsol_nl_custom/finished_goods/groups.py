# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Deciding what is a finished good.

A finished good is an Item in the Item Group named "Finished Goods", or in any
Item Group nested under it. The group is the gate, by name, because the
customer decides which group holds the products they make - there is no flag
to tick and no field to fill in, and nothing else in the app has to know.

The nested case matters: a customer who makes several kinds of product will
put "Finished Goods - Tanks" and "Finished Goods - Panels" under the group, and
an Item in either of them is a finished good. So the test is not "is this
group called Finished Goods" but "does this group's parent chain reach it".
"""

import frappe

# The Item Group that holds finished goods. Everything under it counts too.
FINISHED_GOOD_GROUP = "Finished Goods"


def finished_good_groups() -> set[str]:
	"""Every Item Group that is the Finished Goods group or sits under it.

	One query for the whole tree, then a walk. The result is deliberately NOT
	cached: a cached copy would go stale inside a request that creates the
	group and then uses it, and it would go stale across the test suite,
	where frappe.local survives from one test to the next. The table is a few
	dozen rows, and this is read once per rule that needs the answer.
	"""
	parents = {
		row.name: row.parent_item_group
		for row in frappe.get_all("Item Group", fields=["name", "parent_item_group"])
	}

	if FINISHED_GOOD_GROUP not in parents:
		return set()

	children: dict[str, list[str]] = {}
	for name, parent in parents.items():
		children.setdefault(parent, []).append(name)

	found: set[str] = set()
	pending = [FINISHED_GOOD_GROUP]

	while pending:
		current = pending.pop()
		if current in found:
			continue
		found.add(current)
		pending.extend(children.get(current, []))

	return found


def is_finished_good_group(item_group, known: set[str] | None = None) -> bool:
	"""Whether an Item Group holds finished goods.

	`known` is the set `finished_good_groups` returned, for a caller that has
	already got it and is asking about several groups.
	"""
	if not item_group:
		return False

	groups = known if known is not None else finished_good_groups()
	return item_group in groups


def is_finished_good_item(item, known: set[str] | None = None) -> bool:
	"""Whether an Item sits in a finished-goods Item Group.

	Accepts an Item document or anything with an item_group key.
	"""
	if not item:
		return False

	if isinstance(item, str):
		item_group = frappe.db.get_value("Item", item, "item_group")
	else:
		item_group = frappe._dict(item).get("item_group")

	return is_finished_good_group(item_group, known)
