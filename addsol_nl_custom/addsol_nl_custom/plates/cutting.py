# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Cutting a plate into pieces for one order.

One plate goes in whole; what comes out is a set of offcuts, whatever scrap
the operator books, and - whatever is left after both - one remainder piece
that stays plate stock and is issued against the Project the cut was made for.
Booked by a Plate Offcut, which repacks the plate into its pieces on submit
and issues the remainder straight out against that Project, so only the
consumed weight becomes cost for the order.

Every piece becomes real stock in its own right, each with its own item,
batch and serial, all pointing back at the plate it was cut from so the heat
number stays traceable. Offcuts may be rectangles or circles; a circle is
entered by diameter and weighs what the square across it weighs, times pi/4.

The arithmetic follows the source lot rather than the drawing: a piece's
weight is its theoretical weight for the new size, multiplied by the source
batch's actual-to-theoretical ratio. That keeps the density honest even when
the plate it was cut from did not match its nominal size exactly.
"""

import math
import re

import frappe
from frappe import _

from addsol_nl_custom.addsol_nl_custom.plates.item_defaults import SERIES_FIELDS
from addsol_nl_custom.addsol_nl_custom.plates.settings import get_setting
from addsol_nl_custom.addsol_nl_custom.plates.utils import (
	build_circle_item_name,
	build_plate_description,
	build_plate_item_name,
	build_remainder_item_name,
	round_half_up,
)
from addsol_nl_custom.addsol_nl_custom.plates.weight import compute_theoretical_weight, get_item_thickness_mm

WEIGHT_PRECISION = 3
RATIO_PRECISION = 4

# A circle weighs what the square across it weighs, times pi/4. Only the shape
# factor is ours: the square goes through the grade's own formula, so every
# grade's rule still decides the weight of a round cut.
CIRCLE_AREA_FACTOR = math.pi / 4

CIRCLE = "Circle"
RECTANGLE = "Rectangle"

# A cutting that comes out a fraction of a gram heavy is not a rejection - a
# plate is never weighed to this precision. The save has always accepted up to
# this much, so the form's preview must turn red at exactly the same point or
# it would warn about a document the save happily takes.
OVERAGE_TOLERANCE = 0.001

TOO_SMALL = "Too small to keep: record as scrap"


def is_circle(row) -> bool:
	"""Whether an offcut line is a round cut.

	Blank counts as a rectangle: the field is new, and every line entered
	before it existed was drawn as one.
	"""
	shape = row.get("shape") if hasattr(row, "get") else getattr(row, "shape", None)
	return (shape or "").strip().lower() == CIRCLE.lower()


# ------------------------------------------------------------------ read side


def plate_text_for(item_name, item_code, batch_no) -> str:
	"""The plate named in words, so the operator sees which Item - and which
	Batch - a serial is without opening either.

	Item name first, batch after it: an Item with no name still shows its
	code, and a plate with no batch still shows its Item.

	Split out from get_source_details so the backfill that stamps cuttings
	already on file can spell a plate exactly the way the live form does,
	without re-running the reader that refuses a Consumed serial.
	"""
	text = item_name or item_code
	if batch_no:
		text = f"{text} · Batch {batch_no}"
	return text


def get_source_details(source_serial_no) -> dict:
	"""Everything about the plate being cut, read off the serial and batch."""
	if not frappe.db.exists("Serial No", source_serial_no):
		frappe.throw(_("Serial No {0} does not exist.").format(source_serial_no))

	# Serial No links to Item through item_code. Batch, which also appears
	# below, uses item - they are not interchangeable.
	serial = frappe.db.get_value(
		"Serial No",
		source_serial_no,
		["item_code", "batch_no", "custom_weight_kg", "status", "warehouse"],
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
		frappe.db.get_value(
			"Item", serial.item_code, ["item_group", "item_name", "weight_per_unit"], as_dict=True
		)
		or frappe._dict()
	)

	return {
		"item": serial.item_code,
		"plate_text": plate_text_for(item.item_name, serial.item_code, serial.batch_no),
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


def get_offcut_details(source_serial_no) -> dict:
	"""Everything compute_offcut and check_offcut_fits need about the plate.

	One reader for both the save and the preview the form asks for while the
	operator types dimensions, so the two cannot disagree about the grade, the
	thickness or the plate's real size.
	"""
	details = get_source_details(source_serial_no)

	item = (
		frappe.db.get_value(
			"Item",
			details["item"],
			["item_group", "custom_thickness_dropdown", "custom_length_mm", "custom_width_mm"],
			as_dict=True,
		)
		or frappe._dict()
	)

	# The formula and multiplication factor live on the Item Group, so the grade
	# that decides which formula runs is the Item's own group. details["grade"]
	# prefers the batch's custom_grade, which is only a label - stamping code
	# writes the group into it today, but nothing stops a batch carrying another
	# name, and that would silently pick a different (or missing) formula.
	details["grade"] = item.item_group
	details["thickness_mm"] = frappe.utils.flt(
		get_item_thickness_mm({"custom_thickness_dropdown": item.custom_thickness_dropdown})
	)
	details["length_mm"] = frappe.utils.flt(item.custom_length_mm)
	details["width_mm"] = frappe.utils.flt(item.custom_width_mm)

	return details


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
	if is_circle(row):
		check_circle_fits(row, details)
		return

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

	check_min_size(row, details, f"{fmt_number(length)} x {fmt_number(width)}")


def check_circle_fits(row, details) -> None:
	"""A round cut is both its own length and its own width.

	Fed through the same fits() as a rectangle of diameter x diameter, so it
	cannot be turned to squeeze past a plate it does not fit on.
	"""
	diameter = frappe.utils.flt(row.diameter_mm)

	if diameter <= 0:
		frappe.throw(
			_("Circular offcut on row {0} needs a diameter.").format(row.idx),
			title=_("Diameter missing"),
		)

	if not fits(diameter, diameter, details["length_mm"], details["width_mm"]):
		frappe.throw(
			_("A circle of {0} mm does not fit inside the {1} x {2} plate.").format(
				fmt_number(diameter), details["length_mm"], details["width_mm"]
			),
			title=_("Offcut is larger than the plate"),
		)

	check_min_size(row, details, _("circle of {0} mm").format(fmt_number(diameter)))


def check_min_size(row, details, cut_text) -> None:
	"""A cut too small to be worth keeping has to be booked as scrap instead.

	The two minimums are the shortest length and the shortest width this grade
	keeps. A circle is measured against both: it is one size in every
	direction, so it has to clear whichever minimum is the larger.
	"""
	min_length, min_width = minimum_offcut(details["grade"])

	if is_circle(row):
		diameter = frappe.utils.flt(row.diameter_mm)
		too_small = (min_length and diameter < min_length) or (min_width and diameter < min_width)
	else:
		longer, shorter = max(frappe.utils.flt(row.length_mm), frappe.utils.flt(row.width_mm)), min(
			frappe.utils.flt(row.length_mm), frappe.utils.flt(row.width_mm)
		)
		too_small = (min_width and shorter < min_width) or (min_length and longer < min_length)

	if too_small:
		frappe.throw(
			_("{0}: the {1} is below the minimum this grade keeps.").format(TOO_SMALL, cut_text),
			title=_("Offcut is too small"),
		)


def fmt_number(value) -> str:
	"""A dimension as the operator typed it - no trailing .0 on a whole mm."""
	return f"{frappe.utils.flt(value):g}"


def fits(offcut_length, offcut_width, plate_length, plate_width) -> bool:
	"""Whether the offcut fits, in either orientation."""
	if not plate_length or not plate_width:
		return False

	return (offcut_length <= plate_length and offcut_width <= plate_width) or (
		offcut_length <= plate_width and offcut_width <= plate_length
	)


def compute_offcut(row, details) -> None:
	"""The offcut's weight and value, derived from the source lot."""
	theoretical = theoretical_offcut_weight(row, details)

	row.theoretical_weight_kg = round_half_up(theoretical, WEIGHT_PRECISION)
	row.weight_kg = round_half_up(theoretical * details["ratio"], WEIGHT_PRECISION)
	row.value = round_half_up(row.weight_kg * details["cost_per_kg"], 2)


