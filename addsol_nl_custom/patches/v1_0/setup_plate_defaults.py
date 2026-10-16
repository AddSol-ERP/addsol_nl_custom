"""Part E1 - settings and master data the weighed items depend on.

Idempotent throughout, and it never overwrites a value somebody has already
chosen. Each single value is only written when it is still empty, and each
master record is only created when it does not exist.

Run order matters: this is a post_model_sync patch, so the DocTypes are already
in place when it runs. The Custom Fields arrive with sync_fixtures, which is
later in the same migrate, so anything here that needs one checks the column
exists first and leaves the rest for the next run.
"""

import frappe
from frappe.permissions import setup_custom_perms

from addsol_nl_custom.patches import with_developer_mode_restored

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


@with_developer_mode_restored
def execute():
	create_role()
	create_approver_permission()
	create_scrap_group()
	create_scrap_item()
	apply_single_defaults()
	ensure_plate_settings_defaults()


def create_role():
	if frappe.db.exists("Role", ROLE):
		return

	frappe.get_doc({"doctype": "Role", "role_name": ROLE}).insert(ignore_permissions=True)
	print(f"Created Role: {ROLE}")


def create_approver_permission():
	"""Give the approver read and write on Purchase Receipt at permlevel 1.

	Created here rather than exported as a fixture, for two reasons.
	Custom DocPerm is named by hash, so a fixture row would have to carry a
	name that means nothing to anyone; and Frappe's own customisation sync
	deletes and rebuilds DocPerm rows rather than importing them from fixtures.
	Writing it once, idempotently, is simpler and survives both.

	permlevel 1 is where the weight decision lives, so this is the whole of the
	role's power - deliberately nothing on any other DocType.
	"""
	if not frappe.db.exists("DocType", "Purchase Receipt"):
		return

	# Frappe ignores a doctype's standard DocPerm rows the moment any Custom
	# DocPerm row exists for it - Meta.set_custom_permissions replaces the
	# whole list - so the standard permissions have to be copied over before
	# the approver's row is added, exactly as the Role Permissions Manager
	# does when a permission is first customised. Without this copy the one
	# row below would wipe read, write and create for every other role on
	# Purchase Receipt. setup_custom_perms only copies when nothing has been
	# customised yet, so a site where an admin already edited permissions is
	# left alone.
	setup_custom_perms("Purchase Receipt")

	if frappe.db.exists("Custom DocPerm", {"role": ROLE, "permlevel": 1, "parent": "Purchase Receipt"}):
		return

	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"role": ROLE,
			"permlevel": 1,
			"parent": "Purchase Receipt",
			"parenttype": "DocType",
			"read": 1,
			"write": 1,
		}
	).insert(ignore_permissions=True)

	print(f"Created Custom DocPerm: {ROLE} on Purchase Receipt (permlevel 1, read + write)")


def create_scrap_group():
	if frappe.db.exists("Item Group", SCRAP_ITEM_GROUP):
		return

	# Scrap is weighed, not measured from a drawing, so it has no formula and no
	# multiplication factor. Both are written explicitly rather than left to a
	# meta default: a stray default on either field would make this group look
	# like a weighed grade, and the Item Group validate refuses that.
	frappe.get_doc(
		{
			"doctype": "Item Group",
			"item_group_name": SCRAP_ITEM_GROUP,
			"parent_item_group": "All Item Groups",
			"is_group": 0,
			"custom_formula": "",
			"custom_multiplication_factor": 0,
		}
	).insert(ignore_permissions=True)
	print(f"Created Item Group: {SCRAP_ITEM_GROUP}")


def create_scrap_item():
	"""Create the scrap Item, if there is enough on the site to do it honestly.

	India Compliance requires an HSN/SAC code on every Item, and refuses the
	insert without one. That is a tax classification, so this does not invent
	one: it reuses the code the customer already charges on their steel, which
	is the classification the same business already applies to the same metal.

	With no steel to copy from, the Item is skipped rather than guessed at, and
	the reason is printed. Plate Settings.scrap_item then stays empty and Part
	D refuses to book scrap with a message saying so, which is a better failure
	than the wrong HSN code silently on every scrap invoice.
	"""
	if frappe.db.exists("Item", SCRAP_ITEM):
		return

	hsn_code = find_steel_hsn_code()
	if not hsn_code:
		print(
			f"NOT created: {SCRAP_ITEM}. India Compliance needs an HSN/SAC code on every Item and "
			"no steel item on this site has one to copy. Create the item by hand with a valid "
			"code, then set it in Plate Settings."
		)
		return

	item = {
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
	if hsn_code:
		item["gst_hsn_code"] = hsn_code

	try:
		frappe.get_doc(item).insert(ignore_permissions=True)
	except Exception as error:
		# Never let a third party's mandatory field stop a migration.
		print(f"NOT created: {SCRAP_ITEM} - {error}. Create it by hand and set it in Plate Settings.")
		return

	print(f"Created Item: {SCRAP_ITEM} (HSN/SAC {hsn_code}, copied from the site's steel)")


def find_steel_hsn_code():
	"""The most common HSN/SAC code already in use on the site's steel.

	Scoped to items under an Item Group that carries a weight formula, so a
	services or finished-goods code cannot be picked up by accident.

	The formula column belongs to this app's Custom Fields, which migrate and
	install import from fixtures. If this patch is ever reached before those
	fixtures, the query would die on an unknown column, so the lookup simply
	gives up and the scrap Item is left for a later run to create.
	"""
	if not frappe.db.has_column("Item", "gst_hsn_code"):
		return None

	if not frappe.db.has_column("Item Group", "custom_formula"):
		return None

	rows = frappe.db.sql(
		"""
		select i.gst_hsn_code, count(*) as uses
		  from `tabItem` i
		  inner join `tabItem Group` g on g.name = i.item_group
		 where ifnull(i.gst_hsn_code, '') != ''
		   and ifnull(g.custom_formula, '') != ''
		 group by i.gst_hsn_code
		 order by uses desc
		 limit 1
		"""
	)

	return rows[0][0] if rows else None


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
