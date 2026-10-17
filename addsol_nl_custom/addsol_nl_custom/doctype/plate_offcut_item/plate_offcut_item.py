# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PlateOffcutItem(Document):
	"""One offcut row on a Plate Offcut.

	The row only carries the size the operator types. Every weight, value,
	Item, Batch and Serial No is derived on the parent, so the arithmetic
	lives in exactly one place - cutting.py and PlateOffcut - and this
	controller stays empty.
	"""

	pass
