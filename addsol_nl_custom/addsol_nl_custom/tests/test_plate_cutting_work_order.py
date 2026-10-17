# Copyright (c) 2026, Your Company and contributors
# For license information, see license.txt

"""check_in_work_order must find the plate among the Work Order's required items.

The check used to query ``BOM Item`` with ``parent = work_order``. ``BOM Item``
is a child of ``BOM``, so its parent is a BOM name and never a Work Order name:
the lookup could never match, and every cutting record failed with "Serial No
PL-000007 is not a required item of Work Order W-0006-01" even with the plate
allocated in the Work Order's WIP warehouse. The Work Order's own
``required_items`` (the ``Work Order Item`` child table) is the correct source
of truth. The check also read ``self.source_item`` before ``set_source`` had
filled it in, so the item filter matched nothing on a fresh record.

`bench --site <site> run-tests --app addsol_nl_custom`
"""

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from .test_item import hsn_for_tests

COMPANY = "_Test Company"
SOURCE_WAREHOUSE = "Stores - _TC"
WIP_WAREHOUSE = "Work In Progress - _TC"
FG_WAREHOUSE = "Finished Goods - _TC"


def make_item(suffix):
	"""A plain stock Item under All Item Groups.

	These items only exist to be a Work Order's raw material, so they stay out
	of the weighed-grade machinery on purpose.
	"""
	item_code = f"PCR-WO-{suffix}-{uuid.uuid4().hex[:6]}"
	return frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"item_group": "All Item Groups",
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"is_purchase_item": 1,
			"valuation_rate": 100,
			**hsn_for_tests(),
		}
	).insert(ignore_permissions=True).name


def make_project():
	"""A Project, because both BOM.project and Work Order.project are mandatory here."""
	return frappe.get_doc(
		{
			"doctype": "Project",
			"naming_series": "PROJ-.####",
			"project_name": f"PCR Plate Cutting {uuid.uuid4().hex[:6]}",
			"company": COMPANY,
		}
	).insert(ignore_permissions=True).name


def make_bom(production_item, raw_item):
	bom = frappe.get_doc(
		{
			"doctype": "BOM",
			"item": production_item,
			"company": COMPANY,
			"project": make_project(),
			"currency": frappe.db.get_value("Company", COMPANY, "default_currency"),
			"quantity": 1,
			"is_active": 1,
			"items": [
				{
					"item_code": raw_item,
					"qty": 1,
					"uom": "Nos",
					"stock_uom": "Nos",
					"source_warehouse": SOURCE_WAREHOUSE,
					"rate": 100,
				}
			],
		}
	)
	bom.insert(ignore_permissions=True)
	bom.submit()
	return bom


def make_work_order(bom, production_item):
	"""A draft Work Order whose required_items come from the BOM.

	Left as a draft: the plate check reads required_items and wip_warehouse,
	not the Work Order's docstatus, and a draft skips the submit-time bin
	bookings that have nothing to do with this test.
	"""
	project = frappe.db.get_value("BOM", bom.name, "project")
	work_order = frappe.get_doc(
		{
			"doctype": "Work Order",
			"production_item": production_item,
			"company": COMPANY,
			"project": project,
			"bom_no": bom.name,
			"qty": 1,
			"source_warehouse": SOURCE_WAREHOUSE,
			"wip_warehouse": WIP_WAREHOUSE,
			"fg_warehouse": FG_WAREHOUSE,
			"planned_start_date": today(),
		}
	)
	# validate() runs and fills required_items from the BOM.
	work_order.insert(ignore_permissions=True)
	return work_order


