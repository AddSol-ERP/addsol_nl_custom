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
	apply_update_dialog_rates(doc)
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


def apply_update_dialog_rates(doc) -> None:
	"""Apply rates from ERPNext's Update Items request before PO repricing."""
	context = getattr(frappe.flags, "addsol_po_update_rates", None) or {}
	requested = context.get("rates", [])
	existing_names = context.get("existing_names", set())
	used = set()
	for row in doc.get("items", []):
		for index, item in enumerate(requested):
			if index in used or item.get("item_code") != row.get("item_code"):
				continue
			if item.get("docname"):
				if item.get("docname") != row.get("name"):
					continue
			elif row.get("name") in existing_names:
				continue
			if not is_weighed_item(row.get("item_code")):
				continue
			row.custom_is_plate = 1
			row.custom_rate_per_kg = frappe.utils.flt(item.get("custom_rate_per_kg"))
			used.add(index)
			break


@frappe.whitelist()
def update_child_qty_rate(parent_doctype, trans_items, parent_doctype_name, child_docname="items"):
	"""Keep the per-kg rate when ERPNext's submitted-document dialog updates a PO.

	The standard Update Items dialog sends only the ordinary unit rate. Its
	client is extended by purchase_weight_pricing.js to include
	``custom_rate_per_kg``. The request-local rates are applied by
	``po_before_validate`` during ERPNext's normal parent save, before the PO
	pricing hook derives the line amount.
	"""
	from erpnext.controllers.accounts_controller import update_child_qty_rate as core_update

	if parent_doctype != "Purchase Order" or not is_enabled():
		return core_update(parent_doctype, trans_items, parent_doctype_name, child_docname)

	items = frappe.parse_json(trans_items) or []
	requested_rates = [
		row for row in items
		if frappe.utils.flt(row.get("custom_rate_per_kg")) > 0
		and row.get("item_code")
		and is_weighed_item(row.get("item_code"))
	]
	if not requested_rates:
		return core_update(parent_doctype, trans_items, parent_doctype_name, child_docname)

	parent = frappe.get_doc(parent_doctype, parent_doctype_name)
	existing_names = {row.name for row in parent.get(child_docname, [])}
	frappe.flags.addsol_po_update_rates = {
		"rates": requested_rates,
		"existing_names": existing_names,
	}
	try:
		result = core_update(parent_doctype, trans_items, parent_doctype_name, child_docname)
	finally:
		frappe.flags.pop("addsol_po_update_rates", None)

	# The standard endpoint skips rows whose qty/unit rate did not change, even
	# when their per-kg rate did. Persist the submitted rate values explicitly
	# after its save; the request-local hook above lets new plate rows pass their
	# first PO validation even when there is no historical rate yet.
	parent = frappe.get_doc(parent_doctype, parent_doctype_name)
	new_rows_by_item = {}
	for row in parent.get(child_docname, []):
		if row.name not in existing_names:
			new_rows_by_item.setdefault(row.item_code, []).append(row)

	for requested in requested_rates:
		row = next(
			(
				child for child in parent.get(child_docname, [])
				if requested.get("docname") and child.name == requested.get("docname")
			),
			None,
		)
		if not row:
			candidates = new_rows_by_item.get(requested.get("item_code"), [])
			row = candidates.pop(0) if candidates else None
		if not row:
			continue

		row.custom_is_plate = 1
		row.custom_rate_per_kg = frappe.utils.flt(requested.get("custom_rate_per_kg"))
		set_line_weights(parent, row)
		apply_amount(parent, row, row.custom_est_weight_kg)
		row.flags.ignore_validate_update_after_submit = True
		row.save(ignore_permissions=True)

	parent.reload()
	parent.flags.ignore_validate_update_after_submit = True
	parent.save(ignore_permissions=True)
	return result


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

	Same rule as the Purchase Order. The supplier can type the rate per kg
	directly; if they instead enter a per-plate rate, derive the rate per kg
	from it. The Purchase Order built from the quotation inherits that rate.

	The quotation is not the place to insist on a price: a quote is often
	raised before the supplier has answered, so a line with neither rate is
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
	"""Use the entered rate per kg, or derive it from the quoted per-piece rate.

	When the supplier supplies a rate per kg, it is authoritative and the
	per-piece rate follows from the estimated weight. If only a per-piece rate
	is supplied, the known plate weight gives us a rate per kg instead.

	The quotation and the Purchase Order then price the same estimated weight
	with the same stored rate per kg.
	"""
	unit_weight = frappe.utils.flt(row.get("custom_unit_weight_kg"))
	quoted_rate = frappe.utils.flt(row.get("rate"))
	rate_per_kg = frappe.utils.flt(row.get("custom_rate_per_kg"))
	if not rate_per_kg and unit_weight and quoted_rate:
		rate_per_kg = round_half_up(quoted_rate / unit_weight, RATE_PER_KG_PRECISION)
		row.custom_rate_per_kg = rate_per_kg

	if not rate_per_kg:
		# No price yet, or a plate with no weight to derive one from.
		return

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
	"""Default the receipt rate from its PO, preserving a receiving override."""
	order_row = linked_order_row(row)
	if not order_row:
		return

	if not frappe.utils.flt(row.get("custom_rate_per_kg")):
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
