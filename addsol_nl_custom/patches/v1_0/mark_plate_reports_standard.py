"""Use the app's Python modules for plate Script Reports."""

import frappe

from addsol_nl_custom.patches import with_developer_mode_restored


@with_developer_mode_restored
def execute():
	for report_name in ("Plate Stock Register", "Plate Receipt Weight Variance"):
		if frappe.db.exists("Report", report_name):
			frappe.db.set_value("Report", report_name, "is_standard", "Yes")
