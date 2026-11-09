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


def positive(value):
	number = float(value or 0)
	if not math.isfinite(number) or number <= 0:
		raise ValueError("A positive, finite quantity/rate is required.")
	return number


def frozen_kg_snapshot(quantity, stock_units, nominal_per_unit, length=0, width=0):
	"""Freeze measured Kg with source geometry; never use today's pricing UOM."""
	quantity, units = positive(quantity), positive(stock_units)
	nominal = positive(nominal_per_unit or quantity / units)
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
	rate, qty = positive(row["custom_rate_per_kg"]), positive(abs(float(row.get("qty") or 0)))
	amount = abs(float(row.get("amount") or 0))
	measured = float(row.get("custom_billable_weight_kg") or row.get("custom_est_weight_kg") or 0)
	if amount:
		if measured and not math.isclose(amount, measured * rate, abs_tol=0.05, rel_tol=1e-7):
			raise ValueError("Booked amount does not reconcile with the stored weight and per-kg rate.")
		measured = amount / rate
	measured = positive(measured)
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
				errors.append(f"{doctype} {row.name} ({row.parent}): {exc}")

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
				weight = positive(serial.get("custom_weight_kg"))
				snapshot = frozen_kg_snapshot(
					weight, 1, weight, item.get("custom_length_mm"), item.get("custom_width_mm")
				)
				snapshot.update(
					quantity=weight, cost_per_uom=float(serial.get("purchase_rate") or 0) / weight
				)
				serial_updates.append(
					(
						"Serial No",
						serial.name,
						{
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
			first = records[0]
			if any(record != first for record in records[1:]):
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
		"batches": len(batch_updates),
		"mixed_batches_using_serial_snapshots": mixed_batches,
		"groups_requiring_kg_rule": groups,
		"conflicts": errors,
	}
	if dry_run:
		return report
	if errors:
		raise ValueError("Per-UOM migration needs review (no data changed):\n" + "\n".join(errors[:50]))

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
