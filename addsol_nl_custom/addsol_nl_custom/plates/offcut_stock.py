# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Taking offcuts and scrap back into stock when a work order finishes.

The important part is what ERPNext does with a row marked `is_scrap_item`:
`StockEntry.get_basic_rate_for_manufactured_item` subtracts the basic amount of
every scrap row from the finished item's cost. So booking the offcuts and the
scrap here means the tank is only charged for the plate steel it actually used,
and the steel that is still sitting in the offcut store keeps its value.

PROTOTYPE FIRST. This has not been run against a real Stock Entry. The open
question is whether ERPNext accepts `use_serial_batch_fields` on a row with
`is_scrap_item` set, and still creates the Serial No for it. If it does not,
switch to the fallback in `fallback_note` below.
"""

import frappe
from frappe import _

from addsol_nl_custom.addsol_nl_custom.plates.settings import get_setting

STATUS_RECORDED = "Recorded"
STATUS_STOCK_UPDATED = "Stock Updated"


def add_offcuts_to_manufacture_entry(doc, method=None) -> None:
	"""Put one row per offcut, and one for the scrap, onto a Manufacture entry."""
	if not doc.get("purpose") == "Manufacture" or not doc.get("work_order"):
		return

	for record in pending_records(doc):
		add_record_rows(doc, record)


def pending_records(doc):
	"""Submitted cutting records for this work order not yet on this entry."""
	names = frappe.get_all(
		"Plate Cutting Record",
		filters={"work_order": doc.get("work_order"), "docstatus": 1, "status": STATUS_RECORDED},
		fields=["name"],
		limit_page_length=0,
	)

	if not names:
		return []

	already = set(
		frappe.get_all(
			"Stock Entry Detail",
			filters={"parent": doc.get("name"), "custom_cutting_record": ("in", [n.name for n in names])},
			pluck="custom_cutting_record",
			limit_page_length=0,
		)
	)

	return [name for name in names if name not in already]


def add_record_rows(doc, record_name) -> None:
	record = frappe.get_doc("Plate Cutting Record", record_name)

	offcut_warehouse = get_setting("offcut_warehouse")
	if not offcut_warehouse:
		frappe.throw(
			_("Plate Settings.offcut_warehouse is not set, so offcuts from {0} have nowhere to go.").format(
				record.name
			),
			title=_("Offcut warehouse not set"),
		)

	for row in record.offcuts:
		doc.append(
			"items",
			{
				"custom_cutting_record": record.name,
				"item_code": row.offcut_item,
				"qty": 1,
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"t_warehouse": offcut_warehouse,
				"is_scrap_item": 1,
				"set_basic_rate_manually": 1,
				"basic_rate": row.value,
				"use_serial_batch_fields": 1,
				"serial_no": row.serial_no,
				"batch_no": row.batch_no,
			},
		)

	if frappe.utils.flt(record.scrap_weight_kg) > 0:
		scrap_item = get_setting("scrap_item")
		if not scrap_item:
			frappe.throw(
				_("Plate Settings.scrap_item is not set, so the scrap from {0} cannot be booked.").format(
					record.name
				),
				title=_("Scrap item not set"),
			)

		doc.append(
			"items",
			{
				"custom_cutting_record": record.name,
				"item_code": scrap_item,
				"qty": record.scrap_weight_kg,
				"uom": "Kg",
				"stock_uom": "Kg",
				"conversion_factor": 1,
				"t_warehouse": offcut_warehouse,
				"is_scrap_item": 1,
				"set_basic_rate_manually": 1,
				"basic_rate": record.source_cost_per_kg,
			},
		)

	record.db_set("status", STATUS_STOCK_UPDATED, update_modified=False)
	record.db_set("stock_entry", doc.get("name"), update_modified=False)


def sync_cutting_records(doc, method=None) -> None:
	"""Follow the Stock Entry back onto the cutting records it consumed.

	On submit the offcut serials now exist, so their weight and source serial
	can be written. On cancel the records go back to Recorded, ready to be put
	onto another entry.
	"""
	if not doc.get("purpose") == "Manufacture":
		return

	names = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": doc.get("name"), "custom_cutting_record": ("is", "set")},
		fields=["custom_cutting_record", "item_code", "serial_no", "batch_no"],
		limit_page_length=0,
	)

	if not names:
		return

	if doc.get("docstatus") == 2:
		for name in {row.custom_cutting_record for row in names}:
			frappe.db.set_value(
				"Plate Cutting Record",
				name,
				{"status": STATUS_RECORDED, "stock_entry": ""},
				update_modified=False,
			)
		return

	for row in names:
		stamp_offcut_serial(row)


def stamp_offcut_serial(row) -> None:
	"""The offcut serial only exists now the Stock Entry is submitted."""
	if not row.get("serial_no") or not frappe.db.exists("Serial No", row.serial_no):
		return

	source_serial = frappe.db.get_value(
		"Plate Cutting Record", row.get("custom_cutting_record"), "source_serial_no"
	)

	frappe.db.set_value(
		"Serial No",
		row.serial_no,
		{
			"custom_weight_kg": frappe.db.get_value(
				"Batch", row.get("batch_no"), "custom_weight_per_plate_kg"
			),
			"custom_source_serial_no": source_serial,
		},
		update_modified=False,
	)


def fallback_note() -> str:
	"""What to do if ERPNext refuses a scrap row that carries serial and batch."""
	return (
		"If Stock Entry will not accept use_serial_batch_fields on a row with "
		"is_scrap_item, or does not create the Serial No for it, fall back to a "
		"separate Material Receipt after the work order for the offcuts and scrap, "
		"with the credit side posted to an Offcut and Scrap Recovery account (a "
		"cost-of-goods credit), carrying the same values."
	)
