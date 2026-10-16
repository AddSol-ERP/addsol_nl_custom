# Copyright (c) 2026, Your Company and contributors
# For license information, see license.txt

"""The offcut hooks must not die on a Manufacture entry with nothing to do.

sync_cutting_records runs on every submitted Manufacture Stock Entry and
selects Stock Entry Detail.custom_cutting_record. When that column was
missing from the shipped schema the first real Manufacture submit failed
with "Unknown column 'custom_cutting_record' in 'SELECT'". add_record_rows
writes Plate Cutting Record.stock_entry the same way, which no DocType JSON
declared either.

These tests pin the live schema both fields need, and the no-op path for an
entry that carries no cutting rows.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.addsol_nl_custom.plates.offcut_stock import sync_cutting_records


class TestOffcutStockHooks(FrappeTestCase):
	def test_the_fields_the_offcut_hooks_write_exist(self):
		self.assertIsNotNone(
			frappe.get_meta("Stock Entry Detail").get_field("custom_cutting_record"),
			"offcut_stock.py selects and stamps Stock Entry Detail.custom_cutting_record",
		)
		self.assertIsNotNone(
			frappe.get_meta("Plate Cutting Record").get_field("stock_entry"),
			"offcut_stock.py db_sets Plate Cutting Record.stock_entry on every offcut row",
		)

	def test_a_manufacture_entry_with_no_cutting_rows_is_a_no_op(self):
		entry = frappe._dict({"purpose": "Manufacture", "name": "NO-SUCH-ENTRY", "docstatus": 1})
		self.assertIsNone(sync_cutting_records(entry))
