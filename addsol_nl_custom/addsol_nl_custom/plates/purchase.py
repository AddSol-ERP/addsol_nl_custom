# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Weight based pricing on Purchase Orders, Receipts and Invoices.

The rule the whole design rests on: a plate line is priced by weight, not by
piece. Amount = accepted weight x rate per kg, and the rate per piece is then
just amount divided by the plate count.

Everything here stands down while Plate Settings.enable_weight_based_purchasing
is off, so a half-finished deployment cannot move money. That is checked once
per document rather than per row.
"""

import frappe
from frappe import _

from addsol_nl_custom.addsol_nl_custom.plates.grouping import is_weighed_item
from addsol_nl_custom.addsol_nl_custom.plates.settings import get_setting, is_enabled
from addsol_nl_custom.addsol_nl_custom.plates.utils import round_half_up

AMOUNT_TOLERANCE = 0.05
WEIGHT_PRECISION = 3
RATE_PRECISION = 6

ACCEPT_SUPPLIER = "Accept Supplier Weight"
ACCEPT_ESTIMATED = "Accept Estimated Weight"
ACCEPT_WEIGHBRIDGE = "Accept Weighbridge Weight"


# --------------------------------------------------------------------- helpers


def tolerance_pct():
	return frappe.utils.flt(get_setting("weight_tolerance_pct", 10))


def plate_rows(doc):
	"""The weighed lines on a purchase document."""
	return [row for row in doc.get("items", []) if row.get("custom_is_plate")]


def mark_plate_rows(doc) -> None:
	for row in doc.get("items", []):
		row.custom_is_plate = 1 if is_weighed_item(row.get("item_code")) else 0


def require_nos(doc, row) -> None:
	uom = row.get("uom") or row.get("stock_uom")
	if uom and uom != "Nos":
		frappe.throw(
			_("Row {0} of {1}: plate stock is counted in Nos, but this line uses {2}.").format(
				row.idx, doc.name, uom
			),
			title=_("Wrong unit of measure"),
		)

	conversion_factor = frappe.utils.flt(row.get("conversion_factor"), 1) or 1
	if conversion_factor != 1:
		frappe.throw(
			_(
				"Row {0} of {1}: plate stock is counted in Nos, so the conversion factor must be 1, not {2}."
			).format(row.idx, doc.name, conversion_factor),
			title=_("Wrong conversion factor"),
		)


def apply_amount(doc, row, billable_kg) -> None:
	"""Price a line by weight and derive the rate per piece from it."""
	rate_per_kg = frappe.utils.flt(row.get("custom_rate_per_kg"))
	qty = frappe.utils.flt(row.get("qty"))

	if not rate_per_kg or not qty:
		return

	target_amount = round_half_up(billable_kg * rate_per_kg, 2)
	rate = round_half_up(target_amount / qty, RATE_PRECISION)

	row.rate = rate
	row.price_list_rate = rate
	row.discount_percentage = 0
	row.discount_amount = 0

	if row.meta.get_field("custom_weight_per_plate_kg"):
		row.custom_weight_per_plate_kg = round_half_up(billable_kg / qty, WEIGHT_PRECISION)


def sum_header(doc, fieldname, rows) -> None:
	if doc.meta.get_field(fieldname):
		doc.set(
			fieldname, round_half_up(sum(frappe.utils.flt(r.get(fieldname)) for r in rows), WEIGHT_PRECISION)
		)


def assert_amount_reconciles(doc, row) -> None:
	"""amount must equal accepted weight x rate per kg, within a few paise."""
	amount = frappe.utils.flt(row.get("amount"))
	expected = round_half_up(
		frappe.utils.flt(row.get("custom_billable_weight_kg"))
		* frappe.utils.flt(row.get("custom_rate_per_kg")),
		2,
	)

	if abs(amount - expected) > AMOUNT_TOLERANCE:
		frappe.throw(
			_(
				"Row {0} of {1}: the amount does not reconcile with the accepted weight. "
				"Line amount is {2}, but accepted weight x rate per kg is {3}. A difference "
				"over {4} means the rate has been rounded too far."
			).format(row.idx, doc.name, amount, expected, AMOUNT_TOLERANCE),
			title=_("Amount does not match the weight"),
		)


# ------------------------------------------------------------- Purchase Order


def po_before_validate(doc, method=None) -> None:
	mark_plate_rows(doc)

	if not is_enabled():
		return

	rows = plate_rows(doc)
	if not rows:
		return

	for row in rows:
		require_nos(doc, row)
		set_po_weights(doc, row)
		set_po_rate(doc, row)

	sum_header(doc, "custom_total_est_weight_kg", rows)


def set_po_weights(doc, row) -> None:
	"""Theoretical weight per plate, then the line's estimated weight."""
	row.custom_unit_weight_kg = frappe.utils.flt(row.get("item_weight_per_unit")) or frappe.utils.flt(
		frappe.db.get_value("Item", row.get("item_code"), "weight_per_unit")
	)
	row.custom_est_weight_kg = round_half_up(
		frappe.utils.flt(row.get("qty")) * frappe.utils.flt(row.get("custom_unit_weight_kg")),
		WEIGHT_PRECISION,
	)


