# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Small formatting helpers shared by the MS Plate code."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import frappe
from frappe import _

# Dimensions are millimetres. Three decimals is one micron, which is far finer
# than anything the workshop can measure.
DIMENSION_PRECISION = 3


def round_half_up(value, precision: int = 0) -> float:
	"""Round half away from zero, like the Math.round the old JS used.

	Python's built-in round() is banker's rounding, so round(245.3125, 3)
	returns 245.312 while JavaScript's Math.round(245.3125 * 1000) / 1000
	returns 245.313. Plate weights were always shown the JavaScript way, so the
	server has to agree with it or stock values will shift under the customer.
	"""
	try:
		number = Decimal(str(value).strip())
	except (InvalidOperation, ValueError, ArithmeticError):
		frappe.throw(_("{0} is not a number.").format(value))

	return float(number.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP))


def fmt_dim(value) -> str:
	"""Render a dimension for an item name.

	Whole numbers lose the ".0" that a Float field carries - 2500.0 becomes
	2500, so the name is MS Plate 250-10x2500x1250 and not ...x2500.0x1250.0.
	Anything else keeps at most DIMENSION_PRECISION decimals with no trailing
	zeros.
	"""
	if value is None or value == "":
		return ""

	try:
		number = Decimal(str(value).strip())
	except (InvalidOperation, ValueError, ArithmeticError):
		frappe.throw(_("{0} is not a valid dimension.").format(value))

	number = number.quantize(
		Decimal(1).scaleb(-DIMENSION_PRECISION),
		rounding=ROUND_HALF_UP,
	)

	if number == number.to_integral_value():
		return str(int(number))

	return format(number.normalize(), "f")


def build_plate_item_name(item_group, thickness_mm, length_mm, width_mm) -> str:
	"""Name a plate item from its grade and its size.

	Format: <Item Group>-<T>x<L>x<W>, e.g. MS Plate 250-10x2500x1250.

	Only the dimensions that are set are used, so a thickness-only master still
	gets a name. Thickness is the one dimension that has to be there.
	"""
	if not item_group:
		frappe.throw(_("Item Group is required to name a plate item."))

	dimensions = []
	for value in (thickness_mm, length_mm, width_mm):
		if value is None or value == "":
			continue
		dimensions.append(fmt_dim(value))

	if not dimensions:
		frappe.throw(_("Thickness is required to name a plate item."))

	return "-".join([item_group, "x".join(dimensions)])


def build_plate_description(thickness_mm, length_mm, width_mm) -> str:
	"""Human readable size, e.g. '10 x 2500 x 1250 mm'."""
	dimensions = [fmt_dim(value) for value in (thickness_mm, length_mm, width_mm) if value not in (None, "")]

	if not dimensions:
		return ""

	return " x ".join(dimensions) + " mm"
