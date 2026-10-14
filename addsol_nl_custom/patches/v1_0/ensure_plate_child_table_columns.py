"""Repair child-table links if a DocType was first installed as a regular table.

Supplier Grade Rate and Plate Cutting Offcut were initially shipped without
``istable``. Once marked as child tables, Frappe metadata expects the standard
parent link columns. This post-model-sync patch fills any columns that an
existing site's schema sync did not add.
"""

import frappe


CHILD_TABLES = ("Supplier Grade Rate", "Plate Cutting Offcut")
PARENT_COLUMNS = {
	"parent": "varchar(140)",
	"parenttype": "varchar(140)",
	"parentfield": "varchar(140)",
}


def execute():
	for doctype in CHILD_TABLES:
		if not frappe.db.table_exists(doctype):
			continue

		for column, fieldtype in PARENT_COLUMNS.items():
			if not frappe.db.has_column(doctype, column):
				frappe.db.add_column(doctype, column, fieldtype)
				print(f"Added missing {column} column to {doctype}")