def set_po_rate(doc, row) -> None:
	"""The rate per kg comes from the supplier's grade table and is fixed here."""
	if not row.get("custom_rate_per_kg") or row.get("items_changed"):
		row.custom_rate_per_kg = lookup_supplier_rate(doc, row)

	if not row.get("custom_rate_per_kg"):
		frappe.throw(
			_(
				"Row {0} of {1}: no rate per kg for {2}. Add it to this supplier's Grade Rates, "
				"or type it on the line."
			).format(row.idx, doc.name, row.get("item_group") or row.get("item_code")),
			title=_("No rate per kg"),
		)

	apply_amount(doc, row, frappe.utils.flt(row.get("custom_est_weight_kg")))


def lookup_supplier_rate(doc, row):
	"""The supplier's rate for this grade, valid on the order's date."""
	from addsol_nl_custom.addsol_nl_custom.plates.supplier_rates import find_rate

	return find_rate(
		doc.get("supplier"), row.get("item_group"), doc.get("transaction_date") or doc.get("schedule_date")
	)


# ---------------------------------------------------------- Purchase Receipt


def pr_before_validate(doc, method=None) -> None:
	mark_plate_rows(doc)

	if not is_enabled():
		return

	rows = plate_rows(doc)
	if not rows:
		return

	for row in rows:
		require_nos(doc, row)
		copy_rate_from_order(doc, row)
		set_receipt_weights(doc, row)
		resolve_billable_weight(doc, row)

	sum_header(doc, "custom_total_est_weight_kg", rows)
	sum_header(doc, "custom_total_billable_weight_kg", rows)


def copy_rate_from_order(doc, row) -> None:
	"""The rate per kg was fixed at the order and must not drift."""
	order_row = linked_order_row(row)
	if not order_row:
		return

	order_rate = frappe.utils.flt(order_row.get("custom_rate_per_kg"))
	line_rate = frappe.utils.flt(row.get("custom_rate_per_kg"))

	if not order_rate:
		frappe.throw(
			_("Row {0} of {1} links to a Purchase Order line with no rate per kg.").format(row.idx, doc.name),
			title=_("No rate per kg on the order"),
		)

	if line_rate and abs(line_rate - order_rate) > 0.0001:
		frappe.throw(
			_(
				"Row {0} of {1}: the rate per kg is {2} but the Purchase Order fixed it at {3}. "
				"The rate is agreed at the order and does not change on receipt."
			).format(row.idx, doc.name, line_rate, order_rate),
			title=_("Rate per kg does not match the order"),
		)

	row.custom_rate_per_kg = order_rate


def linked_order_row(row):
	if not row.get("purchase_order_item"):
		return None
	return frappe.db.get_value(
		"Purchase Order Item",
		row.get("purchase_order_item"),
		["custom_rate_per_kg", "custom_unit_weight_kg"],
		as_dict=True,
	)


def set_receipt_weights(doc, row) -> None:
	if not row.get("custom_unit_weight_kg"):
		row.custom_unit_weight_kg = frappe.utils.flt(row.get("item_weight_per_unit")) or frappe.utils.flt(
			frappe.db.get_value("Item", row.get("item_code"), "weight_per_unit")
		)

	row.custom_est_weight_kg = round_half_up(
		frappe.utils.flt(row.get("qty")) * frappe.utils.flt(row.get("custom_unit_weight_kg")),
		WEIGHT_PRECISION,
	)

	supplier_weight = frappe.utils.flt(row.get("custom_supplier_weight_kg"))
	estimated = frappe.utils.flt(row.get("custom_est_weight_kg"))
	row.custom_variance_pct = (
		round_half_up((supplier_weight - estimated) / estimated * 100, 2)
		if estimated and supplier_weight
		else 0
	)


