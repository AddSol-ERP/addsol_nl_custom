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

from addsol_nl_custom.patches import with_developer_mode_restored

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

# Extra columns worth showing alongside the value, so the rows in the error
# message identify themselves.
DETAIL_COLUMNS = {
	("Batch", "custom_conversion_factor"): ("name", "item"),
	("Purchase Receipt Item", "custom_total_stock_qty"): ("parent", "item_code", "qty"),
}

# Cap the listing so a field with thousands of rows cannot flood the log.
DETAIL_LIMIT = 20


@with_developer_mode_restored
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

	The old unit-conversion scripts wrote to these. If anything is left the
	migration stops and prints the rows, so whoever is running it can judge
	whether the values are junk before clearing them - no second SQL session
	needed to find out what is in the way.
	"""
	populated = []

	for dt, fieldname in DATA_BEARING_CUSTOM_FIELDS:
		name = f"{dt}-{fieldname}"
		if not frappe.db.exists("Custom Field", name):
			continue

		# NULL and 0 both mean "never filled in" for a Float, so coalesce them.
		# dt and fieldname are module constants, never user input.
		total = frappe.db.sql(f"select count(*) from `tab{dt}` where coalesce(`{fieldname}`, 0) != 0")[0][0]

		if total:
			populated.append((name, total, describe_rows(dt, fieldname)))

	if populated:
		frappe.throw(
			"Part A stopped: these Kg-era Custom Fields still hold values and were NOT "
			"deleted.\n\n"
			+ "\n\n".join(
				f"{name} - {total} row(s)\n" + "\n".join(f"    {row}" for row in rows)
				for name, total, rows in populated
			)
			+ "\n\nIf these are settled history and the values are not needed, clear them:\n"
			+ "\n".join(
				f"    {clear_statement(dt, fieldname)}" for dt, fieldname in DATA_BEARING_CUSTOM_FIELDS
			)
			+ "\n\n(0, not NULL - Frappe creates Custom Field columns as NOT NULL DEFAULT 0.)\n"
			+ "Re-run with the session's safe updates off, e.g. prefix the run with\n"
			+ "    SET SQL_SAFE_UPDATES = 0;\n\n"
			+ "then re-run bench --site <site> migrate. To see every row first:\n"
			+ "\n".join(
				f"    {select_statement(dt, fieldname)}" for dt, fieldname in DATA_BEARING_CUSTOM_FIELDS
			),
			title="Legacy plate customizations still in use",
		)

	for dt, fieldname in DATA_BEARING_CUSTOM_FIELDS:
		name = f"{dt}-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, force=True, ignore_missing=True)
			print(f"Deleted Custom Field: {name}")


def describe_rows(dt, fieldname):
	"""The offending rows, in a form fit to read inside an error message."""
	columns = DETAIL_COLUMNS.get((dt, fieldname), ("name",))
	selected = ", ".join(f"`{column}`" for column in columns)
	rows = frappe.db.sql(
		f"select {selected}, `{fieldname}` from `tab{dt}` "
		f"where coalesce(`{fieldname}`, 0) != 0 limit {DETAIL_LIMIT}"
	)
	headers = [*columns, fieldname]
	return [
		"  ".join(f"{header}={value}" for header, value in zip(headers, row, strict=True)) for row in rows
	]


def select_statement(dt, fieldname):
	return f"SELECT * FROM `tab{dt}` WHERE COALESCE(`{fieldname}`, 0) <> 0;"


def clear_statement(dt, fieldname):
	# 0 rather than NULL: Frappe creates Custom Field columns NOT NULL DEFAULT 0,
	# so NULL is rejected with error 1048. The emptiness check treats both alike.
	return f"UPDATE `tab{dt}` SET `{fieldname}` = 0 WHERE COALESCE(`{fieldname}`, 0) <> 0;"
