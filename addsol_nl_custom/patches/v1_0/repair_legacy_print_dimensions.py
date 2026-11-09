"""Repair only historical print geometry; preserve all financial/cutting values."""

import json

import frappe

from addsol_nl_custom.addsol_nl_custom.plates.legacy_dimensions import item_dimensions
from addsol_nl_custom.addsol_nl_custom.plates.legacy_pricing_migration import PARENTS
from addsol_nl_custom.patches import with_developer_mode_restored


@with_developer_mode_restored
def execute():
	items = {}
	for doctype in PARENTS:
		if not frappe.db.has_column(doctype, "custom_rate_per_kg"):
			continue
		if not frappe.db.has_column(doctype, "custom_pricing_dimensions"):
			raise ValueError("Migrate ERP UI first: custom_pricing_dimensions is missing.")
		for row in frappe.get_all(
			doctype,
			filters={"custom_rate_per_kg": [">", 0]},
			fields=["name", "item_code", "custom_pricing_snapshot"],
			limit_page_length=0,
		):
			snapshot = json.loads(row.custom_pricing_snapshot) if row.custom_pricing_snapshot else None
			if (
				snapshot
				and snapshot.get("migration_origin") != "legacy_kg_v1"
				and not snapshot.get("preserve_contract")
			):
				continue  # New per-UOM history keeps its configured parameter display.
			if row.item_code not in items:
				items[row.item_code] = item_dimensions(frappe.get_doc("Item", row.item_code))
			dimensions = items[row.item_code]
			values = {"custom_pricing_dimensions": dimensions}
			if snapshot:
				snapshot["display_dimensions"] = dimensions
				values["custom_pricing_snapshot"] = json.dumps(snapshot)
			frappe.db.set_value(doctype, row.name, values, update_modified=False)
