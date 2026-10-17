"""Remove the old Job Card cutting flow and its two DocTypes.

The cutting of a plate is now a standalone Plate Offcut: no Work Order, no
Job Card, no WIP warehouse, no Manufacture-entry hooks. Plate Cutting Record
and Plate Cutting Offcut went with it - this was still a local experiment, so
there is no production data to preserve.

What this patch does not do is drop the DB column left behind by the
Stock Entry Detail.custom_cutting_record Custom Field: Frappe never drops
columns on field removal. After this has run, an operator who wants the
column gone runs ``bench --site <site> trim-tables``.

Runs post-model-sync, before migrate's own orphan-DocType sweep, and is
idempotent: a site that never had the old flow, or that has already run this,
is left exactly as it is.
"""

import frappe

from addsol_nl_custom.patches import with_developer_mode_restored

CUSTOM_FIELD = "Stock Entry Detail-custom_cutting_record"
# Child table before parent, though nothing here cascades either way.
DOCTYPES = ("Plate Cutting Offcut", "Plate Cutting Record")


@with_developer_mode_restored
def execute():
	removed = []

	# The Link-type Custom Field is not swept away with its DocType (only
	# Table-typed ones are), and the fixture that used to ship it has been
	# regenerated without it - so delete the record here, once.
	if frappe.db.exists("Custom Field", CUSTOM_FIELD):
		frappe.delete_doc("Custom Field", CUSTOM_FIELD, ignore_permissions=True, force=True)
		removed.append("custom field")

	# Table first, metadata second: if the DocType record were still present
	# when the table went, a later sync could try to create the table again.
	for doctype in DOCTYPES:
		if frappe.db.table_exists(doctype):
			frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{doctype}`")
			removed.append(f"table {doctype}")

	for doctype in DOCTYPES:
		if frappe.db.exists("DocType", doctype):
			frappe.delete_doc("DocType", doctype, ignore_permissions=True, force=True)
			removed.append(f"doctype {doctype}")

	print(f"Old cutting flow removed: {', '.join(removed) or 'nothing to do'}")
