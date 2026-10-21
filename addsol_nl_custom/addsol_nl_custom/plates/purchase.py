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
from addsol_nl_custom.addsol_nl_custom.plates.rate_history import last_rate
from addsol_nl_custom.addsol_nl_custom.plates.settings import get_setting, is_enabled
from addsol_nl_custom.addsol_nl_custom.plates.utils import round_half_up

AMOUNT_TOLERANCE = 0.05
WEIGHT_PRECISION = 3
RATE_PRECISION = 6

# The rate per kg is stored at four decimals, so the figure worked out from a
# quoted rate is rounded to the same four. Anything more would be thrown away
# when the value is stored, and the Purchase Order that inherits it would
# price the line differently from the quotation it came from.
RATE_PER_KG_PRECISION = 4

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


def sum_header(doc, fieldname, rows, row_fieldname) -> None:
	"""The header total, from the row figures.

	`fieldname` is the header field and `row_fieldname` the row figure it
	totals: the header's `custom_total_est_weight_kg` is the sum of the rows'
	`custom_est_weight_kg`.

	Reading the row under the header's OWN name summed nothing, because no
	row carries that name - so "Total Estimated Weight" and "Total Accepted
	Weight" have been reading zero on every Purchase Order, Receipt and
	Invoice since they were added. The fields are display only; nothing
	reads them, so filling them in properly changes nothing else.
	"""
	if not doc.meta.get_field(fieldname):
		return

	doc.set(
		fieldname,
		round_half_up(sum(frappe.utils.flt(r.get(row_fieldname)) for r in rows), WEIGHT_PRECISION),
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
		set_line_weights(doc, row)
		set_po_rate(doc, row)

	sum_header(doc, "custom_total_est_weight_kg", rows, "custom_est_weight_kg")


def set_line_weights(doc, row) -> None:
	"""Theoretical weight per plate, then the line's estimated weight.

	The same two figures on a Purchase Order and on a Supplier Quotation, so
	that a line priced on the quotation and the same line priced on the order
	come to the same amount.
	"""
	row.custom_unit_weight_kg = frappe.utils.flt(row.get("item_weight_per_unit")) or frappe.utils.flt(
		frappe.db.get_value("Item", row.get("item_code"), "weight_per_unit")
	)
	row.custom_est_weight_kg = round_half_up(
		frappe.utils.flt(row.get("qty")) * frappe.utils.flt(row.get("custom_unit_weight_kg")),
		WEIGHT_PRECISION,
	)


def set_po_rate(doc, row) -> None:
	"""The rate per kg is the buyer's to enter, and nothing here overwrites it.

	When the line is still empty we hand it the last rate agreed for this item,
	so a repeat order does not start from nothing. A figure someone typed is
	left exactly as it is, including when the items grid is edited again.
	"""
	if not row.get("custom_rate_per_kg"):
		row.custom_rate_per_kg = last_rate(row.get("item_code"), doc.get("supplier"))

	if not row.get("custom_rate_per_kg"):
		frappe.throw(
			_("Row {0} of {1}: enter a rate per kg for {2}.").format(row.idx, doc.name, row.get("item_code")),
			title=_("No rate per kg"),
		)

	apply_amount(doc, row, frappe.utils.flt(row.get("custom_est_weight_kg")))


# --------------------------------------------------------- Supplier Quotation


def sq_before_validate(doc, method=None) -> None:
	"""Price a plate line on a Supplier Quotation by weight.

	Same rule as the Purchase Order, and one difference in where the price
	comes from. On an order the buyer types the rate per kg. On a quotation it
	is WORKED OUT from the quoted rate, because the supplier quotes a price per
	plate and the plate's weight is known. The Purchase Order built from the
	quotation inherits the figure, so nobody types the price twice.

	The quotation is not the place to insist on a price: a quote is often
	raised before the supplier has answered, so a line with no quoted rate is
	left alone. The Purchase Order is where the price is demanded.
	"""
	mark_plate_rows(doc)

	if not is_enabled():
		return

	rows = plate_rows(doc)
	if not rows:
		return

	for row in rows:
		require_nos(doc, row)
		set_line_weights(doc, row)
		set_sq_rate(doc, row)

	sum_header(doc, "custom_total_est_weight_kg", rows, "custom_est_weight_kg")


def set_sq_rate(doc, row) -> None:
	"""The rate per kg, worked out from the quoted rate, and the line priced by weight.

	The quoted rate is per plate and the plate's weight is known, so the two
	give the price per kg. The line is then priced the way a Purchase Order
	line is priced: the amount is the estimated weight times the rate per kg,
	and the per-piece rate follows from that.

	The two documents therefore agree exactly, because they price the same
	weights with the same stored rate per kg. What the supplier quoted and
	what the weight pricing gives can differ by a paisa or two - the rate per
	kg is stored at four decimals and a plate weighs a quarter of a tonne -
	and the quotation carries the weight figure, not the supplier's arithmetic.
	"""
	unit_weight = frappe.utils.flt(row.get("custom_unit_weight_kg"))
	quoted_rate = frappe.utils.flt(row.get("rate"))

	if not unit_weight or not quoted_rate:
		# No price yet, or a plate with no weight to work the price from.
		return

	row.custom_rate_per_kg = round_half_up(quoted_rate / unit_weight, RATE_PER_KG_PRECISION)

	apply_amount(doc, row, frappe.utils.flt(row.get("custom_est_weight_kg")))


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

	sum_header(doc, "custom_total_est_weight_kg", rows, "custom_est_weight_kg")
	sum_header(doc, "custom_total_billable_weight_kg", rows, "custom_billable_weight_kg")


def copy_rate_from_order(doc, row) -> None:
	"""A receipt is priced at the rate the order agreed.

	The rate per kg is not typed on a receipt, so there is nothing to reconcile:
	the order's figure simply stands. If the order line has no rate at all that
	is a gap in the order, and it is worth saying so.
	"""
	order_row = linked_order_row(row)
	if not order_row:
		return

	order_rate = frappe.utils.flt(order_row.get("custom_rate_per_kg"))
	if not order_rate:
		frappe.throw(
			_("Row {0} of {1} links to a Purchase Order line with no rate per kg.").format(row.idx, doc.name),
			title=_("No rate per kg on the order"),
		)

	row.custom_rate_per_kg = order_rate
	# ERPNext's Purchase Receipt mapper does not always carry custom fields from
	# the Purchase Order Item. Use the committed PO weight as a fallback before
	# set_receipt_weights() falls back to Item.weight_per_unit. Preserve a value
	# already present on the receipt row so an explicit receipt value wins.
	if not frappe.utils.flt(row.get("custom_unit_weight_kg")):
		row.custom_unit_weight_kg = frappe.utils.flt(order_row.get("custom_unit_weight_kg"))


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
	measured_weight = supplier_weight or frappe.utils.flt(row.get("custom_weighbridge_weight_kg"))
	estimated = frappe.utils.flt(row.get("custom_est_weight_kg"))
	row.custom_variance_pct = (
		round_half_up((measured_weight - estimated) / estimated * 100, 2)
		if estimated and measured_weight
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

	if not supplier and weighbridge and abs(row.get("custom_variance_pct")) <= tolerance_pct():
		# Truck net weight can be allocated over eligible lines when the supplier
		# does not provide per-item weights. This remains a weighbridge reading.
		billable = weighbridge
		row.custom_weight_decision = None

	elif not supplier and not weighbridge:
		# No measured weight given at all. Allowed in draft, refused on submit.
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

	truck_net = frappe.utils.flt(doc.get("custom_truck_net_weight_kg"))
	if truck_net > 0:
		allocated = round_half_up(
			sum(frappe.utils.flt(row.get("custom_weighbridge_weight_kg")) for row in rows),
			WEIGHT_PRECISION,
		)
		if abs(allocated - truck_net) > 0.002:
			frappe.throw(
				_("The allocated weighbridge weights ({0} Kg) must equal the truck net weight ({1} Kg).")
				.format(allocated, truck_net),
				title=_("Truck weight is not fully allocated"),
			)

	sum_header(doc, "custom_total_est_weight_kg", rows, "custom_est_weight_kg")
	sum_header(doc, "custom_total_billable_weight_kg", rows, "custom_billable_weight_kg")


def blocked_reason(doc, row, approver_role) -> str:
	billable = frappe.utils.flt(row.get("custom_billable_weight_kg"))

	if billable <= 0:
		if not frappe.utils.flt(row.get("custom_supplier_weight_kg")) and not frappe.utils.flt(
			row.get("custom_weighbridge_weight_kg")
		):
			return _("neither a supplier weight nor a weighbridge weight has been entered.")
		return _("the variance is above tolerance and nobody has chosen which weight to accept.")

	if not frappe.utils.flt(row.get("custom_supplier_weight_kg")) and not frappe.utils.flt(
		row.get("custom_weighbridge_weight_kg")
	):
		return _("neither a supplier weight nor a weighbridge weight has been entered.")

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

	sum_header(doc, "custom_total_billable_weight_kg", rows, "custom_billable_weight_kg")


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
