# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""The wrongly named Custom Field record is an orphan, and the patch removes it.

The three `custom_document_attachments` records shipped with one identical
name, so only the last of them could ever be on a site: the others collided
with it and died with "A field with the name custom_document_attachments
already exists". The record left behind blocks the properly named one from
landing, because the fieldname is already on the DocType:

    "A field with the name custom_document_attachments already exists in
    Stock Entry"

`bench --site <site> run-tests --app addsol_nl_custom`
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.patches.v1_0.remove_orphaned_custom_field_records import (
	ATTACHMENTS_FIELD,
	execute,
	orphaned_records,
)

# Two DocTypes the attachments field is NOT shipped on, so the test can put
# one there without colliding with the fixture's own records. They are
# different DocTypes because the fieldname can only live on one of them at a
# time.
ORPHAN_DOCTYPE = "Purchase Order"
NAMED_DOCTYPE = "Purchase Invoice"


class TestOrphanedCustomFields(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# FrappeTestCase rolls the database back once per class, not once per
		# test, so a field an earlier test put on a DocType would still be
		# there. Undo whatever the last test left behind.
		self.addCleanup(frappe.db.rollback)

	def make_orphan(self):
		"""A Custom Field record under a name Frappe would never use.

		Frappe names a Custom Field `<DocType>-<fieldname>`, but a fixture
		import keeps the name it is given - which is how this record came to
		be. `flags.name_set` is the same switch.
		"""
		record = frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": ORPHAN_DOCTYPE,
				"fieldname": ATTACHMENTS_FIELD,
				"fieldtype": "HTML",
				"label": "Document Attachments",
				"insert_after": "status",
			}
		)
		record.name = ATTACHMENTS_FIELD
		record.flags.name_set = True

		return record.insert(ignore_permissions=True)

	def make_named_record(self):
		"""The same field, under the name Frappe gives it."""
		return frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": NAMED_DOCTYPE,
				"fieldname": ATTACHMENTS_FIELD,
				"fieldtype": "HTML",
				"label": "Document Attachments",
				"insert_after": "status",
			}
		).insert(ignore_permissions=True)

	def test_the_orphan_is_found(self):
		orphan = self.make_orphan()

		self.assertEqual(orphan.name, ATTACHMENTS_FIELD)
		self.assertIn(ATTACHMENTS_FIELD, [record.name for record in orphaned_records()])

	def test_the_patch_removes_the_orphan(self):
		self.make_orphan()

		execute()

		self.assertFalse(frappe.db.exists("Custom Field", ATTACHMENTS_FIELD))

	def test_a_properly_named_record_is_left_alone(self):
		record = self.make_named_record()
		self.assertEqual(record.name, f"{NAMED_DOCTYPE}-{ATTACHMENTS_FIELD}")

		execute()

		self.assertTrue(frappe.db.exists("Custom Field", record.name))
