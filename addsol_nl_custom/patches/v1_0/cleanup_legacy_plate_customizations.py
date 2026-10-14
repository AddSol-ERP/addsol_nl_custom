"""Part A - remove the legacy Kg-based plate customizations.

The previous design kept plate stock in Kg with the plate as a transaction UOM.
That design is incompatible with serial numbers and with two lots of different
weights on one receipt line, so everything it added is removed here.

The matching rows have also been removed from ``fixtures/*.json`` in the same
commit. Frappe's fixture import only upserts the records present in the file,
it never deletes records that are absent from it, so an entry left behind in a
fixture would simply be re-created on the next migrate.

Idempotent: every step is a no-op once the record is gone.
"""

import frappe

# Reports / scripts that only existed to serve the Kg-based design.
LEGACY_REPORTS = ["Attendance Register"]
LEGACY_CLIENT_SCRIPTS = [
	"Purchase Reciept Item UOM conversion",
	"Stock Entry \u2014 Fetch Conversion from Batch",
]
LEGACY_SERVER_SCRIPTS = ["Set Conversion factor in batch"]

# Custom Fields to drop. The two Kg fields are data-bearing, so they are only
# dropped once the pre-check below proves they are empty.
UNUSED_CUSTOM_FIELDS = [("Item", "custom_second_unit_of_measure")]
DATA_BEARING_CUSTOM_FIELDS = [
	("Batch", "custom_conversion_factor"),
	("Purchase Receipt Item", "custom_total_stock_qty"),
]


def execute():
	delete_legacy_reports_and_scripts()
	delete_unused_custom_fields()
	delete_data_bearing_custom_fields()


def delete_legacy_reports_and_scripts():
	for name in LEGACY_REPORTS:
		if frappe.db.exists("Report", name):
			frappe.delete_doc("Report", name, force=True, ignore_missing=True)
			print(f"Deleted Report: {name}")

	for name in LEGACY_CLIENT_SCRIPTS:
		if frappe.db.exists("Client Script", name):
			frappe.delete_doc("Client Script", name, force=True, ignore_missing=True)
			print(f"Deleted Client Script: {name}")

	for name in LEGACY_SERVER_SCRIPTS:
		if frappe.db.exists("Server Script", name):
			frappe.delete_doc("Server Script", name, force=True, ignore_missing=True)
			print(f"Deleted Server Script: {name}")


def delete_unused_custom_fields():
	for dt, fieldname in UNUSED_CUSTOM_FIELDS:
		name = f"{dt}-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, force=True, ignore_missing=True)
			print(f"Deleted Custom Field: {name}")


def delete_data_bearing_custom_fields():
	"""Drop the two Kg fields, but refuse to touch them while they still hold data.

	The old unit-conversion scripts wrote to these. If anything is left, the
	weight values have to be reviewed by hand before the field goes.
	"""
	populated = []
	for dt, fieldname in DATA_BEARING_CUSTOM_FIELDS:
		name = f"{dt}-{fieldname}"
		if not frappe.db.exists("Custom Field", name):
			continue

		# NULL and 0 both mean "never filled in" for a Float, so coalesce them.
		# dt and fieldname are module constants, never user input.
		rows = frappe.db.sql(f"select count(*) from `tab{dt}` where coalesce(`{fieldname}`, 0) != 0")[0][0]
		if rows:
			populated.append(f"{name} ({rows} non-empty rows)")

	if populated:
		frappe.throw(
			"Part A stopped: these Kg-era Custom Fields still hold values and were NOT "
			"deleted. Review and clear them by hand, then re-run bench migrate.\n"
			+ "\n".join(f"  - {item}" for item in populated),
			title="Legacy plate customizations still in use",
		)

	for dt, fieldname in DATA_BEARING_CUSTOM_FIELDS:
		name = f"{dt}-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, force=True, ignore_missing=True)
			print(f"Deleted Custom Field: {name}")
