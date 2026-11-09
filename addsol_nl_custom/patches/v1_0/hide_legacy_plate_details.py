"""Hide retired buying fields and empty sections; retain historical stored values."""

import frappe

from addsol_nl_custom.addsol_nl_custom.plates.legacy_pricing_migration import ARCHIVED_FIELDS, PARENTS
from addsol_nl_custom.patches import with_developer_mode_restored


@with_developer_mode_restored
def execute():
	doctypes = {*PARENTS, *PARENTS.values()}
	for field in frappe.get_all(
		"Custom Field",
		filters={"dt": ["in", sorted(doctypes)], "fieldname": ["in", sorted(ARCHIVED_FIELDS)]},
		fields=["name", "dt"],
		limit_page_length=0,
	):
		frappe.db.set_value(
			"Custom Field",
			field.name,
			{
				"hidden": 1,
				"read_only": 1,
				"in_list_view": 0,
				"reqd": 0,
				"print_hide": 1,
			},
			update_modified=False,
		)
	for doctype in doctypes:
		frappe.clear_cache(doctype=doctype)
