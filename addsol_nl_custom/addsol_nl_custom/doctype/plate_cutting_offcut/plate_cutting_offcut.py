# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PlateCuttingOffcut(Document):
	"""One offcut row on a Plate Cutting Record.

	Every field except the two dimensions is worked out by the parent when the
	record is validated, so the operator only ever types a length and a width.
	"""

	pass