def theoretical_offcut_weight(row, details) -> float:
	"""Unrounded theoretical weight of one offcut, by shape.

	A circle is the square across it - diameter by diameter - through the
	grade's own formula, times pi/4. The shape factor is the only thing this
	module adds; the steel still weighs whatever the grade says it weighs.
	"""
	if is_circle(row):
		square = compute_theoretical_weight(
			details["grade"],
			details["thickness_mm"],
			row.diameter_mm,
			row.diameter_mm,
		)
		return square * CIRCLE_AREA_FACTOR

	return compute_theoretical_weight(
		details["grade"],
		details["thickness_mm"],
		row.length_mm,
		row.width_mm,
	)


def offcut_totals(source_weight_kg, scrap_weight_kg, row_weights, row_values, cost_per_kg) -> dict:
	"""The cutting summary, shared by the save and the form's live preview.

	Pure arithmetic - no document, no throw - so the numbers shown while the
	operator types are produced by exactly the code that decides whether the
	save is allowed.

	Scrap is booked by hand and the remainder is what is left after it, so
	`consumed` is source minus offcuts minus scrap: the weight that carries on
	as the project's own piece. It comes back unrounded on purpose: the
	tolerance test is a judgement about the raw sum, and rounding it in one
	caller but not the other is how the preview and the save would start to
	disagree by a gram. `over_by_kg` is the same judgement the save makes,
	expressed in kilograms, so the form only warns when the save really would
	refuse.
	"""
	scrap = frappe.utils.flt(scrap_weight_kg)
	offcuts = sum(frappe.utils.flt(weight) for weight in row_weights)
	source = frappe.utils.flt(source_weight_kg)
	consumed = source - offcuts - scrap
	over_by = (
		0.0
		if consumed >= -OVERAGE_TOLERANCE
		else round_half_up(-consumed, WEIGHT_PRECISION)
	)
	cost_per_kg = frappe.utils.flt(cost_per_kg)

	return {
		"source_weight_kg": source,
		"scrap_weight_kg": scrap,
		"total_offcut_weight_kg": round_half_up(offcuts, WEIGHT_PRECISION),
		"total_offcut_value": round_half_up(
			sum(frappe.utils.flt(value) for value in row_values), 2
		),
		"scrap_value": round_half_up(scrap * cost_per_kg, 2),
		"consumed": consumed,
		# Below zero only within the tolerance - a cutting a gram over is
		# accepted, and the piece it does not have must not be booked as one.
		"consumed_weight_kg": max(round_half_up(consumed, WEIGHT_PRECISION), 0.0),
		"consumed_value": round_half_up(max(consumed, 0.0) * cost_per_kg, 2),
		"over_by_kg": over_by,
	}