def resolve_billable_weight(doc, row) -> None:
	"""Decide which weight this line is paid on.

	Within tolerance the supplier's weight wins. Above it the line waits until
	somebody with the approver role picks one.
	"""
	estimated = frappe.utils.flt(row.get("custom_est_weight_kg"))
	supplier = frappe.utils.flt(row.get("custom_supplier_weight_kg"))
	weighbridge = frappe.utils.flt(row.get("custom_weighbridge_weight_kg"))
	decision = row.get("custom_weight_decision")

	billable = 0.0

	if not supplier:
		# No weight given at all. Allowed in draft, refused on submit.
		billable = 0.0

	elif abs(row.get("custom_variance_pct")) <= tolerance_pct():
		billable = supplier
		row.custom_weight_decision = None

	elif decision == ACCEPT_SUPPLIER:
		billable = supplier

	elif decision == ACCEPT_ESTIMATED:
		billable = estimated

	elif decision == ACCEPT_WEIGHBRIDGE:
		if weighbridge <= 0:
			frappe.throw(
				_(
					"Row {0} of {1}: the decision is '{2}', but no weighbridge weight has been entered."
				).format(row.idx, doc.name, ACCEPT_WEIGHBRIDGE),
				title=_("Weighbridge weight missing"),
			)
		billable = weighbridge

	else:
		billable = 0.0  # above tolerance, waiting for a decision

	row.custom_billable_weight_kg = round_half_up(billable, WEIGHT_PRECISION)

	if billable > 0:
		apply_amount(doc, row, billable)


def pr_before_submit(doc, method=None) -> None:
	if not is_enabled():
		return

	rows = plate_rows(doc)
	if not rows:
		return

	approver_role = get_setting("approver_role")

	for row in rows:
		reason = blocked_reason(doc, row, approver_role)
		if reason:
			frappe.throw(
				_("Row {0} of {1} cannot be submitted: {2}").format(row.idx, doc.name, reason),
				title=_("Receipt line is not ready"),
			)

	sum_header(doc, "custom_total_est_weight_kg", rows)
	sum_header(doc, "custom_total_billable_weight_kg", rows)


def blocked_reason(doc, row, approver_role) -> str:
	billable = frappe.utils.flt(row.get("custom_billable_weight_kg"))

	if billable <= 0:
		if not frappe.utils.flt(row.get("custom_supplier_weight_kg")):
			return _("the supplier's weight has not been entered.")
		return _("the variance is above tolerance and nobody has chosen which weight to accept.")

	if not row.get("custom_heat_number"):
		return _("the heat number is missing. One receipt line is one heat number.")

	if row.get("custom_weight_decision") and approver_role:
		if approver_role not in frappe.get_roles():
			return _("the accepted weight was decided by someone without the {0} role.").format(approver_role)

	return None


# ---------------------------------------------------------- Purchase Invoice


def pi_before_validate(doc, method=None) -> None:
	mark_plate_rows(doc)

	if not is_enabled():
		return

	rows = plate_rows(doc)
	if not rows:
		return

	for row in rows:
		if row.get("purchase_order_item"):
			check_invoice_against_receipt(doc, row)
		else:
			apply_receipt_rules(doc, row)

	sum_header(doc, "custom_total_billable_weight_kg", rows)


def check_invoice_against_receipt(doc, row) -> None:
	"""An invoice made from a receipt must carry its weight and rate across."""
	receipt_row = frappe.db.get_value(
		"Purchase Receipt Item",
		row.get("purchase_receipt_item"),
		["custom_rate_per_kg", "custom_billable_weight_kg"],
		as_dict=True,
	)

	if receipt_row and receipt_row.get("custom_rate_per_kg"):
		line_rate = frappe.utils.flt(row.get("custom_rate_per_kg"))
		receipt_rate = frappe.utils.flt(receipt_row.get("custom_rate_per_kg"))

		if line_rate and abs(line_rate - receipt_rate) > 0.0001:
			frappe.throw(
				_(
					"Row {0} of {1}: the rate per kg is {2} but the receipt recorded {3}. The rate "
					"is fixed at the order and cannot be changed on the invoice."
				).format(row.idx, doc.name, line_rate, receipt_rate),
				title=_("Rate per kg does not match the receipt"),
			)

		row.custom_rate_per_kg = receipt_rate

	if not row.get("custom_billable_weight_kg") and receipt_row:
		row.custom_billable_weight_kg = receipt_row.get("custom_billable_weight_kg")

	assert_amount_reconciles(doc, row)


def apply_receipt_rules(doc, row) -> None:
	"""A line with no receipt behind it cannot be priced by weight."""
	if not row.get("update_stock"):
		frappe.throw(
			_(
				"Row {0} of {1} is a plate line with no Purchase Receipt behind it. Create the "
				"invoice from the receipt so the weight carries across."
			).format(row.idx, doc.name),
			title=_("Create the invoice from a Purchase Receipt"),
		)

	require_nos(doc, row)
	set_receipt_weights(doc, row)
	resolve_billable_weight(doc, row)
