# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SupplierGradeRate(Document):
	"""One row of a supplier's Grade Rates (per Kg) table.

	Deliberately empty. The overlap check belongs to the whole table, so it
	lives on Supplier where every sibling row is visible.
	"""

	pass
