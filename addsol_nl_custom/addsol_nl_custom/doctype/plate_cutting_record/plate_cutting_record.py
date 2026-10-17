# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from addsol_nl_custom.addsol_nl_custom.plates import cutting
from addsol_nl_custom.addsol_nl_custom.plates.settings import get_setting

STATUS_DRAFT = "Draft"
STATUS_RECORDED = "Recorded"
STATUS_STOCK_UPDATED = "Stock Updated"


class PlateCuttingRecord(Document):
	"""One plate cut into offcuts plus scrap."""

	def validate(self):
		self.set_source()
		self.set_offcut_values()
		self.set_totals()

	def on_submit(self):
		self.create_offcut_stock()

	def on_cancel(self):
		self.remove_offcut_stock()

	def set_source(self):
		"""Read the plate being cut and fill in everything derived from it."""
		details = cutting.get_offcut_details(self.source_serial_no)

		self.source_item = details["item"]
		self.source_batch = details["batch"]
		self.heat_number = details["heat_number"]
		self.source_weight_kg = details["weight"]
		self.source_cost_per_kg = details["cost_per_kg"]
		self.ratio = details["ratio"]
		self.thickness_mm = details["thickness_mm"]
		self.source_length_mm = details["length_mm"]
		self.source_width_mm = details["width_mm"]

		# Last, because the check reads self.source_item - which is only real
		# once the lines above have run.
		self.check_in_work_order()

	def check_in_work_order(self):
		"""The plate has to be in this work order's WIP and be one of its required items."""
		if not self.work_order:
			return

		wip = frappe.db.get_value("Work Order", self.work_order, "wip_warehouse")
		warehouse = frappe.db.get_value("Serial No", self.source_serial_no, "warehouse")

		if wip and warehouse and warehouse != wip:
			frappe.throw(
				_("Serial No {0} is in {1}, not in the Work Order's WIP warehouse {2}.").format(
					self.source_serial_no, warehouse, wip
				),
				title=_("Plate is not in the WIP warehouse"),
			)

		# The Work Order's required_items table, not BOM Item: it is the
		# Work Order's own view of what it consumes (exploded for multi-level
		# BOMs), and BOM Item's parent is a BOM name, never a Work Order name.
		required = frappe.get_all(
			"Work Order Item",
			filters={"parent": self.work_order, "item_code": self.source_item},
			pluck="name",
		)
		if not required:
			frappe.throw(
				_("Serial No {0} is not a required item of Work Order {1}.").format(
					self.source_serial_no, self.work_order
				),
				title=_("Plate is not in this Work Order"),
			)

	def set_offcut_values(self):
		# Read the plate again rather than trusting the fields set_source
		# assigned: same serial, same Item, same numbers - and the weights stay
		# right even if this is ever run on its own.
		details = cutting.get_offcut_details(self.source_serial_no)

		for row in self.offcuts:
			cutting.check_offcut_fits(self, row, details)
			cutting.compute_offcut(row, details)

	def set_totals(self):
		cutting.compute_totals(self)

	def create_offcut_stock(self):
		"""Create the Item, Batch and reserved serial number for each offcut.

		The serial numbers themselves are created when the Manufacture Stock
		 Entry takes the offcuts in. Allocating the names here keeps the record
		and the later stock movement pointing at the same thing.
		"""
		offcut_batch_series = get_setting("offcut_batch_series", "OFB-.YY.-.#####")

		for row in self.offcuts:
			row.offcut_item = cutting.get_or_create_offcut_item(self.source_item, row.length_mm, row.width_mm)
			row.batch_no = self.make_offcut_batch(row, offcut_batch_series)
			row.serial_no = cutting.reserve_serial_no(row.offcut_item)

		self.status = STATUS_RECORDED

	def make_offcut_batch(self, row, series):
		from frappe.model.naming import make_autoname

		batch = {
			"doctype": "Batch",
			"item": row.offcut_item,
			"custom_heat_number": self.heat_number,
			"custom_mtc_no": getattr(self, "mtc_no", None),
			"custom_grade": frappe.db.get_value("Item", row.offcut_item, "item_group"),
			"custom_source_batch": self.source_batch,
			"custom_weight_per_plate_kg": row.weight_kg,
			"custom_cost_per_kg": self.source_cost_per_kg,
			"custom_actual_to_theoretical_ratio": self.ratio,
		}

		while True:
			name = make_autoname(series, doc=batch)
			if not frappe.db.exists("Batch", name):
				break

		batch["batch_id"] = name
		frappe.get_doc(batch).insert(ignore_permissions=True)

		return name

	def remove_offcut_stock(self):
		"""Cancel only while the offcuts have not been moved into stock yet."""
		if self.status != STATUS_RECORDED:
			frappe.throw(
				_(
					"This record is '{0}' so its offcuts have already been taken into stock. "
					"Cancel that Stock Entry first."
				).format(self.status),
				title=_("Offcuts already in stock"),
			)

		for row in self.offcuts:
			if row.get("batch_no") and frappe.db.exists("Batch", row.batch_no):
				frappe.delete_doc("Batch", row.batch_no, force=True, ignore_missing=True)

		self.status = STATUS_DRAFT
