"""Repair Purchase Receipt permissions that the approver patch wiped.

An earlier version of setup_plate_defaults.create_approver_permission added a
single Custom DocPerm row (Plate Weight Approver, permlevel 1) without first
copying the standard DocPerm rows. Frappe ignores a doctype's standard
DocPerm rows entirely once any Custom DocPerm row exists for it -
Meta.set_custom_permissions replaces the whole list - so on every site that
ran that patch, Stock Manager, Stock User, Purchase User and the rest lost
read, write and create on Purchase Receipt, and creating a receipt from a
submitted order failed with "You need the 'create' permission on Purchase
Receipt".

The fix is to copy the standard rows in now, the way the Role Permissions
Manager does the first time a permission is customised. The patch only acts
on the signature this bug leaves behind - custom rows exist but none at
permlevel 0 - so a doctype an admin has since customised properly (the
manager copies every standard row first) is left alone. Only rows whose
(role, permlevel, if_owner) combination is not already present are copied,
so the approver row and any deliberate edits are never overwritten.
Idempotent: once the copies exist, a second run copies nothing.
"""

import frappe

from addsol_nl_custom.patches import with_developer_mode_restored

DOCTYPE = "Purchase Receipt"


@with_developer_mode_restored
def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	custom_rows = frappe.get_all(
		"Custom DocPerm",
		filters={"parent": DOCTYPE},
		fields=["role", "permlevel", "if_owner"],
	)

	# Nothing customised yet: standard DocPerm still rules, nothing to repair.
	# Custom rows with a permlevel 0 entry mean the permissions were customised
	# properly at some point, so the standard rows are not silently missing.
	if not custom_rows or any(row.permlevel == 0 for row in custom_rows):
		print(f"{DOCTYPE}: Custom DocPerm not in the broken state, nothing to repair")
		return

	existing = {(row.role, row.permlevel, row.if_owner) for row in custom_rows}

	copied = 0
	for perm in frappe.get_all(
		"DocPerm",
		filters={"parent": DOCTYPE},
		fields=[
			"role",
			"permlevel",
			"if_owner",
			"read",
			"write",
			"create",
			"delete",
			"submit",
			"cancel",
			"amend",
			"report",
			"export",
			"print",
			"email",
			"import",
			"share",
			"select",
		],
	):
		key = (perm.role, perm.permlevel, perm.if_owner)
		if key in existing:
			continue

		row = frappe.new_doc("Custom DocPerm")
		row.update(perm)
		row.parent = DOCTYPE
		row.parenttype = "DocType"
		row.parentfield = "permissions"
		row.insert(ignore_permissions=True)
		existing.add(key)
		copied += 1

	if copied:
		frappe.clear_cache(doctype=DOCTYPE)
		print(f"{DOCTYPE}: copied {copied} standard permission row(s) into Custom DocPerm")
	else:
		print(f"{DOCTYPE}: standard permissions already present in Custom DocPerm, nothing to copy")
