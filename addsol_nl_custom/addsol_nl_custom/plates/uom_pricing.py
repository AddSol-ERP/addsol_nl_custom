"""Bridge cutting to ERP UI pricing without changing stock quantities.

Snapshots carry inventory cost in company currency, not the supplier's quoted
rate. Historical pieces receive frozen Kg snapshots during migration.
"""

import math

import frappe


def shared_pricing(item_code):
	"""Optional integration: a missing app leaves legacy sites untouched."""
	if "erpnext_ui" not in frappe.get_installed_apps():
		return None
	from erpnext_ui.uom_pricing import get_item_pricing

	pricing = get_item_pricing(item_code, "buying")
	return pricing if pricing["enabled"] else None


def receipt_snapshot(row):
	value = row.get("custom_pricing_snapshot")
	if not value:
		return None
	snapshot = frappe.parse_json(value)
	qty = float(row.get("stock_qty") or row.get("qty") or 0)
	measure = float(snapshot.get("chargeable_qty") or 0)
	if qty <= 0 or measure <= 0 or not snapshot.get("pricing_uom"):
		raise ValueError("Receipt pricing snapshot needs positive quantities and a UOM.")
	# net valuation currency already includes transaction currency conversion.
	value = row.get("base_net_amount")
	if value is None:
		raise ValueError("Receipt pricing snapshot has no company-currency net amount.")
	return {**snapshot, "quantity": measure / qty, "cost_per_uom": float(value) / measure}


def stamp_snapshot(doctype, name, snapshot):
	frappe.db.set_value(
		doctype,
		name,
		{
			"custom_offcut_pricing_snapshot": frappe.as_json(snapshot),
			"custom_offcut_pricing_uom": snapshot["pricing_uom"],
			"custom_offcut_pricing_qty": snapshot["quantity"],
		},
	)


def read_snapshot(serial_no):
	if not frappe.get_meta("Serial No").has_field("custom_offcut_pricing_snapshot"):
		return None
	value = frappe.db.get_value("Serial No", serial_no, "custom_offcut_pricing_snapshot")
	return frappe.parse_json(value) if value else None


def piece_quantity(snapshot, row, source_dimensions):
	"""Use the frozen rule with the cut dimensions, or an explicit measurement.

	Dimension parameters map through their declared Item data_source. No symbol
	names or physical density are guessed. Direct Entry needs a measure per piece.
	Circles require an area-based formula; length pricing uses Direct Entry for
	circles because pi/4 is not a length conversion.
	"""
	from erpnext_ui.uom_pricing import calculate_chargeable_quantity

	rule = snapshot["rule"]
	entered = row.get("pricing_qty")
	if rule.get("formula_mode") == "Direct Entry":
		return positive(entered, "Enter the chargeable quantity for each offcut.")
	params = dict(snapshot.get("params_by_symbol") or {})
	circle = row.get("shape") == "Circle"
	dimensions = {
		"custom_length_mm": row.get("diameter_mm") if circle else row.get("length_mm"),
		"custom_width_mm": row.get("diameter_mm") if circle else row.get("width_mm"),
	}
	mapped = set()
	for parameter in rule.get("params") or []:
		source = parameter.get("data_source")
		if source in dimensions:
			params[parameter["symbol"]] = positive(dimensions[source], "Offcut dimensions must be positive.")
			mapped.add(source)
	if not mapped:
		raise ValueError("Offcut formula needs a length or width parameter mapped to its Item field.")
	if circle and mapped != set(dimensions):
		raise ValueError(
			"Circular cuts need an area formula mapped to length and width, or Direct Entry pricing."
		)
	baseline = calculate_chargeable_quantity(rule, snapshot.get("params_by_symbol") or {})
	# The frozen source measurement calibrates nominal dimensions just as the
	# legacy actual-to-theoretical weight ratio does.
	quantity = (
		calculate_chargeable_quantity(rule, params)
		* positive(snapshot["quantity"], "Source quantity missing.")
		/ baseline
	)
	if circle:
		# pi/4 converts a bounding square's AREA. Reject formulas that use
		# both dimensions as a sum or ignore one, rather than pricing length
		# as if it were an area. Rectangle rules need no shape assumption.
		rectangular = calculate_chargeable_quantity(rule, params)
		for field in dimensions:
			changed = dict(params)
			for parameter in rule.get("params") or []:
				if parameter.get("data_source") == field:
					changed[parameter["symbol"]] *= 2
			if not math.isclose(calculate_chargeable_quantity(rule, changed), rectangular * 2, rel_tol=1e-9):
				raise ValueError("Circular cuts require an area-proportional formula or Direct Entry.")
		quantity *= math.pi / 4
	return positive(quantity, "Offcut pricing quantity must be positive.")


def positive(value, message):
	try:
		number = float(value)
	except (ValueError, TypeError):
		raise ValueError(message) from None
	if not math.isfinite(number) or number <= 0:
		raise ValueError(message)
	return number


def uses_configured_item_code(doc):
	"""An explicitly enabled shared naming rule takes over customer naming."""
	if "erpnext_ui" not in frappe.get_installed_apps():
		return False
	try:
		from erpnext_ui.item_naming import uses_configured_item_code as configured
	except ImportError:
		# Compatibility while the UI app is upgraded independently.
		return False
	return configured(doc)
