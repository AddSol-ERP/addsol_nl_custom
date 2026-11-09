"""Financial migration invariants, runnable without a bench."""

import json
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

path = (
	Path(__file__).resolve().parents[1]
	/ "addsol_nl_custom/addsol_nl_custom/plates/legacy_pricing_migration.py"
)
migration = types.ModuleType("legacy_pricing_migration")
exec(compile(path.read_text().replace("import frappe", ""), str(path), "exec"), migration.__dict__)


class MigrationTests(unittest.TestCase):
	def row(self, **values):
		return dict(qty=10, amount=12000, custom_rate_per_kg=40, custom_billable_weight_kg=300, **values)

	def test_metadata_preserves_agreed_rate_and_never_writes_ledger_fields(self):
		original = self.row()
		result = migration.row_conversion(original, {})
		self.assertEqual(result["custom_rate_per_pricing_uom"], 40)
		self.assertEqual(result["custom_chargeable_qty"], 300)
		self.assertFalse({"amount", "rate", "base_amount", "qty", "net_amount"} & result.keys())
		self.assertEqual(original, self.row())
		saved = json.loads(result["custom_pricing_snapshot"])
		self.assertTrue(saved["preserve_contract"])
		self.assertEqual(saved["actual_per_unit"], 30)
		self.assertEqual(saved["pricing_uom"], "Kg")

	def test_existing_generic_snapshot_wins(self):
		self.assertIsNone(
			migration.row_conversion(self.row(custom_pricing_snapshot='{"pricing_uom":"Metre"}'), {})
		)

	def test_conflicting_money_blocks_conversion(self):
		row = self.row()
		row["amount"] = 13000
		with self.assertRaisesRegex(ValueError, "does not reconcile"):
			migration.row_conversion(row, {})

	def test_booked_amount_recovers_missing_weight(self):
		row = self.row()
		row.pop("custom_billable_weight_kg")
		self.assertEqual(migration.row_conversion(row, {})["custom_chargeable_qty"], 300)

	def test_returns_keep_positive_metadata_without_changing_negative_amount(self):
		row = self.row()
		row.update(qty=-10, amount=-12000)
		self.assertEqual(migration.row_conversion(row, {})["custom_chargeable_qty"], 300)
		self.assertEqual(row["amount"], -12000)

	def test_source_geometry_freezes_legacy_measure_not_current_commercial_rule(self):
		result = migration.frozen_kg_snapshot(320, 10, 30, 2000, 1000)
		self.assertEqual(result["calculated_chargeable_qty"], 300)
		self.assertEqual(result["actual_per_unit"], 32)
		self.assertEqual(result["rule"]["formula_expression"], "L * W * F")

	def test_partial_generic_rate_conflict_is_not_overwritten(self):
		with self.assertRaisesRegex(ValueError, "rates differ"):
			migration.row_conversion(self.row(custom_rate_per_pricing_uom=99), {})

	def test_conflict_and_dry_run_never_write_any_record(self):
		fake = Mock()
		fake.get_installed_apps.return_value = ["erpnext_ui"]
		fake.db.get_single_value.return_value = 0
		fake.db.has_column.side_effect = lambda dt, field: dt not in ("Serial No", "Batch", "Item Group")
		fake.get_doc.return_value = {}
		bad = self.row()
		bad.update(name="ROW-1", parent="PO-1", item_code="PLATE", amount=13000)
		row = type("Row", (dict,), {"__getattr__": dict.get})(bad)
		fake.get_all.side_effect = lambda dt, **kwargs: [row] if dt == "Purchase Order Item" else []
		with patch.object(migration, "frappe", fake, create=True):
			report = migration.run()
			self.assertEqual(len(report["conflicts"]), 1)
			with self.assertRaisesRegex(ValueError, "no data changed"):
				migration.run(dry_run=False)
		fake.db.set_value.assert_not_called()
		fake.db.set_single_value.assert_not_called()
