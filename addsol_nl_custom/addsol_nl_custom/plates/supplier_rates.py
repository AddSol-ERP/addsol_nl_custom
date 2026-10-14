# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""A supplier's rate per kilogram, one row per grade.

A Purchase Order reads its rate from here and then fixes it, so a later change
to this table never moves a price that has already been agreed.
"""

import frappe

from addsol_nl_custom.addsol_nl_custom.plates.utils import round_half_up


def find_rate(supplier, item_group, on_date=None) -> float:
	"""The rate per kg this supplier charges for this grade on a date.

	Returns 0.0 when there is no matching row, so the caller can decide whether
	that is worth an error - on a Purchase Order it is.
	"""
	if not supplier or not item_group:
		return 0.0

	rows = frappe.get_all(
		"Supplier Grade Rate",
		filters={"parent": supplier, "item_group": item_group},
		fields=["rate_per_kg", "valid_from", "valid_upto", "idx"],
		order_by="idx asc",
		limit_page_length=0,
	)

	if not rows:
		return 0.0

	d = frappe.utils.getdate(on_date) if on_date else None
	matching = [row for row in rows if covers(row, d)]

	if not matching:
		# No row covers the date. Fall back to any row that carries no dates at
		# all, otherwise to the most recent, so an undated or expired table
		# still prices something rather than silently zero.
		undated = [row for row in rows if not row.valid_from and not row.valid_upto]
		matching = undated or rows[-1:]

	return round_half_up(frappe.utils.flt(matching[-1].rate_per_kg), 4)


def covers(row, on_date) -> bool:
	"""Whether this row's validity window includes the given date."""
	if not on_date:
		return True

	if row.valid_from and on_date < frappe.utils.getdate(row.valid_from):
		return False

	if row.valid_upto and on_date > frappe.utils.getdate(row.valid_upto):
		return False

	return True


def check_no_overlap(doc, method=None) -> None:
	"""Two rates for one grade must not cover the same day.

	Checked on Supplier because that is where every sibling row is visible.
	"""
	if not doc.get("custom_grade_rates"):
		return

	by_grade = {}
	for index, row in enumerate(doc.custom_grade_rates):
		if not row.item_group:
			continue
		by_grade.setdefault(row.item_group, []).append((index + 1, row))

	for item_group, rows in by_grade.items():
		for position, (first_no, first) in enumerate(rows):
			for second_no, second in rows[position + 1 :]:
				if overlap(first, second):
					frappe.throw(
						frappe._(
							"Rows {0} and {1} both cover the same dates for grade {2}. A grade "
							"can only have one rate per period."
						).format(first_no, second_no, item_group),
						title=frappe._("Overlapping Grade Rates"),
					)


def overlap(first, second) -> bool:
	"""Do two validity windows share at least one day?"""
	first_from = first.valid_from
	first_to = first.valid_to or first.valid_upto
	second_from = second.valid_from
	second_to = second.valid_to or second.valid_upto

	# An open end is far away rather than missing.
	first_to = first_to or "9999-12-31"
	second_to = second_to or "9999-12-31"

	if first_from and second_to and first_from > second_to:
		return False

	if second_from and first_to and second_from > first_to:
		return False

	return True
