# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Cutting a plate into offcuts.

One plate goes in, a set of offcuts and some scrap kg come out. The offcuts
become real stock in their own right, each with its own item, batch and serial,
all pointing back at the plate they came from so the heat number stays
traceable.

The arithmetic follows the source lot rather than the drawing: an offcut's
weight is its theoretical weight for the new size, multiplied by the source
batch's actual-to-theoretical ratio. That keeps the offcut's density honest
even when the plate it was cut from did not match its nominal size exactly.
"""

import frappe
from frappe import _

from addsol_nl_custom.addsol_nl_custom.plates.item_defaults import SERIES_FIELDS
from addsol_nl_custom.addsol_nl_custom.plates.settings import get_setting
from addsol_nl_custom.addsol_nl_custom.plates.utils import build_plate_item_name, round_half_up
from addsol_nl_custom.addsol_nl_custom.plates.weight import compute_theoretical_weight

WEIGHT_PRECISION = 3
RATIO_PRECISION = 4

TOO_SMALL = "Too small to keep: record as scrap"


# ------------------------------------------------------------------ read side


def get_source_details(source_serial_no) -> dict:
	"""Everything about the plate being cut, read off the serial and batch."""
	if not frappe.db.exists("Serial No", source_serial_no):
		frappe.throw(_("Serial No {0} does not exist.").format(source_serial_no))

	serial = frappe.db.get_value(
		"Serial No",
		source_serial_no,
		["item", "batch_no", "custom_weight_kg", "status", "warehouse"],
		as_dict=True,
	)

	if serial.status != "Active":
		frappe.throw(_("Serial No {0} is {1}, so it cannot be cut.").format(source_serial_no, serial.status))

	if not serial.custom_weight_kg:
		frappe.throw(
			_("Serial No {0} has no weight on it. It was received before weights were recorded.").format(
				source_serial_no
			)
		)

	batch = (
		frappe.db.get_value(
			"Batch",
			serial.batch_no,
			[
				"custom_heat_number",
				"custom_mtc_no",
				"custom_grade",
				"custom_cost_per_kg",
				"custom_actual_to_theoretical_ratio",
			],
			as_dict=True,
		)
		or frappe._dict()
	)

	item = (
		frappe.db.get_value("Item", serial.item, ["item_group", "weight_per_unit"], as_dict=True)
		or frappe._dict()
	)

	return {
		"item": serial.item,
		"batch": serial.batch_no,
		"warehouse": serial.warehouse,
		"weight": frappe.utils.flt(serial.custom_weight_kg),
		"heat_number": batch.custom_heat_number,
		"mtc_no": batch.custom_mtc_no,
		"grade": batch.custom_grade or item.item_group,
		"cost_per_kg": frappe.utils.flt(batch.custom_cost_per_kg),
		"ratio": frappe.utils.flt(batch.custom_actual_to_theoretical_ratio) or 1.0,
		"unit_weight": frappe.utils.flt(item.weight_per_unit),
	}


def minimum_offcut(item_group) -> tuple[float, float]:
	"""The smallest offcut this grade keeps, falling back to Plate Settings."""
	group = (
		frappe.db.get_value(
			"Item Group",
			item_group,
			["custom_min_offcut_length_mm", "custom_min_offcut_width_mm"],
			as_dict=True,
		)
		or frappe._dict()
	)

	length = frappe.utils.flt(group.custom_min_offcut_length_mm) or frappe.utils.flt(
		get_setting("min_offcut_length_mm", 0)
	)
	width = frappe.utils.flt(group.custom_min_offcut_width_mm) or frappe.utils.flt(
		get_setting("min_offcut_width_mm", 0)
	)
	return length, width


def check_offcut_fits(doc, row, details) -> None:
	"""The offcut has to fit inside the plate, and be big enough to keep."""
	length = frappe.utils.flt(row.length_mm)
	width = frappe.utils.flt(row.width_mm)

	if length <= 0 or width <= 0:
		frappe.throw(
			_("Offcut on row {0} needs both a length and a width.").format(row.idx),
			title=_("Offcut size missing"),
		)

	if not fits(length, width, details["length_mm"], details["width_mm"]):
		frappe.throw(
			_("Offcut {0} x {1} does not fit inside the {2} x {3} plate.").format(
				length, width, details["length_mm"], details["width_mm"]
			),
			title=_("Offcut is larger than the plate"),
		)

	min_length, min_width = minimum_offcut(details["grade"])
	longer, shorter = max(length, width), min(length, width)

	if min_width and shorter < min_width:
		frappe.throw(TOO_SMALL, title=_("Offcut is too small"))
	if min_length and longer < min_length:
		frappe.throw(TOO_SMALL, title=_("Offcut is too small"))


def fits(offcut_length, offcut_width, plate_length, plate_width) -> bool:
	"""Whether the offcut fits, in either orientation."""
	if not plate_length or not plate_width:
		return False

	return (offcut_length <= plate_length and offcut_width <= plate_width) or (
		offcut_length <= plate_width and offcut_width <= plate_length
	)


def compute_offcut(row, details) -> None:
	"""The offcut's weight and value, derived from the source lot."""
	theoretical = compute_theoretical_weight(
		details["grade"],
		details["thickness_mm"],
		row.length_mm,
		row.width_mm,
	)

	row.theoretical_weight_kg = round_half_up(theoretical, WEIGHT_PRECISION)
	row.weight_kg = round_half_up(theoretical * details["ratio"], WEIGHT_PRECISION)
	row.value = round_half_up(row.weight_kg * details["cost_per_kg"], 2)


