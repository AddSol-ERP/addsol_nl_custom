"""One-time per-kg -> generic per-UOM metadata conversion. Never rebook money.

Preview with bench execute ...legacy_pricing_migration.run (dry_run defaults True).
The patch applies the same audited plan transactionally. Legacy columns remain
hidden/read-only as historical evidence; no stock or accounting documents save.
"""

import json
import math

import frappe

PARENTS = {
	"Supplier Quotation Item": "Supplier Quotation",
	"Purchase Order Item": "Purchase Order",
	"Purchase Receipt Item": "Purchase Receipt",
	"Purchase Invoice Item": "Purchase Invoice",
}
ARCHIVED_FIELDS = {
	"custom_rate_per_kg",
	"custom_est_weight_kg",
	"custom_supplier_weight_kg",
	"custom_weighbridge_weight_kg",
	"custom_variance_pct",
	"custom_weight_decision",
	"custom_billable_weight_kg",
	"custom_truck_net_weight_kg",
	"custom_total_est_weight_kg",
	"custom_total_billable_weight_kg",
}


def positive(value, label="Quantity/rate"):
	number = float(value or 0)
	if not math.isfinite(number) or number <= 0:
		raise ValueError(f"{label} must be positive and finite (found {value!r}).")
	return number


def frozen_kg_snapshot(quantity, stock_units, nominal_per_unit, length=0, width=0):
	"""Freeze measured Kg with source geometry; never use today's pricing UOM."""
	quantity, units = positive(quantity, "Chargeable Kg"), positive(stock_units, "Document quantity")
	nominal = positive(nominal_per_unit or quantity / units, "Nominal Kg per unit")
	params, definitions = {}, []
	if float(length or 0) > 0 and float(width or 0) > 0:
		params = {"L": positive(length), "W": positive(width), "F": nominal / (float(length) * float(width))}
		definitions = [
			{"symbol": "L", "label": "Length", "uom": "mm", "data_source": "custom_length_mm"},
			{"symbol": "W", "label": "Width", "uom": "mm", "data_source": "custom_width_mm"},
			{"symbol": "F", "data_source": ""},
		]
		mode, expression = "Formula", "L * W * F"
	else:
		mode, expression = "Direct Entry", ""
	return {
		"pricing_uom": "Kg",
		"chargeable_qty": quantity,
		"calculated_chargeable_qty": nominal * units if mode == "Formula" else None,
		"baseline_per_unit": nominal if mode == "Formula" else None,
		"actual_per_unit": quantity / units,
		"preserve_contract": True,
		"migration_origin": "legacy_kg_v1",
		"rule": {
			"name": "Historical Kg contract",
			"pricing_uom": "Kg",
			"formula_mode": mode,
			"formula_expression": expression,
			"params": definitions,
			"tolerance_plus": 0,
			"tolerance_minus": 0,
		},
		"params_by_symbol": params,
	}


def row_conversion(row, item):
	"""Only fill generic metadata. Existing generic snapshots always win."""
	if row.get("custom_pricing_snapshot") or not row.get("custom_rate_per_kg"):
		return None
	rate = positive(row["custom_rate_per_kg"], "Legacy rate per Kg")
	qty = positive(abs(float(row.get("qty") or 0)), "Document quantity")
	amount = abs(float(row.get("amount") or 0))
	measured = float(row.get("custom_billable_weight_kg") or row.get("custom_est_weight_kg") or 0)
	if amount:
		if measured and not math.isclose(amount, measured * rate, abs_tol=0.05, rel_tol=1e-7):
			raise ValueError("Booked amount does not reconcile with the stored weight and per-kg rate.")
		measured = amount / rate
	measured = positive(
		measured,
		"Chargeable Kg (billable weight / estimated weight, or booked amount divided by legacy rate)",
	)
	nominal = float(row.get("custom_unit_weight_kg") or item.get("weight_per_unit") or measured / qty)
	snapshot = frozen_kg_snapshot(
		measured, qty, nominal, item.get("custom_length_mm"), item.get("custom_width_mm")
	)
	# A half-migrated row must not have its already-entered new rate replaced.
	new_rate = float(row.get("custom_rate_per_pricing_uom") or 0)
	if new_rate and not math.isclose(new_rate, rate, rel_tol=1e-9):
		raise ValueError("Generic and legacy rates differ; review the row before migration.")
	from erpnext_ui.print_dimensions import pricing_dimensions

	return {
		"custom_pricing_dimensions": pricing_dimensions({"custom_pricing_snapshot": snapshot}),
		"custom_pricing_uom": "Kg",
		"custom_rate_per_pricing_uom": rate,
		"custom_chargeable_qty": measured,
		"custom_pricing_snapshot": json.dumps(snapshot),
		"custom_estimated_chargeable_qty": snapshot["calculated_chargeable_qty"],
		"custom_estimated_pricing_amount": (snapshot["calculated_chargeable_qty"] * rate)
		if snapshot["calculated_chargeable_qty"] is not None
		else None,
	}


