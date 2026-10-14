# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Theoretical weight of a plate, worked out on the server.

The browser used to do this, which meant an import or a script got no weight
at all. The formula itself still comes from the Item Group, so the grade owns
the rule, but it is now evaluated here through frappe.safe_eval.
"""

import ast

import frappe
from frappe import _

from addsol_nl_custom.addsol_nl_custom.plates.utils import round_half_up

# The only names a weight formula may use: the three dimensions and the
# multiplication factor. A formula is free to combine them however it likes,
# so adding a product with a different shape later means adding a name here and
# nothing else.
ALLOWED_VARIABLES = frozenset({"L", "W", "T", "MF"})

ALLOWED_OPERATORS = (ast.Add, ast.Sub, ast.Mult, ast.Div)

# Unary + and - are arithmetic too. ** is not: a huge exponent is a cheap way
# to hang the worker, so ast.Pow stays out.
ALLOWED_UNARY_OPERATORS = (ast.UAdd, ast.USub)

# ast.walk() also yields the Load/Store/Del context that hangs off every Name.
# Those are structure, not operation, so they pass straight through.
CONTEXT_NODES = (ast.expr_context,)

WEIGHT_PRECISION = 3


def formula_variables(formula) -> set[str]:
	"""Check a weight formula and return the variables it actually uses.

	The formula is walked with ast and never executed here. Only bare names
	from ALLOWED_VARIABLES, plain numbers and + - * / are accepted, so a
	formula cannot smuggle in a function call, an attribute lookup or a string.
	Anything else is rejected here, long before safe_eval sees it.

	Calling this is also how we find out what to check on the Item: a formula
	that never mentions W does not need a width.
	"""
	if not formula or not isinstance(formula, str):
		frappe.throw(_("No weight formula."), title=_("Invalid weight formula"))

	try:
		tree = ast.parse(formula, mode="eval")
	except SyntaxError:
		frappe.throw(
			_("Formula {0} is not valid Python.").format(formula),
			title=_("Invalid weight formula"),
		)

	variables = set()

	for node in ast.walk(tree):
		if isinstance(node, ast.Name):
			if node.id not in ALLOWED_VARIABLES:
				frappe.throw(
					_("{0} is not allowed in a weight formula. Use only {1}.").format(
						node.id, ", ".join(sorted(ALLOWED_VARIABLES))
					),
					title=_("Invalid weight formula"),
				)
			variables.add(node.id)

		elif isinstance(node, ast.Constant):
			if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
				frappe.throw(
					_("A weight formula may only contain numbers."),
					title=_("Invalid weight formula"),
				)

		elif isinstance(node, (ast.BinOp, *ALLOWED_OPERATORS)):
			continue

		elif isinstance(node, (ast.UnaryOp, *ALLOWED_UNARY_OPERATORS)):
			continue

		elif isinstance(node, (ast.Expression, *CONTEXT_NODES)):
			continue

		else:
			frappe.throw(
				_("A weight formula may only use {0} and numbers, arithmetic only.").format(
					", ".join(sorted(ALLOWED_VARIABLES))
				),
				title=_("Invalid weight formula"),
			)

	if not variables:
		frappe.throw(
			_("A weight formula has to use at least one of {0}.").format(
				", ".join(sorted(ALLOWED_VARIABLES))
			),
			title=_("Invalid weight formula"),
		)

	return variables


def is_safe_formula(formula) -> bool:
	"""Whether a formula is acceptable, without raising.

	Used where the answer is a yes/no - deciding whether a group is weighed, for
	instance - rather than a validation that should stop a save.
	"""
	try:
		formula_variables(formula)
	except Exception:
		return False
	return True


def compute_theoretical_weight(item_group, thickness_mm, length_mm, width_mm) -> float:
	"""Weight in Kg of one plate of this grade and size.

	Throws rather than guessing. A missing multiplication factor, a missing or
	unsafe formula, or a zero in a variable the formula actually uses all stop
	here - silently falling back to length x width x thickness is how the wrong
	weight reaches a valuation.
	"""
	mf, formula = get_plate_group_formula(item_group)

	values = {
		"L": frappe.utils.flt(length_mm),
		"W": frappe.utils.flt(width_mm),
		"T": frappe.utils.flt(thickness_mm),
		"MF": frappe.utils.flt(mf),
	}

	for variable in formula_variables(formula):
		if not values[variable]:
			frappe.throw(
				_("Plate weight formula for {0} needs {1}, but it is 0.").format(item_group, variable),
				title=_("Cannot work out the plate weight"),
			)

	weight = frappe.safe_eval(formula, None, values)

	return round_half_up(weight, WEIGHT_PRECISION)


def get_plate_group_formula(item_group) -> tuple[float, str]:
	"""Read and check the multiplication factor and formula of a weighed group."""
	if not item_group:
		frappe.throw(_("Item Group is required to work out the plate weight."))

	if not frappe.db.exists("Item Group", item_group):
		frappe.throw(_("Item Group {0} does not exist.").format(item_group))

	group = frappe.db.get_value(
		"Item Group",
		item_group,
		["custom_multiplication_factor", "custom_formula"],
		as_dict=True,
	)
	if not group:
		frappe.throw(_("Item Group {0} does not exist.").format(item_group))

	if not group.custom_multiplication_factor or group.custom_multiplication_factor <= 0:
		frappe.throw(
			_("Item Group {0} needs a Multiplication Factor (MF) greater than 0.").format(item_group),
			title=_("Cannot work out the plate weight"),
		)

	if not group.custom_formula:
		frappe.throw(
			_("Item Group {0} needs a Formula.").format(item_group),
			title=_("Cannot work out the plate weight"),
		)

	# Throws on anything that is not safe arithmetic over the allowed names.
	formula_variables(group.custom_formula)

	return group.custom_multiplication_factor, group.custom_formula


def get_item_thickness_mm(item) -> float:
	"""Thickness of an Item in mm, read from the Thickness master.

	The Thickness label is a display value like '10 mm'. Code never parses it,
	so this reads Thickness.thickness_mm. The label is only used as a fallback
	for sites where the backfill patch has not run yet.
	"""
	from addsol_nl_custom.addsol_nl_custom.doctype.thickness.thickness import Thickness

	item = frappe._dict(item) if isinstance(item, dict) else item

	thickness_name = item.get("custom_thickness_dropdown")
	if not thickness_name:
		return frappe.utils.flt(item.get("thickness_mm"))

	thickness = frappe.db.get_value(
		"Thickness", thickness_name, ["thickness_mm", "thickness_value"], as_dict=True
	)
	if not thickness:
		return 0.0

	if thickness.thickness_mm:
		return frappe.utils.flt(thickness.thickness_mm)

	_, number = Thickness.split_thickness(thickness.thickness_value)
	return frappe.utils.flt(number)
