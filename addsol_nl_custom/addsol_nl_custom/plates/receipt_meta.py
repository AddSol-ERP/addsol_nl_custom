# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Stamping the receipt's weight onto the batch and the serials.

A batch is one heat number and one accepted weight. Once this has run, the
batch alone is enough to answer "how much did this lot of steel really weigh
and what did we pay per kilo", which is the whole reason for keeping plate
stock per piece but valuing it per kilo.

Every value is written with `frappe.db.set_value(..., update_modified=False)`
because the batch and serial already exist by the time a hook runs, and
touching `modified` on them would churn the stock ledger's view of them.
"""

import frappe
from frappe import _

from addsol_nl_custom.addsol_nl_custom.plates.utils import round_half_up

RATIO_PRECISION = 4
WEIGHT_PRECISION = 3


def apply_receipt_metadata(doc, method=None) -> None:
	"""Copy the weight and the rate off every weighed line onto its batch."""
	if not doc.get("docstatus"):
		return

	for row in doc.get("items", []):
		if row.get("custom_is_plate"):
			stamp_row(doc, row)


def stamp_row(receipt, row) -> None:
	"""Write this line's weight, rate and heat number onto its batch and serials."""
	bundle_entries = get_bundle_entries(row)
	if not bundle_entries:
		# Nothing was created for this line - a return, or a row without serial
		# and batch tracking. Nothing to stamp.
		return

	batch_nos = {entry.batch_no for entry in bundle_entries if entry.batch_no}

	if len(batch_nos) > 1:
		frappe.throw(
			_(
				"Row {0} of {1} produced more than one batch ({2}). One receipt line is one "
				"heat number - split it into separate lines."
			).format(row.idx, receipt.name, ", ".join(sorted(batch_nos))),
			title=_("More than one heat number on a receipt line"),
		)

	if not batch_nos:
		return

	batch_no = next(iter(batch_nos))
	heat_number = row.get("custom_heat_number")
	weight_per_plate = weight_per_plate_of(row)
	unit_weight = frappe.utils.flt(frappe.db.get_value("Item", row.get("item_code"), "weight_per_unit"))
	ratio = (
		round_half_up(weight_per_plate / unit_weight, RATIO_PRECISION)
		if unit_weight and weight_per_plate
		else 0.0
	)

	update_batch(
		batch_no,
		heat_number=heat_number,
		mtc_no=row.get("custom_mtc_no"),
		grade=grade_of(row.get("item_code")),
		weight_per_plate=weight_per_plate,
		cost_per_kg=frappe.utils.flt(row.get("custom_rate_per_kg")),
		ratio=ratio,
	)

	for serial_no in sorted({e.serial_no for e in bundle_entries if e.serial_no}):
		update_serial(serial_no, weight_per_plate, heat_number)


def weight_per_plate_of(row) -> float:
	"""Weight carried by one plate on this line.

	The receipt normally has this already. If it does not - a row typed by hand,
	or a site where the weight logic is switched off - fall back to dividing the
	accepted weight, then the estimate, by the plate count.
	"""
	weight_per_plate = frappe.utils.flt(row.get("custom_weight_per_plate_kg"))
	if weight_per_plate:
		return weight_per_plate

	qty = frappe.utils.flt(row.get("qty"))
	if not qty:
		return 0.0

	for fieldname in ("custom_billable_weight_kg", "custom_est_weight_kg"):
		total = frappe.utils.flt(row.get(fieldname))
		if total:
			return round_half_up(total / qty, WEIGHT_PRECISION)

	return 0.0


def get_bundle_entries(row):
	"""The Serial and Batch Entry rows ERPNext created for this line."""
	if not row.get("serial_and_batch_bundle"):
		return []

	return frappe.get_all(
		"Serial and Batch Entry",
		filters={
			"parent": row.get("serial_and_batch_bundle"),
			"parenttype": "Serial and Batch Bundle",
		},
		fields=["serial_no", "batch_no"],
		limit_page_length=0,
	)


def grade_of(item_code):
	if not item_code:
		return None
	return frappe.db.get_value("Item", item_code, "item_group")


def update_batch(batch_no, heat_number, mtc_no, grade, weight_per_plate, cost_per_kg, ratio) -> None:
	if not frappe.db.exists("Batch", batch_no):
		return

	frappe.db.set_value(
		"Batch",
		batch_no,
		{
			"custom_heat_number": heat_number,
			"custom_mtc_no": mtc_no,
			"custom_grade": grade,
			"custom_weight_per_plate_kg": weight_per_plate,
			"custom_cost_per_kg": cost_per_kg,
			"custom_actual_to_theoretical_ratio": ratio,
		},
		update_modified=False,
	)


def update_serial(serial_no, weight_kg, heat_number) -> None:
	if not frappe.db.exists("Serial No", serial_no):
		return

	frappe.db.set_value(
		"Serial No",
		serial_no,
		{"custom_weight_kg": weight_kg, "custom_heat_number": heat_number},
		update_modified=False,
	)