def compute_totals(doc) -> None:
	"""Offcuts plus scrap can never come to more than the plate weighed."""
	if frappe.utils.flt(doc.scrap_weight_kg) < 0:
		frappe.throw(
			_("Scrap cannot be negative. Scrap is what you book as waste; the rest of the "
			  "plate becomes the remainder piece."),
			title=_("Scrap cannot be negative"),
		)

	totals = offcut_totals(
		source_weight_kg=doc.source_weight_kg,
		scrap_weight_kg=doc.scrap_weight_kg,
		row_weights=[row.weight_kg for row in doc.offcuts],
		row_values=[row.value for row in doc.offcuts],
		cost_per_kg=doc.source_cost_per_kg,
	)

	doc.total_offcut_weight_kg = totals["total_offcut_weight_kg"]
	doc.total_offcut_value = totals["total_offcut_value"]
	doc.scrap_value = totals["scrap_value"]
	doc.consumed_weight_kg = totals["consumed_weight_kg"]
	doc.consumed_value = totals["consumed_value"]

	if totals["consumed"] < -OVERAGE_TOLERANCE:
		frappe.throw(
			_(
				"The offcuts ({0} kg) and scrap ({1} kg) add up to more than the plate weighs ({2} kg)."
			).format(
				totals["total_offcut_weight_kg"],
				round_half_up(totals["scrap_weight_kg"], WEIGHT_PRECISION),
				totals["source_weight_kg"],
			),
			title=_("More material out than in"),
		)


# ----------------------------------------------------------------- write side


def get_or_create_offcut_item(source_item, row) -> str:
	"""The Item for an offcut, named by its shape and created once.

	One Item per size, shared by every offcut of that size: a rectangle is
	<group>-<T>x<W>x<L> and a circle is <group>-<T>-D<d>, so a round cut can
	never be handed the Item of a square one.
	"""
	thickness_mm = item_thickness_mm(source_item)
	item_group = frappe.db.get_value("Item", source_item, "item_group")

	if is_circle(row):
		name = build_circle_item_name(item_group, thickness_mm, row.diameter_mm)
		item = {
			"custom_diameter_mm": row.diameter_mm,
			"description": _("Round offcut, {0} mm across, cut from {1}.").format(
				fmt_number(row.diameter_mm), source_item
			),
		}
	else:
		name = build_plate_item_name(item_group, thickness_mm, row.length_mm, row.width_mm)
		item = {
			"custom_length_mm": row.length_mm,
			"custom_width_mm": row.width_mm,
			"description": build_plate_description(thickness_mm, row.length_mm, row.width_mm),
		}

	if frappe.db.exists("Item", name):
		return name

	item.update(
		{
			"doctype": "Item",
			"item_code": name,
			"item_name": name,
			"item_group": item_group,
			"custom_thickness_dropdown": frappe.db.get_value("Item", source_item, "custom_thickness_dropdown"),
			"custom_is_offcut": 1,
			"custom_source_item": source_item,
		}
	)

	return insert_piece_item(item, item_group)


