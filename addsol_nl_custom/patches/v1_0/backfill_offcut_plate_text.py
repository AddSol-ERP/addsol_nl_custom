"""Name the plate on cuttings that were filed before the form said it out loud.

Plate Offcut gained `source_plate_text` - the Item and Batch of the plate
being cut, spelled out under the serial - as a stored field, so a submitted
cutting shows what it was cut from without the live preview being asked.
Cuttings saved before that field existed arrive with it blank, and a
submitted document never runs set_source again, so they would stay blank
for good. This reads each one's serial and writes the same words the form
would have shown.

The live reader cannot be reused here: get_source_details refuses a serial
that is not Active, and the whole point of a submitted cutting is that its
plate has since been Consumed. So the serial and Item are read directly -
just the two fields the text is made of - and cut into words by the very
helper the live path uses, so the two can never spell a plate differently.

Only blank rows are touched, so re-running it is a no-op, and a cutting
somebody has since re-saved keeps the text their save wrote.

Post-model-sync on purpose: the column is created by the DocType sync that
runs first in this migrate. A site that has not run that sync yet has
nothing to write into, and the next migrate will find these rows again.
"""

import frappe

from addsol_nl_custom.addsol_nl_custom.plates.cutting import plate_text_for
from addsol_nl_custom.patches import with_developer_mode_restored


@with_developer_mode_restored
def execute():
	if not frappe.db.table_exists("Plate Offcut"):
		return

	if "source_plate_text" not in frappe.db.get_table_columns("Plate Offcut"):
		# The DocType sync has not run on this site yet, so there is nothing
		# to write into. The next migrate will find these rows again.
		return

	blank = frappe.get_all(
		"Plate Offcut",
		filters={"source_plate_text": ["in", ["", None]], "source_serial_no": ["!=", ""]},
		fields=["name", "source_serial_no"],
	)
	if not blank:
		return

	# One read for every serial and Item named, rather than a pair per row:
	# a run over a few hundred cuttings should not issue a query each.
	serials = {
		row.name: row
		for row in frappe.get_all(
			"Serial No",
			filters={"name": ["in", list({d.source_serial_no for d in blank})]},
			fields=["name", "item_code", "batch_no"],
		)
	}
	items = {
		row.name: row.item_name
		for row in frappe.get_all(
			"Item",
			filters={"name": ["in", list({s.item_code for s in serials.values()})]},
			fields=["name", "item_name"],
		)
	}

	stamped = 0
	for doc in blank:
		serial = serials.get(doc.source_serial_no)
		if not serial:
			# The serial has been deleted since; there is nothing left to
			# name the plate from, and inventing one would be a lie.
			continue

		frappe.db.set_value(
			"Plate Offcut",
			doc.name,
			"source_plate_text",
			plate_text_for(items.get(serial.item_code), serial.item_code, serial.batch_no),
			update_modified=False,
		)
		stamped += 1

	frappe.db.commit()
	print(f"Plate Offcut: {stamped} existing cutting(s) named with their Item and Batch.")
