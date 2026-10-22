"""Publish the Plate Offcut Register report.

The offcut pieces a cutting produces are stock of their own, and they are
reported by their own report. Until this patch runs the site has no
`Plate Offcut Register` record, so the SPA's tile for it resolves to false and
simply does not appear -- the report is invisible rather than broken, which is
the right failure mode but still needs the record to exist.

The record must be STANDARD (`is_standard: "Yes"`), because the report's
`execute()` lives in this app's Python module. A non-standard Script Report is
compiled from the database `report_script` column, and an empty one raises
`TypeError: Not allowed source type: "NoneType"` the moment the report is
opened. This is the same trap `mark_plate_reports_standard` exists for.

`ref_doctype` is `Serial No` for the same reason as the plate register: the
report counts active serial numbers, and the SPA re-applies row-level security
on that doctype when it runs the report.

Idempotent: re-running it re-asserts the same values and creates nothing a
second time.
"""

import frappe

from addsol_nl_custom.patches import with_developer_mode_restored

REPORT_NAME = "Plate Offcut Register"

ROLES = (
	"Stock User",
	"Stock Manager",
	"Manufacturing User",
	"Manufacturing Manager",
	"Accounts User",
	"Accounts Manager",
	"Purchase User",
	"System Manager",
)

# (fieldname, fieldtype, label, options)
FILTERS = (
	("grade", "Link", "Grade", "Item Group"),
	("thickness", "Link", "Thickness", "Thickness"),
	("item", "Link", "Item", "Item"),
	("warehouse", "Link", "Warehouse", "Warehouse"),
	("heat_number", "Data", "Heat Number", None),
	("batch", "Link", "Source Batch", "Batch"),
)


@with_developer_mode_restored
def execute():
	if not frappe.db.table_exists("Report"):
		return

	if frappe.db.exists("Report", REPORT_NAME):
		doc = frappe.get_doc("Report", REPORT_NAME)
	else:
		doc = frappe.new_doc("Report")
		doc.name = REPORT_NAME

	doc.report_name = REPORT_NAME
	doc.report_type = "Script Report"
	doc.module = "Addsol Nl Custom"
	doc.ref_doctype = "Serial No"
	doc.is_standard = "Yes"
	doc.disabled = 0
	doc.prepared_report = 0
	doc.letter_head = "Standard"

	# The child tables are REPLACED rather than merged. A filter the report no
	# longer declares must not linger: the SPA builds its filter bar from these
	# rows, so a stale one shows up as a control that filters nothing.
	#
	# Rows are appended, NOT assigned as a list of dicts. A bare
	# `doc.filters = [{...}]` stores the dicts on the document untouched, and
	# `Document._set_defaults` then calls `row.is_new()` on a dict during save:
	# `AttributeError: 'dict' object has no attribute 'is_new'`. `append`
	# builds a real child document. Clearing first keeps the replace semantics.
	doc.filters = []
	for fieldname, fieldtype, label, options in FILTERS:
		doc.append(
			"filters",
			{
				"fieldname": fieldname,
				"fieldtype": fieldtype,
				"label": label,
				"options": options,
				"default": None,
				"mandatory": 0,
				"wildcard_filter": 0,
			},
		)

	doc.roles = []
	for role in ROLES:
		doc.append("roles", {"role": role})

	doc.flags.ignore_permissions = True
	doc.save()


if __name__ == "__main__":
	execute()
