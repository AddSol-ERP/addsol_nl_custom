# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Whitelisted helpers the desk forms call."""

import frappe

from addsol_nl_custom.addsol_nl_custom.finished_goods import groups, naming


@frappe.whitelist(allow_guest=False)
def get_finished_good_info(item_group=None, item_code=None) -> dict:
	"""What the forms need to know about a finished good.

	Two questions in one call: is this a group that holds finished goods, and
	which Project does this item belong to. The Item form uses the first to
	lock the code and ask for the Project; the Sales Order uses the second to
	put the item's Project onto the row.

	Nothing here decides anything. The rules are the server's: this only
	answers what the form should show, so the user is not asked for a code
	that is going to be replaced.
	"""
	is_finished_good = False

	if item_group:
		is_finished_good = groups.is_finished_good_group(item_group)
	elif item_code:
		is_finished_good = groups.is_finished_good_item(item_code)

	project = None
	if item_code and naming.project_field_exists():
		project = frappe.db.get_value("Item", item_code, "custom_project")

	return {
		"is_finished_good": is_finished_good,
		"project": project,
		"group": groups.FINISHED_GOOD_GROUP,
	}
