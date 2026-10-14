# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import unittest

import frappe

from addsol_nl_custom.addsol_nl_custom.doctype.thickness.thickness import Thickness


class TestThickness(unittest.TestCase):
	"""Part B8 - the label stays for people, thickness_mm is what code reads."""

	def test_thickness_normalization(self):
		"""Test that various input formats are normalized correctly"""

		test_cases = [
			("4", "4 mm"),
			("04", "4 mm"),
			("110", "110 mm"),
			("4 mm", "4 mm"),
			("4mm", "4 mm"),
			("04mm", "4 mm"),
			("4  mm", "4 mm"),
			("4MM", "4 mm"),
			("4.5", "4.5 mm"),
			("4.5mm", "4.5 mm"),
			("110mm", "110 mm"),
			(" 4 ", "4 mm"),
			(" 4 mm ", "4 mm"),
		]

		for input_val, expected_output in test_cases:
			result = Thickness.normalize_thickness(input_val)
			self.assertEqual(
				result,
				expected_output,
				f"Failed for input '{input_val}': expected '{expected_output}', got '{result}'",
			)

	def test_parse_thickness_mm(self):
		"""The numeric value, which the whole app reads instead of the label."""

		test_cases = [
			("4", 4),
			("04", 4),
			("110", 110),
			("4 mm", 4),
			("4mm", 4),
			("2.5", 2.5),
			("2.5 mm", 2.5),
			("0.125", 0.125),
		]

		for input_val, expected in test_cases:
			result = Thickness.parse_thickness_mm(input_val)
			self.assertEqual(
				result,
				expected,
				f"Failed for input '{input_val}': expected {expected}, got {result}",
			)

	def test_split_thickness_returns_both(self):
		self.assertEqual(Thickness.split_thickness("04"), ("4 mm", 4))
		self.assertEqual(Thickness.split_thickness("2.5mm"), ("2.5 mm", 2.5))

	def test_invalid_thickness_input(self):
		"""Test that invalid inputs raise appropriate errors"""

		invalid_inputs = [
			"abc",
			"4x",
			"mm",
			"four",
			"",
		]

		for invalid_input in invalid_inputs:
			with self.assertRaises(Exception):
				Thickness.normalize_thickness(invalid_input)

	def test_validate_keeps_thickness_mm_in_step(self):
		"""Saving a Thickness fills both the label and the number."""

		doc = frappe.get_doc(
			{
				"doctype": "Thickness",
				"thickness_value": "04mm",
				"remark": "test record",
			}
		).insert(ignore_permissions=True)

		self.assertEqual(doc.thickness_value, "4 mm")
		self.assertEqual(doc.thickness_mm, 4)

		frappe.db.set_value("Thickness", doc.name, "thickness_value", "6 mm", update_modified=False)
		reloaded = frappe.get_doc("Thickness", doc.name)
		reloaded.save()
		self.assertEqual(reloaded.thickness_value, "6 mm")
		self.assertEqual(reloaded.thickness_mm, 6)

	def tearDown(self):
		"""Clean up test data"""
		frappe.db.rollback()
