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
			with self.assertRaisesRegex(ValueError, "no data changed") as raised:
				migration.run(dry_run=False)
			self.assertIn("Purchase Order Item ROW-1 (PO-1)", str(raised.exception).splitlines()[0])
		fake.db.set_value.assert_not_called()
		fake.db.set_single_value.assert_not_called()

	def test_missing_measurement_reports_specific_field_without_guessing(self):
		row = self.row()
		row.update(amount=0, custom_billable_weight_kg=0, custom_est_weight_kg=0)
		with self.assertRaisesRegex(ValueError, "Chargeable Kg.*found 0"):
			migration.row_conversion(row, {"weight_per_unit": 30})

	def test_zero_quantity_reports_specific_field(self):
		row = self.row()
		row["qty"] = 0
		with self.assertRaisesRegex(ValueError, "Document quantity.*found 0"):
			migration.row_conversion(row, {})

	def recovery_fixture(self):
		serial = dict(name="PL-000095", item_code="PLATE", batch_no="PLB-26-00003")
		receipt = dict(
			docstatus=1,
			item_code="PLATE",
			qty=40,
			stock_qty=40,
			amount=52080000,
			custom_rate_per_kg=2800,
			custom_billable_weight_kg=18600,
			custom_est_weight_kg=18000,
		)
		entries = [dict(serial_no=f"PL-{n:06d}", batch_no="PLB-26-00003", qty=1) for n in range(57, 97)]
		return serial, receipt, entries

	def test_recovers_verified_receipt_allocation_without_changing_receipt(self):
		serial, receipt, entries = self.recovery_fixture()
		original = receipt.copy()
		self.assertEqual(migration.receipt_bundle_weight(serial, receipt, entries), 465)
		self.assertEqual(receipt, original)

	def test_recovery_rejects_incomplete_duplicate_or_wrong_batch_bundle(self):
		serial, receipt, entries = self.recovery_fixture()
		for bad in (
			entries[:-1],
			[*entries[:-1], entries[0]],
			[{**entry, "batch_no": "OTHER"} for entry in entries],
			[{**entry, "qty": -1} for entry in entries],
		):
			with self.subTest(bad=bad[0]), self.assertRaises(ValueError):
				migration.receipt_bundle_weight(serial, receipt, bad)

	def test_recovery_rejects_unsubmitted_or_different_item_receipt(self):
		serial, receipt, entries = self.recovery_fixture()
		for changes in (dict(docstatus=0), dict(docstatus=2), dict(item_code="OTHER")):
			with self.assertRaises(ValueError):
				migration.receipt_bundle_weight(serial, {**receipt, **changes}, entries)

	def test_recovery_checks_money_and_never_uses_theoretical_weight(self):
		serial, receipt, entries = self.recovery_fixture()
		for changes in (dict(amount=1), dict(amount=0, custom_billable_weight_kg=0)):
			with self.assertRaises(ValueError):
				migration.receipt_bundle_weight(serial, {**receipt, **changes}, entries)

	def test_verified_rejected_stock_is_separate_from_paid_weight(self):
		serial = dict(name="PL-000056", item_code="ANGLE", batch_no="BATCH", warehouse="Returnable")
		receipt = dict(
			docstatus=1,
			item_code="ANGLE",
			rejected_qty=5,
			conversion_factor=1,
			rejected_warehouse="Returnable",
			qty=50,
			custom_billable_weight_kg=910,
		)
		entries = [dict(serial_no=f"PL-{n:06d}", batch_no="BATCH", qty=1) for n in range(52, 57)]
		migration.validate_rejected_bundle(serial, receipt, entries)
		for bad in (entries[:-1], [*entries[:-1], entries[0]]):
			with self.assertRaises(ValueError):
				migration.validate_rejected_bundle(serial, receipt, bad)
		with self.assertRaisesRegex(ValueError, "subsequent movements"):
			migration.validate_rejected_bundle({**serial, "warehouse": "Production"}, receipt, entries)

	def test_direct_entry_numeric_columns_are_not_null_but_snapshot_has_no_estimate(self):
		result = migration.row_conversion(self.row(), {})
		self.assertEqual(result["custom_estimated_chargeable_qty"], 0)
		self.assertEqual(result["custom_estimated_pricing_amount"], 0)
		snapshot = json.loads(result["custom_pricing_snapshot"])
		self.assertIsNone(snapshot["calculated_chargeable_qty"])
		self.assertIsNone(snapshot["baseline_per_unit"])
		self.assertEqual(result["custom_chargeable_qty"], 300)
		self.assertEqual(result["custom_rate_per_pricing_uom"], 40)

	def test_formula_estimate_columns_keep_computed_values(self):
		result = migration.row_conversion(self.row(), {"custom_length_mm": 2000, "custom_width_mm": 1000})
		self.assertEqual(result["custom_estimated_chargeable_qty"], 300)
		self.assertEqual(result["custom_estimated_pricing_amount"], 12000)
