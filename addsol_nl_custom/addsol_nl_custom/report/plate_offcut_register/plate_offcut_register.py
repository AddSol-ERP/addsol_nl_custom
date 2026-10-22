# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Plate Offcut Register.

The offcut half of `Plate Stock Register`. That report counts whole plates and
the remainder a cutting leaves behind; this one counts the pieces a cutting
produced. They are different stock with different questions, so they are
different reports: "how many kilos of that heat number do we hold" and "how
many 500x250 offcuts of that heat are sitting in the rack" are not the same
question, and answering the second with the first's rows is how offcuts end up
counted twice.

Two things make the offcut set its own thing rather than a filter on the plate
register:

- An offcut is identified by the `Plate Offcut Item` row that produced it, not
  by a flag on its Item. `custom_is_offcut` on the Item says what a piece IS;
  the child row says what actually happened. The join below is therefore an
  INNER JOIN, and the remainder piece -- which is plate stock and carries no
  child row -- cannot leak in.
- Every offcut piece gets its OWN Batch (`Plate Offcut.make_piece_batch` is
  called once per row). Grouping by the piece's own batch would therefore
  produce one row per piece, which is a list, not a register. The batch carries
  `custom_source_batch` -- the plate the piece was cut from -- so the register
  groups by the SOURCE batch: one row per size, per warehouse, per heat.

