# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe

from addsol_nl_custom.addsol_nl_custom.plates.weight import formula_variables


def item_group_validate(doc, method):
	"""Check a weighed Item Group before it is saved.

	An Item Group with no formula is an ordinary group and is left alone. Once
	a formula is there it has to be safe arithmetic over the allowed names, and
	the multiplication factor has to be a real number, because every Item under
	the group will be valued with the two of them.

	Progressive setup stays possible: a group can be created first and given its
	formula later.
	"""
	if not doc.get("custom_formula"):
		return

	formula_variables(doc.custom_formula)

	mf = frappe.utils.flt(doc.get("custom_multiplication_factor"))
	if mf <= 0:
		frappe.throw(
			frappe._(
				"Item Group {0} has a Formula, so its Multiplication Factor (MF) must be greater than 0."
			).format(doc.name),
			title=frappe._("Invalid weight formula"),
		)