def make_serial(item_code, warehouse, weight=100.0):
	"""An Active serial for a plate, sitting in the given warehouse.

	ERPNext refuses to create a Serial No that already carries a warehouse -
	the stock ledger has to set it - so this inserts first, then db_sets the
	warehouse and status to the same end state a submitted receipt leaves
	behind.
	"""
	serial_no = f"PCR-WO-SN-{uuid.uuid4().hex[:8].upper()}"
	frappe.get_doc(
		{
			"doctype": "Serial No",
			"serial_no": serial_no,
			"item_code": item_code,
			"company": COMPANY,
		}
	).insert(ignore_permissions=True)

	frappe.db.set_value(
		"Serial No",
		serial_no,
		{"warehouse": warehouse, "status": "Active", "custom_weight_kg": weight},
	)
	return serial_no


def cutting_record(work_order, source_serial_no, source_item=None):
	"""An unsaved Plate Cutting Record carrying just what the check reads."""
	return frappe.get_doc(
		{
			"doctype": "Plate Cutting Record",
			"work_order": work_order,
			"source_serial_no": source_serial_no,
			"source_item": source_item,
		}
	)


class TestCheckInWorkOrder(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# FrappeTestCase rolls the database back once per class, so the world a
		# test needs is rebuilt here and undone after each test.
		self.addCleanup(frappe.db.rollback)
		self.fg_item = make_item("FG")
		self.plate_item = make_item("PLATE")
		self.other_item = make_item("OTHER")
		self.bom = make_bom(self.fg_item, self.plate_item)
		self.work_order = make_work_order(self.bom, self.fg_item)

	def test_a_plate_the_order_requires_is_accepted(self):
		"""The reported bug: a plate in the WIP warehouse, required by the order."""
		serial = make_serial(self.plate_item, WIP_WAREHOUSE)
		record = cutting_record(self.work_order.name, serial, self.plate_item)

		record.check_in_work_order()  # must not throw

	def test_the_required_item_comes_from_the_orders_required_items_table(self):
		"""The plate must match a Work Order Item row, not a BOM Item row.

		BOM Item's parent is a BOM name, so a check against BOM Item can never
		see a Work Order's demand. This pins the table the check reads.
		"""
		serial = make_serial(self.plate_item, WIP_WAREHOUSE)
		record = cutting_record(self.work_order.name, serial, self.plate_item)

		self.assertTrue(
			frappe.get_all(
				"Work Order Item",
				filters={"parent": self.work_order.name, "item_code": self.plate_item},
				pluck="name",
			),
			"the plate is a required item of this Work Order",
		)
		record.check_in_work_order()

	def test_a_plate_the_order_does_not_require_is_rejected(self):
		serial = make_serial(self.other_item, WIP_WAREHOUSE)
		record = cutting_record(self.work_order.name, serial, self.other_item)

		with self.assertRaises(frappe.ValidationError) as caught:
			record.check_in_work_order()

		self.assertIn("is not a required item of Work Order", str(caught.exception))
		self.assertIn(serial, str(caught.exception))

	def test_a_plate_outside_the_wip_warehouse_is_rejected(self):
		serial = make_serial(self.plate_item, SOURCE_WAREHOUSE)
		record = cutting_record(self.work_order.name, serial, self.plate_item)

		with self.assertRaises(frappe.ValidationError) as caught:
			record.check_in_work_order()

		self.assertIn("not in the Work Order's WIP warehouse", str(caught.exception))

	def test_set_source_fills_the_item_before_the_work_order_check(self):
		"""set_source must not consult the Work Order before source_item is set.

		The check used to run first, on an empty source_item, so the item
		filter matched nothing even once the table was right.
		"""
		serial = make_serial(self.plate_item, WIP_WAREHOUSE)
		record = cutting_record(self.work_order.name, serial)

		self.assertFalse(record.source_item, "the record starts without a source item")

		record.set_source()  # must not throw

		self.assertEqual(record.source_item, self.plate_item)

	def test_no_work_order_means_no_work_order_check(self):
		serial = make_serial(self.other_item, WIP_WAREHOUSE)
		record = cutting_record(None, serial, self.other_item)

		record.check_in_work_order()
