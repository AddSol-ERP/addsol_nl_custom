"""Create the Finished Goods Item Group if the site has none.

The group is what marks an Item as a finished good, so a site without one has
the rule switched off rather than broken: nothing is named, nothing is
refused, and ordinary purchasing is unaffected.

Idempotent throughout. A group that already exists is never touched, whoever
made it and whatever shape it has - a customer who has put their own
"Finished Goods" group in place keeps it exactly as it is.
"""

import frappe

from addsol_nl_custom.addsol_nl_custom.finished_goods.groups import FINISHED_GOOD_GROUP
from addsol_nl_custom.patches import with_developer_mode_restored


@with_developer_mode_restored
def execute():
	if frappe.db.exists("Item Group", FINISHED_GOOD_GROUP):
		print(f"Item Group already exists: {FINISHED_GOOD_GROUP} - nothing to do.")
		return

	frappe.get_doc(
		{
			"doctype": "Item Group",
			"item_group_name": FINISHED_GOOD_GROUP,
			"parent_item_group": "All Item Groups",
			# A parent, so the customer can hang "Finished Goods - Tanks" and
			# the like under it. An Item may sit in a group either way, and
			# the rule reads the whole branch below this group.
			"is_group": 1,
		}
	).insert(ignore_permissions=True)

	print(f"Created Item Group: {FINISHED_GOOD_GROUP}")