def get_or_create_remainder_item(source_item, project, running_no) -> str:
	"""The Item for the piece this cutting leaves behind. Never reused.

	One Item per piece, because two cuttings for the same order leave two
	different pieces with their own weight, batch and serial - sharing one
	Item would put both under a single name and the stock register could no
	longer tell them apart. Named <group>-<T>-<project>-<running number>,
	which is why the running number has to be minted per piece and not read
	back from what already exists.
	"""
	thickness_mm = item_thickness_mm(source_item)
	item_group = frappe.db.get_value("Item", source_item, "item_group")

	name = build_remainder_item_name(item_group, thickness_mm, project, running_no)

	if frappe.db.exists("Item", name):
		# Two pieces cannot share a name, and the running number is handed in
		# by the caller, so this only ever fires if something outside this
		# code made an Item of exactly this name.
		frappe.throw(
			_("Item {0} already exists, so this cutting cannot name its remainder piece.").format(name),
			title=_("Remainder name already taken"),
		)

	return insert_piece_item(
		{
			"doctype": "Item",
			"item_code": name,
			"item_name": name,
			"item_group": item_group,
			"custom_thickness_dropdown": frappe.db.get_value("Item", source_item, "custom_thickness_dropdown"),
			# Leftover of a plate, not an offcut: it stays regular plate stock,
			# so the Plate Stock Register must not file it under offcuts.
			"custom_is_remainder": 1,
			"custom_remainder_project": project,
			"custom_source_item": source_item,
			"description": _("Leftover piece of {0}, cut down for {1}.").format(source_item, project),
		},
		item_group,
	)


def next_remainder_running_no(project) -> str:
	"""The next number in this project's remainder series, e.g. 00001.

	Counted per project from the series in Plate Settings, so every project
	starts its own count and two orders never collide - and the number keeps
	moving even if a piece's Item is ever deleted, which a count of what
	exists would not. The digits are read back off the generated name, so any
	series works, not only the default one.
	"""
	from frappe.model.naming import make_autoname

	series = get_setting("remainder_naming_series", "RMD-.{project}.-.#####")

	# The doc is the dict about to be named: parse_naming_series reads
	# {project} off it, and that expansion is what makes the counter per
	# project - the series key becomes RMD-<project>-.
	generated = make_autoname(series, doc={"project": project})

	number = re.search(r"\d+$", generated)
	return number.group(0) if number else generated


def item_thickness_mm(source_item) -> float:
	"""Thickness of the plate being cut, in mm, for naming its pieces."""
	thickness = frappe.db.get_value("Item", source_item, "custom_thickness_dropdown")
	return frappe.utils.flt(frappe.db.get_value("Thickness", thickness, "thickness_mm"))


def insert_piece_item(item: dict, item_group) -> str:
	"""Create an offcut or remainder Item with the plate's own stock options.

	An offcut or remainder is the same steel in another shape, so it carries
	the source's HSN/SAC code - India Compliance refuses to save an Item
	without one, and these are created by code where nobody is there to type
	it - and the group's naming series, which have to be in place before
	item_validate applies the plate defaults.
	"""
	name = item["item_code"]

	hsn_code = frappe.db.get_value("Item", item.get("custom_source_item"), "gst_hsn_code")
	if hsn_code:
		item["gst_hsn_code"] = hsn_code

	created = frappe.get_doc(item).insert(ignore_permissions=True)

	for field, group_field in SERIES_FIELDS.items():
		series = frappe.db.get_value("Item Group", item_group, group_field)
		if series and not created.get(field):
			created.set(field, series)

	created.save()

	return name


def reserve_serial_no(item_code) -> str:
	"""A serial number name, reserved now and stamped when the plate is created."""
	from frappe.model.naming import make_autoname

	series = frappe.db.get_value("Item", item_code, "serial_no_series") or "PL-.######"
	doc = {"doctype": "Serial No", "item_code": item_code}

	while True:
		name = make_autoname(series, doc=doc)
		if not frappe.db.exists("Serial No", name):
			return name