Value comes from the `Plate Offcut Item` row, which holds what the Repack
actually booked for that piece. The batch's cost per kg is the source plate's
rate and every piece of a cutting shares it, so cost per kg times weight would
reproduce it - but only approximately, because each piece is priced on its own
measured weight. The booked value is the number the ledger holds, so it is the
number reported here.
"""

import frappe
from frappe.utils import flt

COLUMNS = [
	{"fieldname": "item", "label": "Item", "fieldtype": "Link", "options": "Item", "width": 240},
	{"fieldname": "grade", "label": "Grade", "fieldtype": "Link", "options": "Item Group", "width": 130},
	{"fieldname": "thickness", "label": "Thickness", "fieldtype": "Data", "width": 90},
	{"fieldname": "length_mm", "label": "Length (mm)", "fieldtype": "Float", "width": 90},
	{"fieldname": "width_mm", "label": "Width (mm)", "fieldtype": "Float", "width": 90},
	{"fieldname": "diameter_mm", "label": "Diameter (mm)", "fieldtype": "Float", "width": 100},
	{
		"fieldname": "source_item",
		"label": "Cut From",
		"fieldtype": "Link",
		"options": "Item",
		"width": 240,
	},
	{
		"fieldname": "warehouse",
		"label": "Warehouse",
		"fieldtype": "Link",
		"options": "Warehouse",
		"width": 130,
	},
	{
		"fieldname": "batch",
		"label": "Source Batch",
		"fieldtype": "Link",
		"options": "Batch",
		"width": 120,
	},
	{"fieldname": "heat_number", "label": "Heat Number", "fieldtype": "Data", "width": 120},
	{"fieldname": "mtc_no", "label": "MTC No", "fieldtype": "Data", "width": 110},
	{"fieldname": "pieces", "label": "Pieces (Nos)", "fieldtype": "Int", "width": 100},
	{
		"fieldname": "weight_per_piece",
		"label": "Weight per Piece (Kg)",
		"fieldtype": "Float",
		"width": 140,
	},
	{"fieldname": "total_weight", "label": "Total Weight (Kg)", "fieldtype": "Float", "width": 140},
	{"fieldname": "total_value", "label": "Total Value", "fieldtype": "Currency", "width": 130},
	{"fieldname": "value_per_kg", "label": "Value per Kg", "fieldtype": "Currency", "width": 110},
]


def execute(filters=None):
	filters = filters or {}

	columns = list(COLUMNS)

	data = build_rows(filters)
	data.sort(key=lambda row: (row["item"], row["warehouse"], row["batch"] or ""))

	return columns, data, None, get_totals(data), None


def build_rows(filters) -> list[dict]:
	"""One row per offcut item, warehouse and source batch."""
	pieces = active_offcut_pieces(filters)

	grouped = {}
	for piece in pieces:
		key = (piece.item_code, piece.warehouse, piece.source_batch or "")
		group = grouped.setdefault(
			key,
			{
				"item": piece.item_code,
				# `custom_grade` is the Batch's own grade label; the Item's
				# group is the fallback, and it is the one the weight maths
				# uses. Same precedence as the plate register.
				"grade": piece.batch_grade or piece.item_group,
				"thickness": piece.custom_thickness_dropdown,
				"length_mm": flt(piece.custom_length_mm),
				"width_mm": flt(piece.custom_width_mm),
				"diameter_mm": flt(piece.custom_diameter_mm),
				"source_item": piece.custom_source_item,
				"warehouse": piece.warehouse,
				"batch": piece.source_batch,
				"heat_number": piece.heat_number,
				"mtc_no": piece.mtc_no,
				"pieces": 0,
				"weight_sum": 0.0,
				"value_sum": 0.0,
			},
		)
		group["pieces"] += 1
		group["weight_sum"] += flt(piece.weight_kg)
		group["value_sum"] += flt(piece.piece_value)

	return [decorate(group) for group in grouped.values()]


def decorate(group) -> dict:
	"""Turn an accumulated group into the report's row.

	`weight_per_piece` and `value_per_kg` are DERIVED, never stored: they are
	quotients of the two figures beside them, and a stored copy would drift
	the moment a piece's weight was corrected.
	"""
	pieces = group["pieces"]
	total_weight = group["weight_sum"]

	return {
		"item": group["item"],
		"grade": group["grade"],
		"thickness": group["thickness"],
		"length_mm": _dimension(group["length_mm"]),
		"width_mm": _dimension(group["width_mm"]),
		"diameter_mm": _dimension(group["diameter_mm"]),
		"source_item": group["source_item"],
		"warehouse": group["warehouse"],
		"batch": group["batch"],
		"heat_number": group["heat_number"],
		"mtc_no": group["mtc_no"],
		"pieces": pieces,
		"weight_per_piece": total_weight / pieces if pieces else 0.0,
		"total_weight": total_weight,
		"total_value": group["value_sum"],
		"value_per_kg": group["value_sum"] / total_weight if total_weight else 0.0,
	}


def _dimension(value):
	"""A dimension that does not apply to this shape, as None rather than 0.

	A circle is cut by its diameter and has no length or width; a rectangle is
	the other way round. Reporting the absent one as 0 puts a real zero in a
	size column, and a storekeeper reads 0 as "this piece measures nothing".
	"""
	number = flt(value)
	return number if number else None


def active_offcut_pieces(filters) -> list:
	"""The offcut pieces currently in stock, matching the filters.

	Stock is counted by ACTIVE serial, which is what makes this report agree
	with Stock Balance rather than with every offcut ever cut.

	Two joins carry the weight of this report:

	- `tabPlate Offcut Item` is INNER-joined on the serial number. That child
	  row IS the offcut: the remainder piece has no row there, and a draft's row
	  names a serial that does not exist as a document, so neither can appear.
	- `tabBatch` is the piece's OWN batch, which carries the plate's history
	  (`custom_source_batch`, `custom_heat_number`, `custom_mtc_no`). The batch
	  is per piece; the SOURCE batch it points at is what the register groups
	  by.

	The Item join reads the size and the grade of the piece. `Item` links to
	`Serial No` through `item_code`, not `item` -- getting that the wrong way
	round fails only when the report is opened.
	"""
	conditions = ["s.status = 'Active'"]

	for fieldname, column in (
		("item", "s.item_code"),
		("warehouse", "s.warehouse"),
		("batch", "b.custom_source_batch"),
		("heat_number", "b.custom_heat_number"),
		("grade", "i.item_group"),
		("thickness", "i.custom_thickness_dropdown"),
	):
		if filters.get(fieldname):
			conditions.append(f"{column} = {_quote(filters[fieldname])}")

	where = " and ".join(conditions)

	return frappe.db.sql(
		f"""
		select s.name, s.item_code, s.warehouse,
		       coalesce(s.custom_weight_kg, p.weight_kg) as weight_kg,
		       p.value as piece_value,
		       b.custom_source_batch as source_batch,
		       b.custom_heat_number as heat_number,
		       b.custom_mtc_no as mtc_no,
		       b.custom_grade as batch_grade,
		       i.item_group, i.custom_thickness_dropdown,
		       i.custom_length_mm, i.custom_width_mm, i.custom_diameter_mm,
		       i.custom_source_item
		  from `tabSerial No` s
		  inner join `tabPlate Offcut Item` p on p.serial_no = s.name
		  left join `tabItem` i on i.name = s.item_code
		  left join `tabBatch` b on b.name = s.batch_no
		 where {where}
		 order by s.name
		""",
		as_dict=True,
	)


def _quote(value) -> str:
	"""Quote a filter value. Frappe's own parameter binding is not available
	inside the conditional builder above, so escape instead."""
	return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def get_totals(data) -> dict:
	return {
		"pieces": sum(row["pieces"] for row in data),
		"total_weight": sum(row["total_weight"] for row in data),
		"total_value": sum(row["total_value"] for row in data),
	}
