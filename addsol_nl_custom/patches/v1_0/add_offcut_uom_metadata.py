"""Add unit-neutral pricing metadata; preserve every historical Kg field."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from addsol_nl_custom.patches import with_developer_mode_restored


@with_developer_mode_restored
def execute():
	create_custom_fields(
		{
			dt: [
				{
					"fieldname": "custom_offcut_pricing_uom",
					"fieldtype": "Link",
					"options": "UOM",
					"label": "Offcut Pricing UOM",
					"read_only": 1,
				},
				{
					"fieldname": "custom_offcut_pricing_qty",
					"fieldtype": "Float",
					"precision": "6",
					"label": "Offcut Pricing Quantity",
					"read_only": 1,
				},
				{
					"fieldname": "custom_offcut_pricing_snapshot",
					"fieldtype": "Long Text",
					"label": "Offcut Pricing Snapshot",
					"read_only": 1,
					"hidden": 1,
				},
			]
			for dt in ["Serial No", "Batch"]
		}
	)
