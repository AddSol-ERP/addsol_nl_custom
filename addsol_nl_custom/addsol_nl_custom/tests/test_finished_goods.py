# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""A finished good is named from its Project, and sold against it.

The problem this answers: a Sales Order is raised against a Project, and the
finished good on it could be given any code at all - FG-001, PRODUCTION-01,
whatever the person typing had in mind. The codes drifted, and nothing could
be read off them.

So the code of a finished good is built from its Project, and it counts per
Project: W-0268-00001, W-0268-00002, and another project starts again at
00001. The server owns that rule. The client only locks the code field and
fills the row's Project, so the user is not invited to type a code that is
going to be replaced.

`bench --site <site> run-tests --app addsol_nl_custom`
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.addsol_nl_custom.finished_goods import groups
from addsol_nl_custom.addsol_nl_custom.finished_goods.item_hooks import item_after_insert
from addsol_nl_custom.addsol_nl_custom.finished_goods.sales_order import sales_order_validate

from .test_item import hsn_for_tests

GROUP = "Finished Goods"
CHILD_GROUP = "Finished Goods - Test Child"
COMPANY = "_Test Company"


def make_finished_good_groups():
	"""The group that holds finished goods, and a group under it.

	The rule is "the group named Finished Goods, or any group under it", so
	both halves have to exist to be tested. The customer may already have a
	group of that name - it is left exactly as it is.
	"""
	if not frappe.db.exists("Item Group", GROUP):
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": GROUP,
				"parent_item_group": "All Item Groups",
				"is_group": 1,
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Item Group", CHILD_GROUP):
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": CHILD_GROUP,
				"parent_item_group": GROUP,
				"is_group": 0,
			}
		).insert(ignore_permissions=True)

	return GROUP, CHILD_GROUP


def make_project(name="FG Test Project"):
	"""A Project for a finished good to be made for.

	The Project names itself from the site's naming series, so its name is
	whatever that series says - the code is built from it, so the test reads
	the name back rather than assuming one.

	The per-project counter is a row in tabSeries, and that survives the
	suite's rollback while the Project's own numbering does not, so a Project
	reused across tests would start at a number an earlier test left behind.
	Wiping the counter makes the first code 00001.
	"""
	existing = frappe.db.get_value("Project", {"project_name": name}, "name")
	if existing:
		project = existing
	else:
		project = (
			frappe.get_doc(
				{
					"doctype": "Project",
					"project_name": name,
					"company": COMPANY,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	frappe.db.delete("Series", {"name": ("like", f"%{project}%")})

	return project


def make_finished_good(group, project, item_code="TYPED-CODE", item_name="Test Finished Good"):
	"""A finished good, with the code the user typed and the Project it is for."""
	return frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_name,
			"item_group": group,
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"custom_project": project,
			**hsn_for_tests(),
		}
	).insert(ignore_permissions=True)


def so_row(item_code, idx=1, project=None):
	"""A Sales Order Item row, in memory.

	The rule is exercised on a document built here rather than on a real
	Sales Order: an ERPNext order needs a customer, a price list and a tax
	template before it will save, and none of that is what is being tested
	here.
	"""
	return frappe._dict(
		{
			"idx": idx,
			"item_code": item_code,
			"project": project,
		}
	)


def so_doc(rows, project=None):
	return frappe._dict(
		{
			"doctype": "Sales Order",
			"name": "SO-FG-TEST",
			"project": project,
			"items": rows,
		}
	)


def take_messages() -> list[str]:
	"""The messages Frappe has logged, and the log cleared.

	Read out of the log rather than by patching `frappe.msgprint`: a throw
	raises through msgprint, so a patch would swallow the throw as well and
	the test would pass on a save that had actually failed.
	"""
	log = frappe.local.message_log or []
	messages = [str(entry.get("message")) for entry in log]
	frappe.local.message_log = []

	return messages


class FinishedGoodsTestBase(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# FrappeTestCase rolls the database back once per class, not once per
		# test, so anything an earlier test in this class created would still
		# be here. The helpers below rebuild the world this test needs.
		self.addCleanup(frappe.db.rollback)
		self.group, self.child_group = make_finished_good_groups()
		self.project = make_project()


class TestFinishedGoodCode(FinishedGoodsTestBase):
	def test_the_code_is_built_from_the_project(self):
		item = make_finished_good(self.group, self.project)

		self.assertEqual(item.name, f"{self.project}-00001")
		self.assertEqual(item.item_code, item.name)

	def test_the_number_counts_within_the_project(self):
		first = make_finished_good(self.group, self.project, item_code="FIRST")
		second = make_finished_good(self.group, self.project, item_code="SECOND")

		self.assertEqual(first.name, f"{self.project}-00001")
		self.assertEqual(second.name, f"{self.project}-00002")

	def test_another_project_starts_again(self):
		other = make_project("FG Test Project Two")

		first = make_finished_good(self.group, self.project, item_code="FIRST")
		second = make_finished_good(self.group, other, item_code="SECOND")

		self.assertEqual(first.name, f"{self.project}-00001")
		self.assertEqual(second.name, f"{other}-00001")

	def test_a_group_under_finished_goods_counts(self):
		item = make_finished_good(self.child_group, self.project)

		self.assertEqual(item.name, f"{self.project}-00001")

	def test_a_typed_code_is_replaced_and_kept_as_the_name(self):
		item = make_finished_good(self.group, self.project, item_code="FG-001", item_name="")

		self.assertEqual(item.name, f"{self.project}-00001")
		# What the user typed is not thrown away: it becomes the name.
		self.assertEqual(item.item_name, "FG-001")

	def test_a_finished_good_with_no_project_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_finished_good(self.group, "", item_code="NO-PROJECT")

	def test_an_item_outside_the_group_keeps_its_typed_code(self):
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "PLAIN-FG-TEST",
				"item_name": "Plain Item",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 1,
				**hsn_for_tests(),
			}
		).insert(ignore_permissions=True)

		self.assertEqual(item.name, "PLAIN-FG-TEST")

	def test_the_code_never_moves(self):
		item = make_finished_good(self.group, self.project)
		other = make_project("FG Test Project Two")

		take_messages()

		reloaded = frappe.get_doc("Item", item.name)
		reloaded.custom_project = other
		reloaded.save()

		# The name is the primary key of everything that points at this Item:
		# the stock, the bills of materials, the documents that quote it. It
		# does not move.
		self.assertEqual(reloaded.name, item.name)
		self.assertEqual(
			frappe.db.get_value("Item", item.name, "name"),
			item.name,
		)
		# And the mismatch is said out loud rather than left to be found.
		messages = take_messages()
		self.assertTrue(
			any(other in message for message in messages),
			f"the changed Project was not reported: {messages}",
		)