def compute_totals(doc) -> None:
	"""Offcuts plus scrap can never come to more than the plate weighed."""
	scrap = frappe.utils.flt(doc.scrap_weight_kg)
	offcuts = sum(frappe.utils.flt(row.weight_kg) for row in doc.offcuts)
	source = frappe.utils.flt(doc.source_weight_kg)

	doc.total_offcut_weight_kg = round_half_up(offcuts, WEIGHT_PRECISION)
	doc.total_offcut_value = round_half_up(sum(frappe.utils.flt(row.value) for row in doc.offcuts), 2)
	doc.scrap_value = round_half_up(scrap * frappe.utils.flt(doc.source_cost_per_kg), 2)

	consumed = source - offcuts - scrap
	if consumed < -0.001:
		frappe.throw(
			_(
				"The offcuts ({0} kg) and scrap ({1} kg) add up to more than the plate weighs ({2} kg)."
			).format(round_half_up(offcuts, 3), round_half_up(scrap, 3), source),
			title=_("More material out than in"),
		)

	doc.consumed_weight_kg = round_half_up(max(consumed, 0.0), WEIGHT_PRECISION)


# ----------------------------------------------------------------- write side


def get_or_create_offcut_item(source_item, length_mm, width_mm) -> str:
	"""The Item for an offcut size, created once and reused after that."""
	thickness = frappe.db.get_value("Item", source_item, "custom_thickness_dropdown")
	thickness_mm = frappe.db.get_value("Thickness", thickness, "thickness_mm")

	item_group = frappe.db.get_value("Item", source_item, "item_group")
	name = build_plate_item_name(item_group, thickness_mm, length_mm, width_mm)

	if frappe.db.exists("Item", name):
		return name

	item = {
		"doctype": "Item",
		"item_code": name,
		"item_name": name,
		"item_group": item_group,
		"custom_thickness_dropdown": thickness,
		"custom_length_mm": length_mm,
		"custom_width_mm": width_mm,
		"custom_is_offcut": 1,
		"custom_source_item": source_item,
	}

	# An offcut is the same steel in a smaller size, so it carries the same
	# HSN/SAC code. India Compliance refuses to save an Item without one, and
	# these are created by code where nobody is there to type it.
	hsn_code = frappe.db.get_value("Item", source_item, "gst_hsn_code")
	if hsn_code:
		item["gst_hsn_code"] = hsn_code

	item = frappe.get_doc(item).insert(ignore_permissions=True)

	# The plate defaults are applied by item_validate, but the Item Group's
	# series have to be in place first.
	for field, group_field in SERIES_FIELDS.items():
		series = frappe.db.get_value("Item Group", item_group, group_field)
		if series and not item.get(field):
			item.set(field, series)

	item.save()

	return name


def reserve_serial_no(item_code) -> str:
	"""A serial number name, reserved now and stamped when the plate is created."""
	from frappe.model.naming import make_autoname

	series = frappe.db.get_value("Item", item_code, "serial_no_series") or "PL-.######"

	while True:
		name = make_autoname(series, doc="Serial No")
		if not frappe.db.exists("Serial No", name):
			return name
