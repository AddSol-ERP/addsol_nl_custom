# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""One plate consumed whole, producing offcuts plus the scrap that balances it.

Decoupled from any Work Order or Job Card: the plate is wherever it sits in
stock, and the submit creates and submits a Repack Stock Entry that takes the
plate out and puts the offcuts (and the balancing scrap) back into the same
warehouse. Every destination row carries its rate by hand - value is weight
times the source batch's cost per kg - because ERPNext refuses to guess rates
across several different finished items in one Repack, and its own guess
(even split per unit) is not what an offcut is worth.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from addsol_nl_custom.addsol_nl_custom.plates import cutting
from addsol_nl_custom.addsol_nl_custom.plates.settings import get_setting


class PlateOffcut(Document):
	"""One plate cut into offcuts plus the scrap that balances the weight."""

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
		self.warehouse = details["warehouse"]

		# Without a warehouse there is no Repack: a row with no s_warehouse is
		# an inbound row to ERPNext, and the plate would come back IN instead
		# of going out.
		if not self.warehouse:
			frappe.throw(
				_("Serial No {0} is not in any warehouse, so there is nothing to cut.").format(
					self.source_serial_no
				),
				title=_("Plate is not in stock"),
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
		if not self.offcuts:
			frappe.throw(
				_("Add at least one offcut. A plate booked straight to scrap is not a cutting."),
				title=_("No offcuts"),
			)

		# The plate is consumed whole, so whatever the offcuts do not weigh
		# has to leave as scrap - otherwise that weight and the value behind it
		# vanish from stock the moment the Repack posts.
		self.scrap_weight_kg = cutting.auto_scrap_weight(
			self.source_weight_kg, [row.weight_kg for row in self.offcuts]
		)

		cutting.compute_totals(self)

		if frappe.utils.flt(self.scrap_weight_kg) > 0 and not get_setting("scrap_item"):
			frappe.throw(
				_(
					"This cutting leaves {0} kg of scrap, but Plate Settings has no scrap Item set."
				).format(self.scrap_weight_kg),
				title=_("Scrap Item not set"),
			)

	def create_offcut_stock(self):
		"""Create the Item, Batch and reserved Serial No per offcut, then repack.

		The Repack's submit creates the reserved serial numbers in stock.
		Allocating the names here keeps this document and the stock movement
		pointing at the same thing.
		"""
		offcut_batch_series = get_setting("offcut_batch_series", "OFB-.YY.-.#####")

		for row in self.offcuts:
			row.offcut_item = cutting.get_or_create_offcut_item(self.source_item, row.length_mm, row.width_mm)
			if not row.batch_no:
				row.batch_no = self.make_offcut_batch(row, offcut_batch_series)
			if not row.serial_no:
				row.serial_no = cutting.reserve_serial_no(row.offcut_item)

		self.make_repack()

		# db_update ran before on_submit, so anything decided here has to be
		# written explicitly - the Item, Batch and Serial No names above, and
		# the Stock Entry this submit created.
		self.db_update()
		for row in self.offcuts:
			row.db_update()

		self.stamp_offcut_serials()

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

	def make_repack(self):
		"""The Stock Entry that consumes the plate and puts the pieces back.

		A Repack, not a Manufacture: there is no work order and no bill of
		materials, only one plate in and several pieces out. Every destination
		row carries its rate by hand, basic_rate AND basic_amount - ERPNext
		skips manual rows entirely and would otherwise leave basic_amount at
		zero, and with more than one finished item it refuses to submit at all
		unless every row is manual.
		"""
		company = frappe.db.get_value("Warehouse", self.warehouse, "company", cache=True)
		if not company:
			frappe.throw(
				_("Warehouse {0} does not belong to any company, so no Stock Entry can be made from it.").format(
					self.warehouse
				),
				title=_("Warehouse has no company"),
			)

		stock_entry = frappe.new_doc("Stock Entry")
		# stock_entry_type is the real Link field; purpose is only its
		# fetch-from shadow and validate fills it from the type.
		stock_entry.stock_entry_type = "Repack"
		stock_entry.purpose = "Repack"
		stock_entry.company = company
		# The Stock Entry is an implementation detail of this document; the
		# permission gate is submitting the Plate Offcut itself.
		stock_entry.flags.ignore_permissions = True

		stock_entry.append(
			"items",
			{
				"s_warehouse": self.warehouse,
				"item_code": self.source_item,
				"qty": 1,
				"serial_no": self.source_serial_no,
				"batch_no": self.source_batch,
				"use_serial_batch_fields": 1,
			},
		)

		for row in self.offcuts:
			stock_entry.append(
				"items",
				{
					"t_warehouse": self.warehouse,
					"item_code": row.offcut_item,
					"qty": 1,
					"serial_no": row.serial_no,
					"batch_no": row.batch_no,
					"use_serial_batch_fields": 1,
					"set_basic_rate_manually": 1,
					"basic_rate": row.value,
					"basic_amount": row.value,
				},
			)

		if frappe.utils.flt(self.scrap_weight_kg) > 0:
			stock_entry.append(
				"items",
				{
					"t_warehouse": self.warehouse,
					"item_code": get_setting("scrap_item"),
					"qty": self.scrap_weight_kg,
					"uom": "Kg",
					"conversion_factor": 1,
					"set_basic_rate_manually": 1,
					"basic_rate": self.source_cost_per_kg,
					"basic_amount": self.scrap_value,
				},
			)

		stock_entry.insert()
		stock_entry.submit()

		self.stock_entry = stock_entry.name

	def stamp_offcut_serials(self):
		"""Point each new serial back at the plate it was cut from."""
		for row in self.offcuts:
			frappe.db.set_value(
				"Serial No",
				row.serial_no,
				{
					"custom_weight_kg": row.weight_kg,
					"custom_source_serial_no": self.source_serial_no,
				},
			)

	def remove_offcut_stock(self):
		"""Cancel the Repack, then take the names back.

		ERPNext refuses to cancel the Repack once an offcut serial has moved
		on in a later transaction - which is exactly right: the plate cannot
		reappear while pieces of it already sit elsewhere. That throw is left
		standing; this only cleans up what the submit created.
		"""
		if self.stock_entry and frappe.db.exists("Stock Entry", self.stock_entry):
			stock_entry = frappe.get_doc("Stock Entry", self.stock_entry)
			if stock_entry.docstatus == 1:
				stock_entry.flags.ignore_permissions = True
				stock_entry.cancel()

		for row in self.offcuts:
			if row.batch_no and frappe.db.exists("Batch", row.batch_no):
				frappe.delete_doc("Batch", row.batch_no, force=True, ignore_missing=True)

			if row.serial_no or row.batch_no:
				# A cancelled attempt leaves an inactive Serial No behind, and
				# ERPNext is wary of re-inwarding an existing serial. Blank the
				# names so a re-submit reserves fresh ones instead.
				frappe.db.set_value("Plate Offcut Item", row.name, {"serial_no": None, "batch_no": None})
				row.serial_no = None
				row.batch_no = None
