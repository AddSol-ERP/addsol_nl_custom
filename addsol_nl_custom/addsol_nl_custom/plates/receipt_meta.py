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
	"""Copy receipt weight and cost metadata onto its batch and serials.

	Weight and cost per kg can be derived from the line's own rate and the
	plate's theoretical weight, so Plate Stock Register works before the
	pricing feature is ever switched on.

	Only the *computation* of weight-based prices is behind the flag, and that
	lives in purchase.py.
	"""
	if not doc.get("docstatus"):
		return

	should_stamp = False
	for row in doc.get("items", []):
		if row.get("custom_is_plate"):
			should_stamp = True
			stamp_row(doc, row)
	apply_quality_metadata_from_receipt(doc)

	# ERPNext can finish writing the Serial and Batch Bundle as part of the
	# receipt's submit lifecycle. Re-read the submitted receipt after commit so
	# the metadata copy also runs against the final, persisted bundle entries.
	# This second pass is idempotent and closes the gap where the on_submit
	# handler sees a bundle before its entries are available.
	if should_stamp and not frappe.flags.in_test:
		frappe.enqueue(
			"addsol_nl_custom.addsol_nl_custom.plates.receipt_meta.stamp_submitted_receipt",
			receipt_name=doc.name,
			queue="short",
			enqueue_after_commit=True,
		)


def stamp_submitted_receipt(receipt_name) -> None:
	"""Re-read and stamp a submitted receipt after its stock bundles are committed."""
	if not frappe.db.exists("Purchase Receipt", {"name": receipt_name, "docstatus": 1}):
		return

	doc = frappe.get_doc("Purchase Receipt", receipt_name)
	for row in doc.get("items", []):
		if row.get("custom_is_plate"):
			stamp_row(doc, row)


def stamp_row(receipt, row) -> None:
	"""Write this line's weight and rate onto its batch and serials."""
	bundle_entries = get_bundle_entries(row)
	if not bundle_entries:
		# A post-commit pass re-reads the receipt once ERPNext has finalized its
		# bundle. Keep this pass non-blocking if entries are not visible yet.
		print(f"Plate receipt {receipt.name} row {row.idx}: no serial/batch bundle, nothing stamped.")
		return

	batch_nos = {entry.batch_no for entry in bundle_entries if entry.batch_no}

	weight_per_plate = weight_per_plate_of(row)
	serial_nos = sorted({e.serial_no for e in bundle_entries if e.serial_no})

	unit_weight = frappe.utils.flt(frappe.db.get_value("Item", row.get("item_code"), "weight_per_unit"))
	ratio = (
		round_half_up(weight_per_plate / unit_weight, RATIO_PRECISION)
		if unit_weight and weight_per_plate
		else 0.0
	)

	if batch_nos:
		for batch_no in batch_nos:
			update_batch(
				batch_no,
				heat_number=None,
				mtc_no=None,
				grade=grade_of(row.get("item_code")),
				weight_per_plate=weight_per_plate,
				cost_per_kg=cost_per_kg_of(row, weight_per_plate),
				ratio=ratio,
				is_plate=bool(row.get("custom_is_plate")),
			)
	else:
		print(f"Plate receipt {receipt.name} row {row.idx}: no batch produced; stamping serials only.")

	for serial_no in serial_nos:
		update_serial(serial_no, weight_per_plate, None)


def quality_inspection_before_submit(doc, method=None) -> None:
	"""Require the heat number when an opted-in weighed item is inspected."""
	if doc.get("reference_type") != "Purchase Receipt" or not doc.get("item_code"):
		return
	from addsol_nl_custom.addsol_nl_custom.plates.settings import is_enabled
	if not is_enabled():
		return
	from addsol_nl_custom.addsol_nl_custom.plates.grouping import is_weighed_item

	if is_weighed_item(doc.item_code) and not doc.get("custom_heat_number"):
		frappe.throw(
			_("Enter the heat number from the material certificate before submitting this inspection."),
			title=_("Heat number required"),
		)


