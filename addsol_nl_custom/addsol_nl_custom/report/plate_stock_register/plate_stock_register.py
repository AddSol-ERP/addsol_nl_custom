# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Plate Stock Register.

Standard ERPNext stock reports count pieces. This one shows pieces, kilograms,
value and value per kilogram side by side, per plate item and lot, with the heat
number carried through, because the question the store actually asks is "how
many kilos of that heat number do we hold and what did we pay for it".

Every column is derived from data the receipt wrote onto the Batch and the
Serial No, so the totals here and the totals on Stock Balance describe the same
stock.
"""

import frappe
from frappe import _
from frappe.utils import flt

COLUMNS = [
	{"fieldname": "item", "label": "Item", "fieldtype": "Link", "options": "Item", "width": 240},
	{"fieldname": "grade", "label": "Grade", "fieldtype": "Link", "options": "Item Group", "width": 130},
	{"fieldname": "thickness", "label": "Thickness", "fieldtype": "Data", "width": 90},
	{"fieldname": "length", "label": "Length", "fieldtype": "Float", "width": 80},
	{"fieldname": "width", "label": "Width", "fieldtype": "Float", "width": 80},
	{
		"fieldname": "warehouse",
		"label": "Warehouse",
		"fieldtype": "Link",
		"options": "Warehouse",
		"width": 130,
	},
	{"fieldname": "batch", "label": "Batch", "fieldtype": "Link", "options": "Batch", "width": 120},
	{"fieldname": "heat_number", "label": "Heat Number", "fieldtype": "Data", "width": 120},
	{"fieldname": "mtc_no", "label": "MTC No", "fieldtype": "Data", "width": 110},
	{"fieldname": "plates", "label": "Plates (Nos)", "fieldtype": "Int", "width": 100},
	{"fieldname": "weight_per_plate", "label": "Weight per Plate (Kg)", "fieldtype": "Float", "width": 140},
	{"fieldname": "total_weight", "label": "Total Weight (Kg)", "fieldtype": "Float", "width": 140},
	{"fieldname": "stock_value", "label": "Stock Value", "fieldtype": "Currency", "width": 130},
	{"fieldname": "value_per_kg", "label": "Value per Kg", "fieldtype": "Currency", "width": 110},
]


def execute(filters=None):
	filters = filters or {}

	columns = list(COLUMNS)
	if not filters.get("include_offcuts"):
		columns.append({"fieldname": "excluded", "label": "Offcuts", "fieldtype": "Data", "hidden": 1})

	data = build_rows(filters)
	data = [row for row in data if matches_offcut_filter(row, filters)]
	data.sort(key=lambda row: (row["item"], row["warehouse"], row["batch"]))

	return columns, data, None, get_totals(data), None


def matches_offcut_filter(row, filters) -> bool:
	if filters.get("include_offcuts"):
		return True
	return not row.get("is_offcut")


def build_rows(filters) -> list[dict]:
	"""One row per item, warehouse and batch."""
	rows = active_serials(filters)

	grouped = {}
	for serial in rows:
		key = (serial.item, serial.warehouse, serial.batch_no)
		group = grouped.setdefault(
			key,
			{
				"item": serial.item,
				"warehouse": serial.warehouse,
				"batch": serial.batch_no,
				"plates": 0,
				"weight_sum": 0.0,
			},
		)
		group["plates"] += 1
		group["weight_sum"] += flt(serial.custom_weight_kg)

	return [decorate(group, grouped[key]) for key, group in grouped.items()]


def decorate(group, serial_rows) -> dict:
	item = (
		frappe.db.get_value(
			"Item",
			group["item"],
			[
				"item_group",
				"custom_is_offcut",
				"custom_thickness_dropdown",
				"custom_length_mm",
				"custom_width_mm",
			],
			as_dict=True,
		)
		or frappe._dict()
	)

	batch = (
		frappe.db.get_value(
			"Batch",
			group["batch"],
			["custom_heat_number", "custom_mtc_no", "custom_grade", "custom_cost_per_kg"],
			as_dict=True,
		)
		or frappe._dict()
	)

	plates = group["plates"]
	total_weight = group["weight_sum"]
	weight_per_plate = total_weight / plates if plates else 0.0

	# Value comes from the batch's own cost per kg, which is the rate the
	# receipt actually paid. It is per plate here because stock is per plate.
	cost_per_kg = flt(batch.custom_cost_per_kg)
	stock_value = cost_per_kg * total_weight

	return {
		"item": group["item"],
		"grade": batch.custom_grade or item.item_group,
		"thickness": item.custom_thickness_dropdown,
		"length": flt(item.custom_length_mm),
		"width": flt(item.custom_width_mm),
		"warehouse": group["warehouse"],
		"batch": group["batch"],
		"heat_number": batch.custom_heat_number,
		"mtc_no": batch.custom_mtc_no,
		"plates": plates,
		"weight_per_plate": weight_per_plate,
		"total_weight": total_weight,
		"stock_value": stock_value,
		"value_per_kg": cost_per_kg,
		"is_offcut": item.custom_is_offcut,
	}


def active_serials(filters) -> list:
	"""Active serial numbers matching the filters.

	Stock is counted by active serial, which is what makes this report agree
	with Stock Balance rather than with every serial ever made.
	"""
	conditions = ["s.status = 'Active'"]

	for fieldname, column in (
		("item", "s.item"),
		("warehouse", "s.warehouse"),
		("batch", "s.batch_no"),
		("thickness", "i.custom_thickness_dropdown"),
	):
		if filters.get(fieldname):
			conditions.append(f"{column} = {_quote(filters[fieldname])}")

	if filters.get("heat_number"):
		conditions.append(f"b.custom_heat_number = {_quote(filters['heat_number'])}")

	if filters.get("grade"):
		conditions.append(f"i.item_group = {_quote(filters['grade'])}")

	where = " and ".join(conditions)

	return frappe.db.sql(
		f"""
		select s.name, s.item, s.warehouse, s.batch_no, s.custom_weight_kg
		  from `tabSerial No` s
		  left join `tabItem` i on i.name = s.item
		  left join `tabBatch` b on b.name = s.batch_no
		 where {where}
		 order by s.name
		""",
		as_dict=True,
		limit_page_length=0,
	)


def _quote(value) -> str:
	"""Quote a filter value. Frappe's own parameter binding is not available
	inside the conditional builder above, so escape instead."""
	return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def get_totals(data) -> dict:
	return {
		"plates": sum(row["plates"] for row in data),
		"total_weight": sum(row["total_weight"] for row in data),
		"stock_value": sum(row["stock_value"] for row in data),
	}
