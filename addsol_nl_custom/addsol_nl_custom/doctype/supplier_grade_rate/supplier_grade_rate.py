# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SupplierGradeRate(Document):
	"""One row of a supplier's Grade Rates (per Kg) table.

	The grade has to be a weighed one. This was originally a link_filters
	query on the picker, but that only hides rows - it stops nothing. A
	validation is better: a rate cannot be saved against a group that has no
	weight formula, so a Purchase Order can never pick one up and try to price
	by weight with no formula behind it.

	The overlap check lives on Supplier, where every sibling row is visible.
	"""

	def validate(self):
		self.check_grade_is_weighed()

	def check_grade_is_weighed(self):
		if not self.item_group:
			return

		from addsol_nl_custom.addsol_nl_custom.plates.grouping import is_weighed_group

		if is_weighed_group(self.item_group):
			return

		frappe.throw(
			frappe._(
				"{0} is not a weighed grade. A rate per kg only makes sense for an Item "
				"Group that has a weight Formula - set one, or pick a different grade."
			).format(self.item_group),
			title=frappe._("Not a weighed grade"),
		)
