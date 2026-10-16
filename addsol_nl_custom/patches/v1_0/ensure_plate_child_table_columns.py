"""Repair child-table links if a DocType was first installed as a regular table.

Plate Cutting Offcut was initially shipped without ``istable``. Once marked as a
child table, Frappe metadata expects the standard parent link columns. This
post-model-sync patch fills any columns that an existing site's schema sync did
not add.

The name of a DocType that no longer exists is left alone on purpose: the table
is dropped by drop_supplier_grade_rates, and this patch may still run on a site
where the drop has happened but the table has not been cleaned up yet.
"""

import frappe

from addsol_nl_custom.patches import with_developer_mode_restored

CHILD_TABLES = ("Plate Cutting Offcut",)
PARENT_COLUMNS = {
	"parent": "varchar(140)",
	"parenttype": "varchar(140)",
	"parentfield": "varchar(140)",
}


@with_developer_mode_restored
def execute():
	for doctype in CHILD_TABLES:
		if not frappe.db.table_exists(doctype):
			continue

		for column, fieldtype in PARENT_COLUMNS.items():
			if not frappe.db.has_column(doctype, column):
				# Frappe's MariaDBDatabase adapter in this deployment does not
				# expose add_column; these identifiers come only from constants above.
				frappe.db.sql(f"ALTER TABLE `tab{doctype}` ADD COLUMN `{column}` {fieldtype}")
				print(f"Added missing {column} column to {doctype}")
