"""Backfill batch and serial metadata from receipts already submitted.

`receipt_meta.apply_receipt_metadata` runs on Purchase Receipt submit, so
receipts that went in before it existed have a batch with no heat number, no
weight and no cost per kg, and the plate reports show blanks.

This walks the submitted receipts and stamps what it can, using exactly the
same helpers the live hook uses, so a batch looks identical whether it was
stamped now or at submit time.

Idempotent, and never overwrites a real value with a zero or a blank.
"""

import frappe

from addsol_nl_custom.addsol_nl_custom.plates import receipt_meta
from addsol_nl_custom.patches import with_developer_mode_restored


@with_developer_mode_restored
def execute():
	rows = frappe.get_all(
		"Purchase Receipt Item",
		filters={
			"parenttype": "Purchase Receipt",
			"docstatus": 1,
			"serial_and_batch_bundle": ("is", "set"),
		},
		fields=[
			"parent",
			"idx",
			"item_code",
			"qty",
			"rate",
			"serial_and_batch_bundle",
			"custom_is_plate",
			"custom_rate_per_kg",
			"custom_billable_weight_kg",
			"custom_est_weight_kg",
			"custom_weight_per_plate_kg",
		],
		order_by="parent asc, idx asc",
		limit_page_length=0,
	)

	interesting = [row for row in rows if row.custom_is_plate]

	print(f"Batch metadata: {len(interesting)} of {len(rows)} submitted receipt line(s) to check.")

	if not interesting:
		return

	receipts = {name: frappe._dict(name=name) for name in {row.parent for row in rows}}

	stamped_batches = 0
	stamped_serials = 0

	for row in interesting:
		before_batches, before_serials = count_plate_records(row.serial_and_batch_bundle)

		# receipt_meta prints its own reason when there is nothing to stamp,
		# which is what makes this diagnostic rather than silent.
		receipt_meta.stamp_row(receipts[row.parent], row)

		after_batches, after_serials = count_plate_records(row.serial_and_batch_bundle)
		stamped_batches += max(after_batches - before_batches, 0)
		stamped_serials += max(after_serials - before_serials, 0)

	print(
		f"Batch metadata: {stamped_batches} batch(es) and {stamped_serials} serial(s) "
		"gained a weight or a heat number."
	)


def count_plate_records(bundle):
	"""How many batches and serials on this bundle already carry a weight."""
	if not bundle:
		return (0, 0)

	batches = frappe.db.sql(
		"""
		select count(*) from `tabBatch`
		 where custom_weight_per_plate_kg > 0
		   and name in (
		         select batch_no from `tabSerial and Batch Entry`
		          where parent = %s and parenttype = 'Serial and Batch Bundle'
		   )
		""",
		(bundle,),
	)[0][0]

	serials = frappe.db.sql(
		"""
		select count(*) from `tabSerial No`
		 where custom_weight_kg > 0
		   and name in (
		         select serial_no from `tabSerial and Batch Entry`
		          where parent = %s and parenttype = 'Serial and Batch Bundle'
		   )
		""",
		(bundle,),
	)[0][0]

	return batches, serials