def receipt_bundle_weight(serial, receipt, entries):
	"""Allocate a reconciled receipt's Kg across its verified one-unit serials."""
	if receipt.get("docstatus") != 1 or receipt.get("item_code") != serial.get("item_code"):
		raise ValueError("Recovery requires a submitted receipt for the same Item.")
	units = positive(receipt.get("stock_qty"), "Receipt stock quantity")
	names = [entry.get("serial_no") for entry in entries]
	if not entries or any(not name for name in names) or len(set(names)) != len(names):
		raise ValueError("Receipt bundle needs distinct serials for every stock unit.")
	if len(entries) != units or any(float(entry.get("qty") or 0) != 1 for entry in entries):
		raise ValueError("Receipt bundle quantities do not reconcile with receipt stock quantity.")
	matching = [entry for entry in entries if entry.get("serial_no") == serial.get("name")]
	if len(matching) != 1 or matching[0].get("batch_no") != serial.get("batch_no"):
		raise ValueError("Receipt bundle does not match this serial and batch.")
	# Recover from the original commercial record, never today's Item weight.
	if not (
		float(receipt.get("amount") or 0) > 0 or float(receipt.get("custom_billable_weight_kg") or 0) > 0
	):
		raise ValueError("Receipt has no booked amount or accepted weight for recovery.")
	legacy = dict(receipt)
	legacy["custom_pricing_snapshot"] = None
	converted = row_conversion(legacy, {})
	if not converted:
		raise ValueError("Receipt has no historical Kg pricing basis.")
	return converted["custom_chargeable_qty"] / units


class RejectedStockWithoutWeight(ValueError):
	"""Verified unpriced rejected stock; do not infer accepted-stock weight."""

	def __init__(self, receipt):
		super().__init__("Rejected stock has no recorded weight; excluded from paid Kg recovery.")
		self.receipt = receipt


def validate_rejected_bundle(serial, receipt, entries):
	if receipt.get("docstatus") != 1 or receipt.get("item_code") != serial.get("item_code"):
		raise ValueError("Rejected bundle requires a submitted receipt for the same Item.")
	if not receipt.get("rejected_warehouse") or serial.get("warehouse") != receipt.get("rejected_warehouse"):
		raise ValueError(
			"Serial is not in the receipt's rejected warehouse; review its subsequent movements."
		)
	units = positive(receipt.get("rejected_qty"), "Rejected quantity") * positive(
		receipt.get("conversion_factor"), "Receipt conversion factor"
	)
	names = [entry.get("serial_no") for entry in entries]
	if not entries or any(not name for name in names) or len(set(names)) != len(names):
		raise ValueError("Rejected bundle must contain distinct serials.")
	if len(entries) != units or any(float(entry.get("qty") or 0) != 1 for entry in entries):
		raise ValueError("Rejected bundle quantities do not reconcile with rejected stock quantity.")
	matching = [entry for entry in entries if entry.get("serial_no") == serial.get("name")]
	if len(matching) != 1 or matching[0].get("batch_no") != serial.get("batch_no"):
		raise ValueError("Rejected bundle does not match this serial and batch.")


