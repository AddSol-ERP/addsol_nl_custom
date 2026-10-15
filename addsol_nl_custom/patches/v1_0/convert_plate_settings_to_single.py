"""Move the existing Plate Settings record into Frappe's Single storage."""

import frappe

LAYOUT_FIELD_TYPES = {
	"Section Break",
	"Column Break",
	"Tab Break",
	"HTML",
	"Heading",
}


def execute():
	if not frappe.db.table_exists("Plate Settings"):
		return

	rows = frappe.get_all(
		"Plate Settings",
		fields=["*"],
		order_by="modified desc",
		limit_page_length=2,
	)
	if len(rows) > 1:
		names = ", ".join(row.name for row in rows)
		frappe.throw(
			"Plate Settings is being converted to a Single DocType, but multiple records "
			f"exist ({names}). Resolve them into one record, then run migrate again."
		)
	if not rows:
		return

	row = rows[0]
	meta = frappe.get_meta("Plate Settings")
	for field in meta.fields:
		if field.fieldtype in LAYOUT_FIELD_TYPES or not field.fieldname:
			continue
		value = row.get(field.fieldname)
		if value is not None:
			frappe.db.set_single_value("Plate Settings", field.fieldname, value)
