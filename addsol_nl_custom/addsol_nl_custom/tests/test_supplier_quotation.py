# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""A plate Supplier Quotation accepts a rate per kg and passes it to the order.

The supplier can enter a per-kg rate directly or enter a per-plate rate and
let the hook derive the equivalent. The order inherits the resulting rate,
because ERPNext's mapper copies a field of the same name between documents.

`bench --site <site> run-tests --app addsol_nl_custom`
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.addsol_nl_custom.plates.purchase import sq_before_validate

from .test_cutting_estimate import COMPANY, make_warehouse
from .test_item import hsn_for_tests, make_group, make_plate_item, make_thickness
from .test_rate_history import without_material_request_rule

GROUP = "SQ Plate Test Group"
THICKNESS = "10 mm"
SUPPLIER = "SQ-TEST-SUPPLIER"
WAREHOUSE = "SQ Test Store"

# A 10 x 2500 x 1250 plate at 0.785 weighs 245.313 kg.
UNIT_WEIGHT = 245.313
QUOTED_RATE = 48000.0

# 48,000 a plate is 195.6684 a kg, and ten plates weigh 2,453.13 kg.
RATE_PER_KG = 195.6684
EST_WEIGHT = 2453.13


def make_supplier(name=SUPPLIER):
	if frappe.db.exists("Supplier", name):
		frappe.delete_doc("Supplier", name, force=True, ignore_missing=True)

	return frappe.get_doc({"doctype": "Supplier", "supplier_name": name}).insert(ignore_permissions=True)


def make_quotation(item, qty=10, rate=QUOTED_RATE, uom="Nos", warehouse=None):
	"""A Supplier Quotation with one plate line, in memory.

	Not inserted: most of these tests are about the figures the hook works
	out, and the document machinery would only get in the way of reading them.
	"""
	return frappe.get_doc(
		{
			"doctype": "Supplier Quotation",
			"supplier": SUPPLIER,
			"company": COMPANY,
			"transaction_date": frappe.utils.nowdate(),
			"currency": frappe.db.get_value("Company", COMPANY, "default_currency"),
			"conversion_rate": 1,
			"items": [
				{
					"item_code": item,
					"qty": qty,
					"uom": uom,
					"stock_uom": "Nos",
					"conversion_factor": 1,
					"rate": rate,
					"warehouse": warehouse or make_warehouse(WAREHOUSE),
				}
			],
		}
	)


class SupplierQuotationTestBase(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# FrappeTestCase rolls the database back once per class, not once per
		# test, so anything an earlier test in this class created would still
		# be there. The helpers below rebuild the world this test needs.
		self.addCleanup(frappe.db.rollback)
		# The plate purchasing rules stand down while this is off, and the
		# site's own choice is not the suite's to make. The per-test rollback
		# undoes the write.
		frappe.db.set_single_value("Plate Settings", "enable_weight_based_purchasing", 1)

		self.group = make_group(GROUP)
		make_thickness(THICKNESS)
		self.item = make_plate_item(group=GROUP).name
		make_supplier()
		self.warehouse = make_warehouse(WAREHOUSE)


class TestQuotationPricing(SupplierQuotationTestBase):
	def test_the_rate_per_kg_is_worked_out_from_the_quoted_rate(self):
		doc = make_quotation(self.item)
		row = doc.items[0]

		sq_before_validate(doc, None)

		self.assertEqual(row.custom_is_plate, 1)
		self.assertEqual(row.custom_unit_weight_kg, UNIT_WEIGHT)
		self.assertEqual(row.custom_est_weight_kg, EST_WEIGHT)
		# 48,000 a plate is 195.6684 a kg.
		self.assertEqual(row.custom_rate_per_kg, RATE_PER_KG)

	def test_the_line_is_priced_by_weight(self):
		doc = make_quotation(self.item)
		row = doc.items[0]

		sq_before_validate(doc, None)

		# The amount is ERPNext's own - it follows the rate, and the totals are
		# calculated after this hook has run. What this hook decides is the
		# rate: 2,453.13 kg at 195.6684 a kg is 480,000.02, which over ten
		# plates is 48,000.002 a plate.
		self.assertEqual(row.rate, 48000.002)
		self.assertEqual(row.price_list_rate, 48000.002)

	def test_the_total_weight_is_on_the_quotation(self):
		doc = make_quotation(self.item)

		sq_before_validate(doc, None)

		self.assertEqual(doc.custom_total_est_weight_kg, EST_WEIGHT)

	def test_saving_twice_moves_nothing(self):
		# The rate per kg is worked out from the quoted rate, and the quoted
		# rate is then worked out from the rate per kg. That has to be a fixed
		# point, or every save of a quotation would walk its total.
		doc = make_quotation(self.item)
		row = doc.items[0]

		sq_before_validate(doc, None)
		first_rate = row.rate
		first_per_kg = row.custom_rate_per_kg

		sq_before_validate(doc, None)

		self.assertEqual(row.rate, first_rate)
		self.assertEqual(row.custom_rate_per_kg, first_per_kg)

	def test_a_quotation_with_no_price_is_allowed(self):
		# A quote is often raised before the supplier has answered, so a line
		# with no price is left alone rather than refused. The Purchase Order
		# is where the price is demanded.
		doc = make_quotation(self.item, rate=0)
		row = doc.items[0]

		sq_before_validate(doc, None)

		self.assertEqual(row.custom_rate_per_kg, None)
		self.assertEqual(row.custom_est_weight_kg, EST_WEIGHT)

	def test_a_plate_line_in_kg_is_refused(self):
		# The same rule as the Purchase Order: plate stock is counted in Nos,
		# so a quotation that cannot become an order is refused here too.
		doc = make_quotation(self.item, uom="Kg")

		with self.assertRaises(frappe.ValidationError):
			sq_before_validate(doc, None)

	def test_a_line_that_is_not_a_plate_is_left_alone(self):
		plain = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "SQ-PLAIN-ITEM",
				"item_name": "Plain Item",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 1,
				**hsn_for_tests(),
			}
		).insert(ignore_permissions=True)

		doc = make_quotation(self.item)
		row = doc.items[0]
		row.item_code = plain.name

		sq_before_validate(doc, None)

		self.assertEqual(row.custom_is_plate, 0)
		self.assertEqual(row.custom_rate_per_kg, None)


class TestTheOrderInheritsThePrice(SupplierQuotationTestBase):
	def test_the_rate_per_kg_reaches_the_purchase_order(self):
		# The whole point of the quotation carrying the figure: ERPNext's
		# mapper copies a field of the same name from one document to the
		# other, so the order arrives with the price already on it.
		quotation = make_quotation(self.item)
		quotation.insert(ignore_permissions=True)
		quotation.submit()

		from erpnext.buying.doctype.supplier_quotation.supplier_quotation import make_purchase_order

		with without_material_request_rule():
			order = make_purchase_order(quotation.name)

		row = order.items[0]
		self.assertEqual(row.item_code, self.item)
		self.assertEqual(row.custom_rate_per_kg, RATE_PER_KG)
		self.assertEqual(row.supplier_quotation_item, quotation.items[0].name)