def recover_serial_weight(serial):
	"""Read-only lookup; ambiguous source receipts must be reviewed explicitly."""
	links = frappe.get_all(
		"Serial and Batch Entry", filters={"serial_no": serial.name}, fields=["parent"], limit_page_length=0
	)
	bundles = list({link.parent for link in links})
	if not bundles:
		raise ValueError("No original receipt bundle found for the missing serial weight.")
	fields = available_fields(
		"Purchase Receipt Item",
		[
			"name",
			"parent",
			"docstatus",
			"item_code",
			"qty",
			"stock_qty",
			"amount",
			"serial_and_batch_bundle",
			"custom_rate_per_kg",
			"custom_billable_weight_kg",
			"custom_est_weight_kg",
			"custom_rate_per_pricing_uom",
		],
	)
	receipts = frappe.get_all(
		"Purchase Receipt Item",
		filters={"serial_and_batch_bundle": ["in", bundles], "item_code": serial.item_code, "docstatus": 1},
		fields=fields,
		limit_page_length=0,
	)
	if not receipts and frappe.db.has_column("Purchase Receipt Item", "rejected_serial_and_batch_bundle"):
		rejected = frappe.get_all(
			"Purchase Receipt Item",
			filters={
				"rejected_serial_and_batch_bundle": ["in", bundles],
				"item_code": serial.item_code,
				"docstatus": 1,
			},
			fields=[
				"name",
				"parent",
				"docstatus",
				"item_code",
				"rejected_qty",
				"conversion_factor",
				"rejected_warehouse",
				"rejected_serial_and_batch_bundle",
			],
			limit_page_length=0,
		)
		if len(rejected) == 1:
			rejected_row = rejected[0]
			if frappe.db.get_value("Purchase Receipt", rejected_row.parent, "is_return"):
				raise ValueError("A return receipt cannot classify original rejected stock.")
			entries = frappe.get_all(
				"Serial and Batch Entry",
				filters={"parent": rejected_row.rejected_serial_and_batch_bundle},
				fields=["serial_no", "batch_no", "qty"],
				limit_page_length=0,
			)
			validate_rejected_bundle(serial, rejected_row, entries)
			raise RejectedStockWithoutWeight(rejected_row)
	if len(receipts) != 1:
		raise ValueError(f"Expected one original submitted receipt; found {len(receipts)}.")
	receipt = receipts[0]
	if frappe.db.get_value("Purchase Receipt", receipt.parent, "is_return"):
		raise ValueError("A return receipt cannot supply the missing original weight.")
	entries = frappe.get_all(
		"Serial and Batch Entry",
		filters={"parent": receipt.serial_and_batch_bundle},
		fields=["serial_no", "batch_no", "qty"],
		limit_page_length=0,
	)
	return receipt_bundle_weight(serial, receipt, entries), receipt


def available_fields(doctype, fields):
	return [
		field
		for field in fields
		if field in ("name", "parent", "docstatus") or frappe.db.has_column(doctype, field)
	]


