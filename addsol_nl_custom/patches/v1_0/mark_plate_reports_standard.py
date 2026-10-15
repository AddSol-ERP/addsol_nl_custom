"""Use the app's Python modules for plate Script Reports."""

import frappe


def execute():
	for report_name in ("Plate Stock Register", "Plate Receipt Weight Variance"):
		if frappe.db.exists("Report", report_name):
			frappe.db.set_value("Report", report_name, "is_standard", "Yes")
