# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""The finished-goods rule on the Sales Order.

A finished good is made for one Project, and it can only be sold against that
Project. The order therefore has to carry the same Project as the item, and a
mismatch is refused rather than reported: a finished good booked against the
wrong project is a finished good the project reports will not find, and the
report is what the customer reads.

Legacy is left alone. A finished good that carries no Project was made before
this rule existed, so there is nothing to match it against and it keeps
working.
"""

import frappe
from frappe import _

from addsol_nl_custom.addsol_nl_custom.finished_goods import groups, naming


def sales_order_validate(doc, method):
	"""Refuse a finished good that is booked against another Project."""
	rows = [row for row in (doc.get("items") or []) if row.get("item_code")]
	if not rows:
		return

	if frappe.flags.in_import:
		# An import is a deliberate bulk operation over a file somebody
		# prepared, and a file cannot answer a question about a Project. The
		# rule stands down for it, exactly as it does on the Item.
		return

	known = groups.finished_good_groups()
	if not known:
		return

	if not naming.project_field_exists():
		return

	items = _items_by_code([row.item_code for row in rows])

	for row in rows:
		item = items.get(row.item_code)
		if not item or item.item_group not in known:
			continue

		item_project = (item.get("custom_project") or "").strip()
		if not item_project:
			# A finished good made before this rule. It carries no Project, so
			# there is nothing to match it against.
			continue

		order_project = (row.get("project") or doc.get("project") or "").strip()

		if not order_project:
			frappe.throw(
				_(
					"Row {0}: {1} is a finished good for project {2}. Set that Project on this order, or on the row, before saving."
				).format(row.get("idx"), row.item_code, item_project),
				title=_("Finished good needs its Project"),
			)

		if order_project != item_project:
			frappe.throw(
				_(
					"Row {0}: {1} is a finished good for project {2}, but this order is for project {3}. One finished good belongs to one Project."
				).format(row.get("idx"), row.item_code, item_project, order_project),
				title=_("Finished good booked against another Project"),
			)


def _items_by_code(codes) -> dict:
	"""The items on this order, read in one query.

	One query for the whole grid rather than one per row: an order with
	twenty lines should not turn into twenty round trips.
	"""
	fields = ["name", "item_group"]
	if naming.project_field_exists():
		fields.append("custom_project")

	rows = frappe.get_all(
		"Item",
		filters={"name": ["in", list(set(codes))]},
		fields=fields,
	)

	return {row.name: row for row in rows}
