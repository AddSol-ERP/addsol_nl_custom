"""Preserve existing receipt heat data before removing PR Item custom fields."""

import frappe


def execute():
	# Older receipts may not have passed through the metadata hook. Preserve the
	# values they carry on the corresponding inventory records before the Custom
	# Fields are deleted and their columns are trimmed by migrate.
	old_fields = [
		fieldname
		for fieldname in ("custom_heat_number", "custom_mtc_no")
		if frappe.db.has_column("Purchase Receipt Item", fieldname)
	]
	if old_fields:
		for row in frappe.get_all(
			"Purchase Receipt Item",
			filters={"parenttype": "Purchase Receipt", "docstatus": 1},
			fields=["name", "serial_and_batch_bundle", *old_fields],
			limit_page_length=0,
		):
			if not row.serial_and_batch_bundle:
				continue
			for entry in frappe.get_all(
				"Serial and Batch Entry",
				filters={"parent": row.serial_and_batch_bundle, "parenttype": "Serial and Batch Bundle"},
				fields=["batch_no", "serial_no"],
				limit_page_length=0,
			):
				if entry.batch_no:
					fill_if_empty("Batch", entry.batch_no, row)
				if entry.serial_no and row.custom_heat_number:
					if not frappe.db.get_value("Serial No", entry.serial_no, "custom_heat_number"):
						frappe.db.set_value(
							"Serial No", entry.serial_no,
							"custom_heat_number", row.custom_heat_number,
							update_modified=False,
						)

	for fieldname in ("custom_heat_number", "custom_mtc_no"):
		name = f"Purchase Receipt Item-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)


def fill_if_empty(doctype, name, row):
	values = {}
	for fieldname in ("custom_heat_number", "custom_mtc_no"):
		value = row.get(fieldname)
		if value and not frappe.db.get_value(doctype, name, fieldname):
			values[fieldname] = value
	if values:
		frappe.db.set_value(doctype, name, values, update_modified=False)
