"""Part B - backfill the values the old code could not compute.

Two things are wrong on an existing site:

* ``Item.item_code`` still holds the ``*New*`` placeholder, because the old
  ``item_autoname`` only ever set ``doc.name``. Item links point at the name,
  so the two are out of step.
* ``Thickness.thickness_mm`` is empty, because the thickness number used to be
  dug out of the label with a regular expression.

Only rows this app owns are touched. Anything that does not match is counted
and printed so it can be reviewed by hand.

Runs after ``sync_all()``, so ``thickness.json`` has already been synced and
the ``thickness_mm`` column is already in the database - this patch only fills
it, it never creates it.

Idempotent.
"""

import frappe

# An Item Group carrying a weight formula makes every Item under it a weighed
# item. That, rather than any flag, is what identifies the plate items here.
PLATE_GROUP_WHERE = "ifnull(g.custom_formula, '') != ''"


def execute():
	backfill_thickness_mm()
	backfill_item_code()


def backfill_thickness_mm():
	"""Fill Thickness.thickness_mm from the existing label."""
	if not frappe.db.has_column("Thickness", "thickness_mm"):
		frappe.throw(
			"Thickness.thickness_mm is not in the database yet. It is added by "
			"sync_all() from thickness.json; if this is the first run, re-run "
			"bench migrate.",
			title="Cannot backfill thickness",
		)

	# Read every row rather than filtering in SQL. thickness_mm is a Float and
	# may be 0 or NULL depending on when the column was added, so a single
	# "is not set" filter would silently skip everything.
	records = frappe.get_all(
		"Thickness",
		fields=["name", "thickness_value", "thickness_mm"],
		limit_page_length=0,
	)

	todo = [row for row in records if not row.thickness_mm]

	if not todo:
		print("Thickness: thickness_mm already filled in on every record.")
		return

	from addsol_nl_custom.addsol_nl_custom.doctype.thickness.thickness import Thickness

	filled = 0
	for row in todo:
		try:
			label, number = Thickness.split_thickness(row.thickness_value)
		except Exception:
			print(f"Thickness: skipped '{row.name}' - cannot read '{row.thickness_value}'.")
			continue

		frappe.db.set_value(
			"Thickness",
			row.name,
			{"thickness_value": label, "thickness_mm": number},
			update_modified=False,
		)
		filled += 1

	print(f"Thickness: filled thickness_mm on {filled} of {len(todo)} record(s).")


def backfill_item_code():
	"""Set item_code = name on the plate items this app created."""
	plate_items = frappe.db.sql(
		f"""
		select i.name, i.item_code
		  from `tabItem` i
		  inner join `tabItem Group` g on g.name = i.item_group
		 where i.name != i.item_code
		   and {PLATE_GROUP_WHERE}
		""",
		as_dict=True,
	)

	for item in plate_items:
		frappe.db.set_value("Item", item.name, "item_code", item.name, update_modified=False)
		print(f"Item: {item.name} - item_code '{item.item_code}' set to the item name.")

	total_mismatched = frappe.db.sql("select count(*) from `tabItem` where name != item_code")[0][0]

	if total_mismatched:
		print(
			f"Item: {total_mismatched} item(s) still have item_code != name "
			"({len(plate_items)} of them plate items, which were just fixed). The rest are "
			"not plate items and were left alone. Review them by hand if you need to."
		)
