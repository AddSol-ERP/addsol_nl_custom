"""Say out loud that every offcut cut so far was rectangular.

Plate Offcut Item gained a `shape` (Rectangle or Circle) when circular cuts
were introduced. Every line that existed before that was drawn as a
rectangle - there was no other kind - but the column arrives empty, and an
empty shape only stays harmless because cutting.is_circle reads blank as
Rectangle.

This writes the fact down so nothing has to rely on that fallback: a report,
a filter or a future shape can take `shape` at its word. Only blank rows are
touched, so re-running it is a no-op, and it never rewrites a line somebody
has since marked as a circle.

Post-model-sync on purpose: the column is created by the DocType sync that
runs first in this migrate, and a patch in the pre-model-sync section could
not see it at all. Sites that installed the app after circular cuts existed
have nothing to backfill and this finds no rows.
"""

import frappe

from addsol_nl_custom.patches import with_developer_mode_restored


@with_developer_mode_restored
def execute():
	if not frappe.db.table_exists("Plate Offcut Item"):
		return

	if "shape" not in frappe.db.get_table_columns("Plate Offcut Item"):
		# The DocType sync has not run on this site yet, so there is nothing
		# to write into. The next migrate will find these rows again.
		return

	stamped = frappe.db.sql(
		"""
		update `tabPlate Offcut Item`
		   set shape = 'Rectangle'
		 where ifnull(shape, '') = ''
		"""
	)

	frappe.db.commit()
	print(f"Offcut shape: {stamped} existing offcut line(s) marked as Rectangle.")