class TestFinishedGoodGroups(FinishedGoodsTestBase):
	def test_the_group_and_its_children_are_finished_goods(self):
		known = groups.finished_good_groups()

		self.assertIn(GROUP, known)
		self.assertIn(CHILD_GROUP, known)

	def test_an_unrelated_group_is_not(self):
		known = groups.finished_good_groups()

		self.assertNotIn("All Item Groups", known)


class TestSalesOrderRule(FinishedGoodsTestBase):
	def test_a_finished_good_may_be_booked_against_its_project(self):
		item = make_finished_good(self.group, self.project)

		# No exception: the order and the item are for the same Project.
		sales_order_validate(so_doc([so_row(item.name)], project=self.project), None)

	def test_a_finished_good_is_refused_against_another_project(self):
		item = make_finished_good(self.group, self.project)
		other = make_project("FG Test Project Two")

		with self.assertRaises(frappe.ValidationError):
			sales_order_validate(so_doc([so_row(item.name)], project=other), None)

	def test_a_finished_good_is_refused_when_the_order_has_no_project(self):
		item = make_finished_good(self.group, self.project)

		with self.assertRaises(frappe.ValidationError):
			sales_order_validate(so_doc([so_row(item.name)]), None)

	def test_the_row_project_is_used_when_the_order_has_none(self):
		item = make_finished_good(self.group, self.project)

		sales_order_validate(so_doc([so_row(item.name, project=self.project)]), None)

	def test_a_legacy_finished_good_is_left_alone(self):
		# A finished good made before the rule carries no Project, so there is
		# nothing to match it against and it keeps working.
		item = make_finished_good(self.group, self.project)
		frappe.db.set_value("Item", item.name, "custom_project", None)

		sales_order_validate(so_doc([so_row(item.name)]), None)

	def test_an_item_outside_the_group_is_not_held_to_the_project(self):
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "PLAIN-SO-TEST",
				"item_name": "Plain Item",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 1,
				**hsn_for_tests(),
			}
		).insert(ignore_permissions=True)

		sales_order_validate(so_doc([so_row(item.name)]), None)


class TestForeignRename(FinishedGoodsTestBase):
	def test_a_code_another_app_replaced_is_reported(self):
		# Any app that renames Items on save reaches the same Items this rule
		# names, and the one that runs last decides the name. The Item is
		# stored by then, so nothing is changed - but it is said out loud.
		doc = frappe._dict({"doctype": "Item", "name": "W-0268-00007"})
		doc.flags["finished_good_code"] = "W-0268-00001"

		take_messages()
		item_after_insert(doc, None)

		messages = take_messages()
		self.assertTrue(
			any("W-0268-00007" in message and "W-0268-00001" in message for message in messages),
			f"the replaced code was not reported: {messages}",
		)

	def test_our_own_code_is_not_reported(self):
		doc = frappe._dict({"doctype": "Item", "name": "W-0268-00001"})
		doc.flags["finished_good_code"] = "W-0268-00001"

		take_messages()
		item_after_insert(doc, None)

		self.assertEqual(take_messages(), [])
