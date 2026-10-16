"""Add the two plate columns to the live MPO Format print format.

The fixture is the source of truth: fixture import runs with force=True after
the patch phases of every migrate, so whatever this patch writes to a live
record is replaced by the fixture's copy minutes later. `print_format.json`
therefore ships the columns in its format_data, and this patch exists for
layouts that are not the shipped one - run it by hand with
`bench --site <site> run-patch addsol_nl_custom.patches.v1_0.add_plate_columns_to_mpo_format --force`
against a customized layout, remembering that the next migrate's fixture
import overwrites that layout with the shipped one.

This only ever appends. If a column is already there it is left alone, and
nothing is reordered or deleted, so running it twice changes nothing the
second time.

MPO Format stores its layout in `format_data`, the Print Format Builder shape:
a JSON document of sections, each with columns of fields, and the items table
carrying its own `table_columns`.
"""

import json

import frappe

from addsol_nl_custom.patches import with_developer_mode_restored

PRINT_FORMAT = "MPO Format"

# (fieldname, label, fieldtype, width)
NEW_COLUMNS = [
	("custom_rate_per_kg", "Rate per Kg", "Currency", 12),
	("custom_est_weight_kg", "Est. Weight (Kg)", "Float", 14),
]

ITEMS_FIELD = "items"
ITEMS_TABLE = "Purchase Order Item"


@with_developer_mode_restored
def execute():
	if not frappe.db.exists("Print Format", PRINT_FORMAT):
		print(f"{PRINT_FORMAT}: not on this site, skipped.")
		return

	pf = frappe.get_doc("Print Format", PRINT_FORMAT)

	if not pf.format_data:
		frappe.throw(
			f"{PRINT_FORMAT} has no format_data on this site. It is a Print Format Builder "
			"layout and this patch does not guess at one built some other way. Add the "
			"columns by hand: Rate per Kg (custom_rate_per_kg) and Est. Weight (Kg) "
			"(custom_est_weight_kg) on the items table.",
			title="Cannot edit this print format automatically",
		)

	layout = json.loads(pf.format_data)

	if not add_columns(layout):
		print(f"{PRINT_FORMAT}: both columns already present, nothing changed.")
		return

	# Compact separators, the shape the Print Format Builder itself writes.
	pf.format_data = json.dumps(layout, separators=(",", ":"))
	pf.save(ignore_permissions=True)
	print(f"{PRINT_FORMAT}: added {[c[1] for c in NEW_COLUMNS]} to the {ITEMS_TABLE} table.")


def add_columns(layout) -> bool:
	"""Append the missing columns. Returns whether anything was added."""
	table = find_items_table(layout)
	if not table:
		frappe.throw(
			f"{PRINT_FORMAT} has no {ITEMS_TABLE} table to add columns to.",
			title="Items table not found",
		)

	columns = table.setdefault("table_columns", [])
	existing = {column.get("fieldname") for column in columns}

	added = False
	for fieldname, label, fieldtype, width in NEW_COLUMNS:
		if fieldname in existing:
			continue
		columns.append(
			{
				"label": label,
				"fieldname": fieldname,
				"fieldtype": fieldtype,
				"options": "currency" if fieldtype == "Currency" else None,
				"width": width,
			}
		)
		added = True

	return added


def find_items_table(layout) -> dict | None:
	"""The layout node holding the Purchase Order Item table."""

	def visit(node):
		if isinstance(node, dict):
			if node.get("fieldname") == ITEMS_FIELD and node.get("options") == ITEMS_TABLE:
				return node
			for value in node.values():
				found = visit(value)
				if found:
					return found
		elif isinstance(node, list):
			for value in node:
				found = visit(value)
				if found:
					return found
		return None

	return visit(layout)
