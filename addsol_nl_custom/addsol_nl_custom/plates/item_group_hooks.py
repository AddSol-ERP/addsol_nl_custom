# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe

from addsol_nl_custom.addsol_nl_custom.plates.weight import formula_variables


def item_group_validate(doc, method):
	"""Check a grade that has opted in before it is saved.

	Only a group with the weighed grade flag on has to be usable. An unticked
	group can carry a half-finished formula while it is being set up, which
	keeps progressive setup possible; ticking the flag is the moment the
	formula and the multiplication factor have to be real, because from then on
	every Item under the group is valued with them.
	"""
	if not doc.get("custom_is_weighed_grade"):
		return

	if not doc.get("custom_formula"):
		frappe.throw(
			frappe._("Item Group {0} is marked as a weighed grade, so it needs a Formula.").format(doc.name),
			title=frappe._("Invalid weight formula"),
		)

	formula_variables(doc.custom_formula)

	if frappe.utils.flt(doc.get("custom_multiplication_factor")) <= 0:
		frappe.throw(
			frappe._(
				"Item Group {0} is marked as a weighed grade, so its Multiplication Factor (MF) "
				"must be greater than 0."
			).format(doc.name),
			title=frappe._("Invalid weight formula"),
		)