def quality_inspection_on_submit(doc, method=None) -> None:
	"""Copy inspected heat/MTC values to only the batch or serial being inspected."""
	if doc.get("reference_type") != "Purchase Receipt":
		return
	stamp_quality_inspection(doc)


def apply_quality_metadata_from_receipt(receipt) -> None:
	"""Apply QIs that were completed before the receipt created its batches."""
	if not receipt.get("name"):
		return
	for inspection in frappe.get_all(
		"Quality Inspection",
		filters={
			"reference_type": "Purchase Receipt",
			"reference_name": receipt.name,
			"docstatus": 1,
		},
		fields=["name"],
		limit_page_length=0,
	):
		stamp_quality_inspection(frappe.get_doc("Quality Inspection", inspection.name))


def stamp_quality_inspection(doc) -> None:
	batch_no = doc.get("batch_no")
	serial_text = (doc.get("item_serial_no") or "").replace(",", "\n").replace(";", "\n")
	serial_nos = [part.strip() for part in serial_text.splitlines() if part.strip()]
	if batch_no:
		update_quality_metadata("Batch", batch_no, doc)
	for serial_no in serial_nos:
		update_quality_metadata("Serial No", serial_no, doc)


def update_quality_metadata(doctype, name, doc) -> None:
	if not frappe.db.exists(doctype, name):
		return
	values = {
		"custom_heat_number": doc.get("custom_heat_number"),
		"custom_mtc_no": doc.get("custom_mtc_no"),
	}
	values = {key: value for key, value in values.items() if value not in (None, "")}
	if values:
		frappe.db.set_value(doctype, name, values, update_modified=False)


def cost_per_kg_of(row, weight_per_plate) -> float:
	"""The rate per kg this line was actually paid at.

	With weight-based purchasing on, purchase.py puts the agreed rate per kg on
	the line. With it off, the line still has its own rate per plate, and
	dividing that by the plate's weight gives the same number - so the report
	can value a batch without the feature ever having been switched on.
	"""
	rate_per_kg = frappe.utils.flt(row.get("custom_rate_per_kg"))
	if rate_per_kg:
		return rate_per_kg

	rate = frappe.utils.flt(row.get("rate"))
	if rate and weight_per_plate:
		return round_half_up(rate / weight_per_plate, 4)

	return 0.0


def weight_per_plate_of(row) -> float:
	"""Weight carried by one plate on this line.

	The receipt normally has this already. If it does not - a row typed by hand,
	or a site where weight-based purchasing is switched off - fall back through
	the accepted weight, the estimate, and finally the plate's own theoretical
	weight from the Item, so a batch is never left with no weight at all.
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

	# Last resort: the plate's theoretical weight, which the Item always has
	# once it has been through item_validate.
	return frappe.utils.flt(frappe.db.get_value("Item", row.get("item_code"), "weight_per_unit"))


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


def update_batch(
	batch_no, heat_number, mtc_no, grade, weight_per_plate, cost_per_kg, ratio, is_plate=True
) -> None:
	"""Write the batch, skipping any value we do not actually have.

	Writing a zero over a real number would be worse than writing nothing, so a
	value that came out empty or zero is simply left off the update.
	"""
	if not frappe.db.exists("Batch", batch_no):
		return

	values = {
		"custom_heat_number": heat_number,
		"custom_mtc_no": mtc_no,
		"custom_cost_per_kg": cost_per_kg,
	}

	if is_plate:
		values.update(
			{
				"custom_grade": grade,
				"custom_weight_per_plate_kg": weight_per_plate,
				"custom_actual_to_theoretical_ratio": ratio,
			}
		)

	values = {k: v for k, v in values.items() if v not in (None, "", 0, 0.0)}

	if not values:
		return

	frappe.db.set_value("Batch", batch_no, values, update_modified=False)


def update_serial(serial_no, weight_kg, heat_number) -> None:
	if not frappe.db.exists("Serial No", serial_no):
		return

	values = {"custom_weight_kg": weight_kg}
	if heat_number:
		values["custom_heat_number"] = heat_number
	frappe.db.set_value("Serial No", serial_no, values, update_modified=False)
