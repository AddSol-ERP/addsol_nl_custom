# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from addsol_nl_custom.addsol_nl_custom.finished_goods.groups import is_finished_good_group
from addsol_nl_custom.addsol_nl_custom.plates.grouping import is_weighed_group
from addsol_nl_custom.addsol_nl_custom.plates.item_defaults import apply_plate_item_defaults
from addsol_nl_custom.addsol_nl_custom.plates.utils import build_plate_description, build_plate_item_name
from addsol_nl_custom.addsol_nl_custom.plates.weight import compute_theoretical_weight, get_item_thickness_mm


def item_autoname(doc, method):
	"""Name a weighed Item from its grade, thickness, length and width.

	For items without dimensions, fall back to whatever the user typed.

	The one exception is a piece the cutting process made: an offcut or a
	remainder already carries the name it was created under, and the size
	maths cannot rebuild it - a circle has no length and width, and a
	remainder has no size at all. Renaming either would orphan the stock,
	batch and serial that point at the old name.
	"""
	if is_cutting_generated(doc):
		# cutting.py named it and set item_name alongside; the link has to
		# agree with the name, exactly as the plate branch below keeps them.
		doc.name = doc.item_name or doc.name
		doc.item_code = doc.name
		return

	if is_finished_good(doc):
		# A finished good is a product the customer makes, and it is named
		# from the Project it is made for - not from a size. The rule lives in
		# finished_goods.item_hooks, and the plate rules must not claim it.
		return

	if doc.custom_thickness_dropdown and doc.item_group:
		doc.name = build_plate_item_name(
			doc.item_group,
			get_item_thickness_mm(doc),
			doc.custom_length_mm,
			doc.custom_width_mm,
		)
	elif doc.item_name:
		doc.name = doc.item_name
	else:
		frappe.throw("Item Name is required for items without thickness.")

	# Item links are stored against the name, so item_code has to follow it.
	# ERPNext's Item controller keeps the two in step on a plain save, but this
	# hook replaces doc.name, so item_code has to be set here too.
	doc.item_code = doc.name


def is_cutting_generated(doc) -> bool:
	"""Whether this Item is a piece of a cut plate rather than a plate size.

	`custom_is_offcut` covers both offcuts - rectangular and circular - and
	`custom_is_remainder` covers the piece a plate was cut down to. Neither is
	named by the plate size rules: the cutting code owns the name, and on a
	remainder there is not even a size to name it from.
	"""
	return bool(doc.custom_is_offcut or doc.custom_is_remainder)


def is_finished_good(doc) -> bool:
	"""Whether this Item is a finished good, which is named from its Project.

	The plate naming rules are about a plate's size. A finished good is a
	product the customer makes, and its code is built from the Project it is
	made for, so the plate rules must not claim it.
	"""
	return is_finished_good_group(doc.get("item_group"))


def item_validate(doc, method):
	"""Keep an Item's name, description, weight and stock options in step."""
	if is_finished_good(doc):
		# A finished good is not a plate size: it is not weighed per piece and
		# it is not named from its dimensions.
		return

	if not (doc.custom_thickness_dropdown and doc.item_group):
		return

	thickness_mm = get_item_thickness_mm(doc)
	length_mm = doc.custom_length_mm
	width_mm = doc.custom_width_mm

	if is_cutting_generated(doc):
		# Named by the cutting process, sized by it too. The size maths below
		# would rename the Item (a remainder has no size to name it from) or
		# refuse to weigh it (a circle has no length and width), so only the
		# stock options still apply: these pieces are weighed, serialised and
		# batched like any other plate item.
		if is_weighed_group(doc.item_group):
			apply_plate_item_defaults(doc)
		return

	expected_name = build_plate_item_name(doc.item_group, thickness_mm, length_mm, width_mm)

	if doc.get("__islocal"):
		doc.name = expected_name
		doc.item_code = expected_name
	else:
		if doc.name != expected_name:
			frappe.msgprint(
				f"Item name is {doc.name} but its dimensions give {expected_name}. "
				"The name is not changed on save.",
				alert=True,
			)

	if doc.item_name != expected_name:
		doc.item_name = expected_name

	if doc.description == "*New*" or not doc.description:
		doc.description = build_plate_description(thickness_mm, length_mm, width_mm)

	if is_weighed_group(doc.item_group):
		refresh_estimated_weight(doc, thickness_mm, length_mm, width_mm)
		apply_plate_item_defaults(doc)


def refresh_estimated_weight(doc, thickness_mm, length_mm, width_mm) -> None:
	"""Keep the stored theoretical weight in step with the dimensions.

	A new Item is strict: if the weight cannot be worked out that is a setup
	mistake and it should be reported now, not later on a receipt.

	An Item that already exists is not. Half-configured legacy Items are common
	after this migration and blocking their edits would be worse than leaving a
	stale weight on file, so the reason is reported and the stored value stands.
	"""
	try:
		set_estimated_weight(doc, thickness_mm, length_mm, width_mm)
	except frappe.ValidationError as error:
		if doc.get("__islocal"):
			raise
		frappe.msgprint(
			_("Item {0} keeps its existing estimated weight. It could not be recalculated: {1}").format(
				doc.name, error
			),
			alert=True,
		)


def set_estimated_weight(doc, thickness_mm, length_mm, width_mm) -> None:
	"""Store the theoretical weight of one piece on the Item.

	Both custom_estimated_weight and weight_per_unit get the same number so
	purchasing can quote a weight per piece without recomputing anything.
	"""
	weight = compute_theoretical_weight(doc.item_group, thickness_mm, length_mm, width_mm)

	doc.set("custom_estimated_weight", weight)
	doc.set("weight_per_unit", weight)
	doc.set("weight_uom", "Kg")
