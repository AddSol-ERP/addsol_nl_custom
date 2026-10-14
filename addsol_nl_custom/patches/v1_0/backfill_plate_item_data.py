"""Part B - backfill the values the old code could not compute.

Two things are wrong on an existing site:

* ``Item.item_code`` still holds the ``*New*`` placeholder, because the old
  ``item_autoname`` only ever set ``doc.name``. Item links point at the name,
  so the two are out of step.
* ``Thickness.thickness_mm`` does not exist yet, because the thickness number
  used to be dug out of the label with a regular expression.

Only rows this app owns are touched. Anything that does not match is counted
and printed so it can be reviewed by hand.

Idempotent.
"""

import frappe

# Item Groups are a tree, so walk it rather than trying to guess the names.
PLATE_MARKERS = ("custom_thickness_dropdown", "custom_length_mm", "custom_width_mm")


def execute():
	backfill_thickness_mm()
	backfill_item_code()


def backfill_thickness_mm():
	"""Fill Thickness.thickness_mm from the existing label."""
	if not frappe.db.exists("Custom Field", "Thickness-thickness_mm"):
		# The field has not reached the database yet. It arrives with the
		# DocType on the same migrate that runs this patch, but stay safe.
		frappe.db.add_column("Thickness", "thickness_mm", "float")
		frappe.db.commit()

	rows = frappe.get_all(
		"Thickness",
		filters={"thickness_mm": ("is", "not set")},
		fields=["name", "thickness_value"],
		ignore_ifnull=True,
	)

	if not rows:
		print("Thickness: nothing to backfill.")
		return

	for row in rows:
		try:
			label, number = _split(row.thickness_value)
		except Exception:
			print(f"Thickness: skipped '{row.name}' - cannot read '{row.thickness_value}'.")
			continue

		frappe.db.set_value("Thickness", row.name, "thickness_mm", number, update_modified=False)
		frappe.db.set_value("Thickness", row.name, "thickness_value", label, update_modified=False)

	print(f"Thickness: backfilled thickness_mm on {len(rows)} record(s).")


def backfill_item_code():
	"""Set item_code = name, but only on the plate items this app created."""
	plate_items = frappe.get_all(
		"Item",
		filters={"name": ["!=", "item_code"]},
		or_filters=[{marker: ("is", "set")} for marker in PLATE_MARKERS],
		fields=["name", "item_code", "item_group"],
		limit_page_length=0,
	)

	for item in plate_items:
		frappe.db.set_value("Item", item.name, "item_code", item.name, update_modified=False)
		print(f"Item: {item.name} - item_code '{item.item_code}' set to the item name.")

	skipped = frappe.db.count("Item", {"name": ["!=", "item_code"]}) - len(plate_items)
	if skipped:
		print(
			f"Item: {skipped} other item(s) still have item_code != name. They are not plate "
			"items, so they were left alone. Review them by hand if you need to."
		)


def _split(value):
	"""Reuse the Thickness normalisation so the patch and the DocType agree."""
	from addsol_nl_custom.addsol_nl_custom.doctype.thickness.thickness import Thickness

	return Thickness.split_thickness(value)
