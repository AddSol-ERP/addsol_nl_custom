# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""One plate consumed whole, cut into offcuts for one order.

Decoupled from any Work Order or Job Card: the plate is wherever it sits in
stock, and the submit creates and submits a Repack Stock Entry that takes the
plate out and puts its pieces back into the same warehouse. Every destination
row carries its rate by hand - value is weight times the source batch's cost
per kg - because ERPNext refuses to guess rates across several different
finished items in one Repack, and its own guess (even split per unit) is not
what a piece is worth.

What the offcuts and the scrap do not take is the remainder: one piece, its
own Item, batch and serial, that stays plate stock and is then issued against
the Project the cutting was made for. That second entry - a Material Issue -
is what puts the consumed value on the order: only the weight that was
actually cut for it is that order's cost, and the offcuts stay in stock for
the next job.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from addsol_nl_custom.addsol_nl_custom.plates import cutting
from addsol_nl_custom.addsol_nl_custom.plates.settings import get_setting


class PlateOffcut(Document):
	"""One plate cut into offcuts plus the piece the order keeps."""

	def validate(self):
		self.set_source()
		self.check_project()
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
		self.source_plate_text = details["plate_text"]
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

	def check_project(self):
		"""Every cutting belongs to one order, and says so before anything is cut.

		The field is mandatory on the form, but a document built by an API or
		an import reaches validate without ever passing through the desk, and
		without a Project there is nothing to issue the remainder against -
		the consumed weight would silently become nobody's cost.

		The Project must also belong to the company the plate sits in: the
		remainder is issued against it, and ERPNext refuses a Stock Entry row
		whose accounting dimension carries another company's name
		(accounts_controller.validate_company). Catching it here turns an
		inscrutable failure deep inside on_submit into one clear line on the
		form.
		"""
		if not (self.project or "").strip():
			frappe.throw(
				_("Set the Project this plate is cut for. Whatever is neither an offcut nor "
				  "scrap is issued against it, so a cutting without one has nowhere to put "
				  "its cost."),
				title=_("Project is required"),
			)

		project_company = frappe.get_cached_value("Project", self.project, "company")
		warehouse_company = frappe.db.get_value(
			"Warehouse", self.warehouse, "company", cache=True
		)

		if project_company and warehouse_company and project_company != warehouse_company:
			frappe.throw(
				_("Project {0} belongs to Company {1}, but this plate sits in a warehouse of "
				  "{2}. The piece that is neither offcut nor scrap is issued against the "
				  "Project, so the two must belong to the same company.").format(
					frappe.bold(self.project),
					frappe.bold(project_company),
					frappe.bold(warehouse_company),
				),
				title=_("Project belongs to another company"),
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

		# Scrap is booked by hand - the operator knows what the job leaves
		# behind - and whatever is neither an offcut nor scrap is the piece
		# this order keeps. compute_totals refuses an overage beyond the
		# tolerance and fills in the consumed figures both documents show.
		self.scrap_weight_kg = frappe.utils.flt(self.scrap_weight_kg)

		cutting.compute_totals(self)

		if frappe.utils.flt(self.scrap_weight_kg) > 0 and not get_setting("scrap_item"):
			frappe.throw(
				_(
					"This cutting books {0} kg of scrap, but Plate Settings has no scrap Item set."
				).format(self.scrap_weight_kg),
				title=_("Scrap Item not set"),
			)

		self.remainder_weight_kg = self.consumed_weight_kg
		self.remainder_value = self.consumed_value

	def create_offcut_stock(self):
		"""Create the Item, Batch and reserved Serial No per piece, then repack.

		The Repack's submit creates the reserved serial numbers in stock.
		Allocating the names here keeps this document and the stock movement
		pointing at the same thing. When anything is consumed, the remainder
		piece is made the same way and then issued against the Project.
		"""
		offcut_batch_series = get_setting("offcut_batch_series", "OFB-.YY.-.#####")

		for row in self.offcuts:
			row.offcut_item = cutting.get_or_create_offcut_item(self.source_item, row)
			if not row.batch_no:
				row.batch_no = self.make_piece_batch(
					row.offcut_item, offcut_batch_series, row.weight_kg
				)
			if not row.serial_no:
				row.serial_no = cutting.reserve_serial_no(row.offcut_item)

		if frappe.utils.flt(self.consumed_weight_kg) > 0:
			self.create_remainder_piece(offcut_batch_series)

		self.make_repack()
		self.make_material_issue()

		# db_update ran before on_submit, so anything decided here has to be
		# written explicitly - the Item, Batch and Serial No names above, and
		# the Stock Entries this submit created.
		self.db_update()
		for row in self.offcuts:
			row.db_update()

		self.stamp_piece_serials()

	def create_remainder_piece(self, offcut_batch_series):
		"""The one piece the order keeps: its own Item, batch and serial.

		One Item per piece, never reused: two cuttings for the same order
		leave two different pieces, and a stock register that showed them
		under one name could not say which heat they came from.
		"""
		running_no = cutting.next_remainder_running_no(self.project)
		self.remainder_item = cutting.get_or_create_remainder_item(
			self.source_item, self.project, running_no
		)
		self.remainder_batch_no = self.make_piece_batch(
			self.remainder_item, offcut_batch_series, self.consumed_weight_kg
		)
		self.remainder_serial_no = cutting.reserve_serial_no(self.remainder_item)

	def make_piece_batch(self, item, series, weight_kg):
		"""A Batch for one piece, carrying the plate's own history.

		Grade is read from the Item's group rather than typed: it is the group
		the weight maths uses, and a label that disagrees with it once made
		weights come out of the wrong formula.
		"""
		from frappe.model.naming import make_autoname

		batch = {
			"doctype": "Batch",
			"item": item,
			"custom_heat_number": self.heat_number,
			"custom_mtc_no": getattr(self, "mtc_no", None),
			"custom_grade": frappe.db.get_value("Item", item, "item_group"),
			"custom_weight_per_plate_kg": weight_kg,
			"custom_source_batch": self.source_batch,
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
		stock_entry = self.new_stock_entry("Repack")

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

		if frappe.utils.flt(self.consumed_weight_kg) > 0:
			# Priced at what it is worth, so the Material Issue that follows
			# takes exactly this value out of stock and onto the Project.
			stock_entry.append(
				"items",
				{
					"t_warehouse": self.warehouse,
					"item_code": self.remainder_item,
					"qty": 1,
					"serial_no": self.remainder_serial_no,
					"batch_no": self.remainder_batch_no,
					"use_serial_batch_fields": 1,
					"set_basic_rate_manually": 1,
					"basic_rate": self.remainder_value,
					"basic_amount": self.remainder_value,
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

	def make_material_issue(self):
		"""Issue the remainder against the Project, so its cost lands there.

		The Repack only moves the piece into stock; this is what spends it.
		One row, one serial, the Project carried on the row itself - that is
		what ERPNext writes into the GL entry's project column, and the
		expense account comes from the Item's own defaults, so the order
		carries the plate's cost without this code touching the ledger.
		"""
		if frappe.utils.flt(self.consumed_weight_kg) <= 0:
			return

		stock_entry = self.new_stock_entry("Material Issue")

		stock_entry.append(
			"items",
			{
				"s_warehouse": self.warehouse,
				"item_code": self.remainder_item,
				"qty": 1,
				"serial_no": self.remainder_serial_no,
				"batch_no": self.remainder_batch_no,
				"use_serial_batch_fields": 1,
				"project": self.project,
			},
		)

		stock_entry.insert()
		stock_entry.submit()

		self.material_issue = stock_entry.name

	def new_stock_entry(self, purpose):
		"""A Stock Entry of this kind, in the plate's own company."""
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
		stock_entry.stock_entry_type = purpose
		stock_entry.purpose = purpose
		stock_entry.company = company
		# The Stock Entry is an implementation detail of this document; the
		# permission gate is submitting the Plate Offcut itself.
		stock_entry.flags.ignore_permissions = True

		return stock_entry

	def stamp_piece_serials(self):
		"""Point each new serial back at the plate it was cut from."""
		self.stamp_serial(self.source_serial_no, self.remainder_serial_no, self.consumed_weight_kg)

		for row in self.offcuts:
			self.stamp_serial(self.source_serial_no, row.serial_no, row.weight_kg)

	@staticmethod
	def stamp_serial(source_serial_no, serial_no, weight_kg) -> None:
		if not serial_no:
			return

		frappe.db.set_value(
			"Serial No",
			serial_no,
			{
				"custom_weight_kg": weight_kg,
				"custom_source_serial_no": source_serial_no,
			},
		)

	def remove_offcut_stock(self):
		"""Cancel the Material Issue, then the Repack, then take the names back.

		The Material Issue goes first: while it stands, the remainder serial
		is out of stock and the Repack cannot take it back. ERPNext refuses to
		cancel either once a piece has moved on in a later transaction - which
		is exactly right: the plate cannot reappear while pieces of it already
		sit elsewhere. That throw is left standing; this only cleans up what
		the submit created.
		"""
		self.cancel_stock_entry(self.material_issue)
		self.cancel_stock_entry(self.stock_entry)

		self.delete_piece_batch(self.remainder_batch_no)
		self.clear_piece_names("remainder_serial_no", "remainder_batch_no", "remainder_item")

		for row in self.offcuts:
			self.delete_piece_batch(row.batch_no)
			self.clear_row_names(row)

	def cancel_stock_entry(self, name) -> None:
		if not name or not frappe.db.exists("Stock Entry", name):
			return

		stock_entry = frappe.get_doc("Stock Entry", name)
		if stock_entry.docstatus == 1:
			stock_entry.flags.ignore_permissions = True
			stock_entry.cancel()

	def delete_piece_batch(self, batch_no) -> None:
		if batch_no and frappe.db.exists("Batch", batch_no):
			frappe.delete_doc("Batch", batch_no, force=True, ignore_missing=True)

	def clear_piece_names(self, *fields) -> None:
		"""Blank the names a cancelled attempt reserved.

		A cancelled attempt leaves an inactive Serial No behind, and ERPNext
		is wary of re-inwarding an existing serial. Blank the names so a
		re-submit reserves fresh ones instead.
		"""
		blanked = {field: None for field in fields}
		frappe.db.set_value("Plate Offcut", self.name, blanked)
		for field in fields:
			setattr(self, field, None)

	def clear_row_names(self, row) -> None:
		if not (row.serial_no or row.batch_no):
			return

		frappe.db.set_value("Plate Offcut Item", row.name, {"serial_no": None, "batch_no": None})
		row.serial_no = None
		row.batch_no = None
