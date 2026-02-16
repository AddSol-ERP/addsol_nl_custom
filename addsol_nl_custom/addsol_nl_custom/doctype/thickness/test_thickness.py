# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import unittest
import frappe
from addsol_nl_custom.addsol_nl_custom.doctype.thickness.thickness import Thickness


class TestThickness(unittest.TestCase):
	def test_thickness_normalization(self):
		"""Test that various input formats are normalized correctly"""
		
		test_cases = [
			('4', '4 mm'),
			('04', '4 mm'),
			('110', '110 mm'),
			('4 mm', '4 mm'),
			('4mm', '4 mm'),
			('04mm', '4 mm'),
			('4  mm', '4 mm'),
			('4MM', '4 mm'),
			('4.5', '4.5 mm'),
			('4.5mm', '4.5 mm'),
			('110mm', '110 mm'),
			(' 4 ', '4 mm'),
			(' 4 mm ', '4 mm'),
		]
		
		for input_val, expected_output in test_cases:
			result = Thickness.normalize_thickness(input_val)
			self.assertEqual(
				result, 
				expected_output, 
				f"Failed for input '{input_val}': expected '{expected_output}', got '{result}'"
			)
	
	def test_invalid_thickness_input(self):
		"""Test that invalid inputs raise appropriate errors"""
		
		invalid_inputs = [
			'abc',
			'4x',
			'mm',
			'four',
		]
		
		for invalid_input in invalid_inputs:
			with self.assertRaises(Exception):
				Thickness.normalize_thickness(invalid_input)
	
	def tearDown(self):
		"""Clean up test data"""
		frappe.db.rollback()