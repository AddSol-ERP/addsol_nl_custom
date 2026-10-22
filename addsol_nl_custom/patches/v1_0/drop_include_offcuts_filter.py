"""Drop the `include_offcuts` filter from the Plate Stock Register.

The offcut pieces are reported by `Plate Offcut Register` now, so the plate
register holds one population -- whole plates and the remainder a cutting
leaves behind -- instead of two.

The filter was not merely unused. It defaulted to ON, so leaving it would keep
every offcut row in the plate register, which is the double counting this
change exists to stop.

The fixture that ships the Report record no longer declares the filter, but a
fixture import does not necessarily remove child rows the fixture no longer
carries -- and the fixture import runs AFTER the patch phase, so a row this
patch does not delete can survive the migrate. Deleting it here is what makes
the removal real.
"""

import frappe

from addsol_nl_custom.patches import with_developer_mode_restored

REPORT_NAME = "Plate Stock Register"
FILTER_NAME = "include_offcuts"


@with_developer_mode_restored
def execute():
	if not frappe.db.exists("Report", REPORT_NAME):
		return

	doc = frappe.get_doc("Report", REPORT_NAME)

	if not any(row.fieldname == FILTER_NAME for row in doc.filters):
		return

	doc.filters = [row for row in doc.filters if row.fieldname != FILTER_NAME]
	doc.flags.ignore_permissions = True
	# Saving an existing Report re-validates its links, and this report's
	# `letter_head` is already "Standard" on sites that have no such Letter Head
	# (fixture import stored it with `ignore_links`, see
	# `frappe/modules/import_file.py:233`). Without this the patch would die on
	# `LinkValidationError: Could not find Letter Head: Standard` before it ever
	# removed the filter. Only the filter row is being changed here.
	doc.flags.ignore_links = True
	doc.save()


if __name__ == "__main__":
	execute()
