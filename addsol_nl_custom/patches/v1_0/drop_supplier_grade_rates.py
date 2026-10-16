"""Remove the Supplier Grade Rate table and its Supplier field.

The rate per kg used to be read out of a per-supplier, per-grade table with
validity dates. That tied the price to the supplier's record rather than to the
purchase, and it overwrote whatever the buyer had typed. The rate is now
entered on the Purchase Order line, with the last agreed rate offered when the
line is empty.

The table is dropped here rather than left to the DocType sync, which removes
the metadata but does not reliably remove the physical table.

Runs post-model-sync, after the DocType record has already gone, and is
idempotent: a site that never had the table, or that has already run this, is
left exactly as it is.
"""

import frappe

from addsol_nl_custom.patches import with_developer_mode_restored

TABLE = "Supplier Grade Rate"
CUSTOM_FIELD = "Supplier-custom_grade_rates"


@with_developer_mode_restored
def execute():
	removed = []

	if frappe.db.exists("Custom Field", CUSTOM_FIELD):
		frappe.delete_doc("Custom Field", CUSTOM_FIELD, ignore_permissions=True, force=True)
		removed.append("custom field")

	# Table first, metadata second: if the DocType record is still present when
	# the table goes, a later sync would try to create the table again.
	if frappe.db.table_exists(TABLE):
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{TABLE}`")
		removed.append("table")

	if frappe.db.exists("DocType", TABLE):
		frappe.delete_doc("DocType", TABLE, ignore_permissions=True, force=True)
		removed.append("doctype record")

	print(f"Supplier grade rates removed: {', '.join(removed) or 'nothing to do'}")
