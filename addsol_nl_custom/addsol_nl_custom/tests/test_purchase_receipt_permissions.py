# Copyright (c) 2026, Your Company and contributors
# For license information, see license.txt

"""Purchase Receipt must keep its standard permissions.

Frappe ignores a doctype's standard DocPerm rows entirely once any Custom
DocPerm row exists for it - Meta.set_custom_permissions replaces the whole
list. An earlier version of create_approver_permission added a single
approver row without first copying the standard ones, so every other role
lost read, write and create on Purchase Receipt and creating a receipt from
a submitted order failed with "You need the 'create' permission".

These tests pin both halves of the fix: the setup patch copies before it
adds, and the repair patch restores sites that already ran the broken one.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.patches.v1_0.fix_purchase_receipt_custom_perms import (
	execute as repair_purchase_receipt_perms,
)
from addsol_nl_custom.patches.v1_0.setup_plate_defaults import (
	ROLE,
	create_approver_permission,
)

DOCTYPE = "Purchase Receipt"
STANDARD_ROLE = "Stock Manager"


def custom_perms(doctype=DOCTYPE):
	return frappe.get_all(
		"Custom DocPerm",
		filters={"parent": doctype},
		fields=["role", "permlevel", "if_owner", "read", "write", "create"],
		order_by="role, permlevel",
	)


def clear_perm_caches():
	# Meta and the per-request role permission cache both have to go, or the
	# assertions below read the state from before the rows were touched.
	frappe.clear_cache()
	frappe.local.role_permissions = {}


def break_permissions_the_old_way():
	"""Leave Purchase Receipt exactly as the broken patch left it."""
	frappe.db.delete("Custom DocPerm", {"parent": DOCTYPE})
	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": DOCTYPE,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": ROLE,
			"permlevel": 1,
			"read": 1,
			"write": 1,
		}
	).insert(ignore_permissions=True)
	clear_perm_caches()


def make_stock_manager():
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": "plate.perm.test@example.com",
			"first_name": "Plate",
			"last_name": "Permission Test",
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)
	user.add_roles(STANDARD_ROLE)
	clear_perm_caches()
	return user.name


class TestPurchaseReceiptPermissions(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# Roll the rows back, then put the caches back too - they are not
		# transactional and would otherwise serve the test's world to the
		# rest of the suite.
		self.addCleanup(clear_perm_caches)
		self.addCleanup(frappe.db.rollback)

	def test_t1_the_approver_patch_copies_the_standard_permissions_first(self):
		frappe.db.delete("Custom DocPerm", {"parent": DOCTYPE})
		clear_perm_caches()

		create_approver_permission()

		rows = custom_perms()
		stock_manager = [r for r in rows if r.role == STANDARD_ROLE and r.permlevel == 0]
		self.assertTrue(stock_manager, "standard roles must be copied into Custom DocPerm")
		self.assertEqual(stock_manager[0].create, 1)
		self.assertEqual(stock_manager[0].read, 1)

		approver = [r for r in rows if r.role == ROLE and r.permlevel == 1]
		self.assertEqual(len(approver), 1)
		self.assertEqual(approver[0].write, 1)

	def test_t2_the_broken_state_takes_create_away(self):
		# The symptom the site showed, so the repair test below proves it
		# fixes something real rather than a state we never reach.
		break_permissions_the_old_way()
		user = make_stock_manager()

		self.assertFalse(frappe.has_permission(DOCTYPE, "create", user=user))
		self.assertFalse(frappe.has_permission(DOCTYPE, "read", user=user))

	def test_t3_the_repair_patch_restores_the_standard_permissions(self):
		break_permissions_the_old_way()
		user = make_stock_manager()

		repair_purchase_receipt_perms()
		clear_perm_caches()

		self.assertTrue(frappe.has_permission(DOCTYPE, "create", user=user))
		self.assertTrue(frappe.has_permission(DOCTYPE, "read", user=user))

		# The approver's permlevel 1 row is what the patch was for; it stays.
		approver = [r for r in custom_perms() if r.role == ROLE and r.permlevel == 1]
		self.assertEqual(len(approver), 1)
		self.assertEqual(approver[0].write, 1)

	def test_t4_the_repair_patch_is_idempotent(self):
		break_permissions_the_old_way()

		repair_purchase_receipt_perms()
		clear_perm_caches()
		after_first = custom_perms()

		repair_purchase_receipt_perms()
		clear_perm_caches()

		self.assertEqual(after_first, custom_perms())

	def test_t5_the_repair_patch_leaves_a_properly_customised_doctype_alone(self):
		# A doctype whose permissions were customised through the Role
		# Permissions Manager carries permlevel 0 rows; those are the
		# admin's, not our bug, and must not be rewritten.
		frappe.db.delete("Custom DocPerm", {"parent": DOCTYPE})
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": DOCTYPE,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": STANDARD_ROLE,
				"permlevel": 0,
				"read": 1,
				"write": 1,
				"create": 0,
			}
		).insert(ignore_permissions=True)
		clear_perm_caches()

		repair_purchase_receipt_perms()
		clear_perm_caches()

		rows = custom_perms()
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].create, 0)