def run(dry_run=True):
	if isinstance(dry_run, str):
		dry_run = dry_run.lower() not in ("false", "0")
	if "erpnext_ui" not in frappe.get_installed_apps():
		raise ValueError("Install and migrate erpnext_ui before retiring per-kg pricing.")
	for dt in PARENTS:
		for field in (
			"custom_rate_per_pricing_uom",
			"custom_chargeable_qty",
			"custom_pricing_snapshot",
			"custom_pricing_uom",
		):
			if not frappe.db.has_column(dt, field):
				raise ValueError(f"Migrate ERP UI first: {dt}.{field} is missing.")
	updates, errors, items, serial_updates = [], [], {}, []
	recovered_weights = []
	rejected_without_weight = []
	old_enabled = frappe.db.get_single_value("Plate Settings", "enable_weight_based_purchasing")
	if old_enabled:
		from erpnext_ui.uom_pricing import is_uom_pricing_enabled

		if not is_uom_pricing_enabled("buying"):
			errors.append(
				"Enable ERP UI UOM pricing and buying pricing before retiring the active Kg workflow."
			)
	weighed_groups = (
		set(
			frappe.get_all(
				"Item Group", filters={"custom_is_weighed_grade": 1}, pluck="name", limit_page_length=0
			)
		)
		if frappe.db.has_column("Item Group", "custom_is_weighed_grade")
		else set()
	)

	def item_data(name):
		if name not in items:
			items[name] = frappe.get_doc("Item", name)
		return items[name]

	for doctype in PARENTS:
		if not frappe.db.has_column(doctype, "custom_rate_per_kg"):
			continue
		fields = available_fields(
			doctype,
			[
				"name",
				"parent",
				"docstatus",
				"item_code",
				"qty",
				"amount",
				"custom_rate_per_kg",
				"custom_billable_weight_kg",
				"custom_est_weight_kg",
				"custom_unit_weight_kg",
				"custom_rate_per_pricing_uom",
				"custom_pricing_snapshot",
			],
		)
		for row in frappe.get_all(
			doctype, filters={"custom_rate_per_kg": [">", 0]}, fields=fields, limit_page_length=0
		):
			try:
				values = row_conversion(row, item_data(row.item_code))
				if values:
					updates.append((doctype, row.name, values))
			except (ValueError, TypeError) as exc:
				errors.append(
					f"{doctype} {row.name} ({row.parent}): {exc} "
					f"[qty={row.get('qty')!r}, amount={row.get('amount')!r}, "
					f"rate_per_kg={row.get('custom_rate_per_kg')!r}, "
					f"billable_kg={row.get('custom_billable_weight_kg')!r}, "
					f"estimated_kg={row.get('custom_est_weight_kg')!r}]"
				)

	# A serial is the authoritative per-piece measurement, including historical
	# offcuts. Existing snapshots are immutable and are never rebuilt from Item rules.
	if frappe.db.has_column("Serial No", "custom_offcut_pricing_snapshot"):
		fields = available_fields(
			"Serial No",
			[
				"name",
				"item_code",
				"status",
				"warehouse",
				"custom_weight_kg",
				"purchase_rate",
				"batch_no",
				"custom_offcut_pricing_snapshot",
			],
		)
		for serial in frappe.get_all("Serial No", fields=fields, limit_page_length=0):
			if serial.get("custom_offcut_pricing_snapshot"):
				continue
			item = item_data(serial.item_code)
			if not (
				serial.get("custom_weight_kg")
				or item.get("custom_is_offcut")
				or item.get("custom_is_remainder")
				or item.get("item_group") in weighed_groups
			):
				continue
			try:
				recovered = None
				if not serial.get("custom_weight_kg") and not (
					item.get("custom_is_offcut") or item.get("custom_is_remainder")
				):
					weight, receipt = recover_serial_weight(serial)
					recovered = {
						"serial": serial.name,
						"receipt": receipt.parent,
						"receipt_row": receipt.name,
						"weight_kg": weight,
					}
				else:
					weight = positive(serial.get("custom_weight_kg"), "Recorded serial weight Kg")
				snapshot = frozen_kg_snapshot(
					weight, 1, weight, item.get("custom_length_mm"), item.get("custom_width_mm")
				)
				snapshot.update(
					quantity=weight, cost_per_uom=float(serial.get("purchase_rate") or 0) / weight
				)
				if recovered:
					recovered_weights.append(recovered)
				serial_updates.append(
					(
						"Serial No",
						serial.name,
						{
							**({"custom_weight_kg": weight} if recovered else {}),
							"custom_offcut_pricing_uom": "Kg",
							"custom_offcut_pricing_qty": weight,
							"custom_offcut_pricing_snapshot": json.dumps(snapshot),
						},
					)
				)
				if serial.get("warehouse") and serial.get("status") == "Active" and item.stock_uom != "Nos":
					raise ValueError(
						"Active plate serial stock UOM is not Nos; verify its per-stock-unit measurement explicitly."
					)
			except RejectedStockWithoutWeight as exc:
				rejected_without_weight.append(
					{
						"serial": serial.name,
						"receipt": exc.receipt.parent,
						"receipt_row": exc.receipt.name,
						"reason": str(exc),
					}
				)
			except (ValueError, TypeError) as exc:
				if serial.get("warehouse") and serial.get("status") == "Active":
					errors.append(f"Serial {serial.name}: {exc}")

	# Batch metadata is a per-piece display fallback. Only stamp a homogeneous
	# batch; differently measured pieces retain their authoritative serial snapshots.
	batch_updates, mixed_batches = [], []
	if frappe.db.has_column("Batch", "custom_offcut_pricing_snapshot"):
		batches = {}
		for _, serial_name, values in serial_updates:
			batch = frappe.db.get_value("Serial No", serial_name, "batch_no")
			if batch:
				batches.setdefault(batch, []).append(values)
		for batch, records in batches.items():
			if frappe.db.get_value("Batch", batch, "custom_offcut_pricing_snapshot"):
				continue
			first = {key: value for key, value in records[0].items() if key != "custom_weight_kg"}
			if any(
				{key: value for key, value in record.items() if key != "custom_weight_kg"} != first
				for record in records[1:]
			):
				mixed_batches.append(batch)
				continue
			batch_updates.append(("Batch", batch, first))

	groups = []
	if frappe.db.has_column("Item Group", "custom_is_weighed_grade"):
		from erpnext_ui.uom_pricing import get_pricing_rule

		for group in frappe.get_all(
			"Item Group", filters={"custom_is_weighed_grade": 1}, pluck="name", limit_page_length=0
		):
			try:
				if not get_pricing_rule(group):
					if frappe.db.exists("UI Uom Pricing Rule", f"{group}-Kg"):
						raise ValueError(
							"An inactive Kg rule exists; review and enable the intended rule before migration."
						)
					groups.append(group)
			except ValueError as exc:
				errors.append(f"Item Group {group}: {exc}")
	report = {
		"dry_run": bool(dry_run),
		"transaction_rows": len(updates),
		"serials": len(serial_updates),
		"recovered_serial_weights": recovered_weights,
		"rejected_serials_without_weight": rejected_without_weight,
		"batches": len(batch_updates),
		"mixed_batches_using_serial_snapshots": mixed_batches,
		"groups_requiring_kg_rule": groups,
		"conflicts": errors,
	}
	if dry_run:
		return report
	if errors:
		# Keep the first conflict on the exception line: log viewers can omit
		# continuation lines, otherwise showing only an empty heading.
		raise ValueError(
			f"Per-UOM migration needs review (no data changed; {len(errors)} conflict(s)): "
			+ " | ".join(errors[:50])
		)

	# Missing groups receive an explicit Direct Entry Kg rule. No density or
	# current Item formula is guessed for future commercial transactions.
	for group in groups:
		frappe.get_doc(
			{
				"doctype": "UI Uom Pricing Rule",
				"item_group": group,
				"enabled": 1,
				"pricing_uom": "Kg",
				"formula_mode": "Direct Entry",
				"receiving_strategy": "Supplier Measurement",
			}
		).insert(ignore_permissions=True)
	for doctype, name, values in updates + serial_updates + batch_updates:
		values = {key: value for key, value in values.items() if frappe.db.has_column(doctype, key)}
		frappe.db.set_value(doctype, name, values, update_modified=False)
	old_enabled = frappe.db.get_single_value("Plate Settings", "enable_weight_based_purchasing")
	if old_enabled:
		frappe.db.set_single_value("Plate Settings", "require_heat_number", 1)
	frappe.db.set_single_value("Plate Settings", "enable_weight_based_purchasing", 0)
	for field in frappe.get_all("Custom Field", fields=["name", "fieldname", "dt"], limit_page_length=0):
		if field.fieldname in ARCHIVED_FIELDS and (field.dt in PARENTS or field.dt in PARENTS.values()):
			frappe.db.set_value("Custom Field", field.name, {"hidden": 1, "read_only": 1, "in_list_view": 0})
	frappe.clear_cache()
	return report
