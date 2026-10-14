"""Part E1 - settings and master data the weighed items depend on.

Idempotent throughout, and it never overwrites a value somebody has already
chosen. Each single value is only written when it is still empty, and each
master record is only created when it does not exist.

Run order matters: this is a post_model_sync patch, so the DocTypes and Custom
Fields are already in place when it runs.
"""

import frappe

ROLE = "Plate Weight Approver"
SCRAP_ITEM_GROUP = "Scrap"
SCRAP_ITEM = "MS Scrap"

# Single DocType -> {field: value we want if nothing is set yet}.
SINGLE_DEFAULTS = {
	"Buying Settings": {"maintain_same_rate": 0},
	"Accounts Settings": {"over_billing_allowance": 10},
	"Stock Settings": {
		"pick_serial_and_batch_based_on": "FIFO",
		"do_not_use_batchwise_valuation": 0,
	},
}


def execute():
	create_role()
	create_scrap_group()
	create_scrap_item()
	apply_single_defaults()
	ensure_plate_settings_defaults()


def create_role():
	if frappe.db.exists("Role", ROLE):
		return

	frappe.get_doc({"doctype": "Role", "role_name": ROLE}).insert(ignore_permissions=True)
	print(f"Created Role: {ROLE}")


def create_scrap_group():
	if frappe.db.exists("Item Group", SCRAP_ITEM_GROUP):
		return

	frappe.get_doc(
		{
			"doctype": "Item Group",
			"item_group_name": SCRAP_ITEM_GROUP,
			"parent_item_group": "All Item Groups",
			"is_group": 0,
		}
	).insert(ignore_permissions=True)
	print(f"Created Item Group: {SCRAP_ITEM_GROUP}")


def create_scrap_item():
	if frappe.db.exists("Item", SCRAP_ITEM):
		return

	# Scrap is weighed, not counted, so stock UOM is Kg and there is no batch or
	# serial tracking - the weight travels on the row instead.
	frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": SCRAP_ITEM,
			"item_name": SCRAP_ITEM,
			"item_group": SCRAP_ITEM_GROUP,
			"stock_uom": "Kg",
			"is_stock_item": 1,
			"has_batch_no": 0,
			"has_serial_no": 0,
			"valuation_method": "FIFO",
			"description": "Offcuts too small to keep, booked at the source batch's cost per kg.",
		}
	).insert(ignore_permissions=True)
	print(f"Created Item: {SCRAP_ITEM}")


def apply_single_defaults():
	for doctype, defaults in SINGLE_DEFAULTS.items():
		for field, value in defaults.items():
			if frappe.db.get_single_value(doctype, field) not in (None, ""):
				continue

			frappe.db.set_single_value(doctype, field, value)
			print(f"{doctype}.{field} = {value}")


def ensure_plate_settings_defaults():
	"""Point Plate Settings at the records just created, where still blank."""
	scrap_item = SCRAP_ITEM if frappe.db.exists("Item", SCRAP_ITEM) else None
	approver_role = ROLE if frappe.db.exists("Role", ROLE) else None

	for field, value in (("scrap_item", scrap_item), ("approver_role", approver_role)):
		if frappe.db.get_single_value("Plate Settings", field):
			continue
		frappe.db.set_single_value("Plate Settings", field, value)
		print(f"Plate Settings.{field} = {value}")
