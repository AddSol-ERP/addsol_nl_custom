# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import unittest

import frappe

from addsol_nl_custom.addsol_nl_custom.plates.weight import (
	ALLOWED_VARIABLES,
	compute_theoretical_weight,
	formula_variables,
)


class TestFormulaVariables(unittest.TestCase):
	"""The formula is checked by shape, so a new product can use a new shape."""

	def test_the_four_financial_formulas(self):
		self.assertEqual(
			formula_variables("(L * W * T * MF) / 100000"),
			{"L", "W", "T", "MF"},
		)
		self.assertEqual(formula_variables("(L * W * MF) / 10000"), {"L", "W", "MF"})
		self.assertEqual(formula_variables("(L * T * MF) / 10000"), {"L", "T", "MF"})
		self.assertEqual(formula_variables("(W * T * MF) / 10000"), {"W", "T", "MF"})

	def test_spacing_and_nesting_do_not_matter(self):
		# An exact-string allow-list would have rejected all of these.
		for formula in (
			"L*W*T*MF/100000",
			"L * W * T * MF / 100000",
			"((L * W) * (T * MF)) / 100000",
			"(L * W * T * MF) / 1e5",
		):
			with self.subTest(formula=formula):
				self.assertEqual(formula_variables(formula), {"L", "W", "T", "MF"})

	def test_only_the_allowed_names(self):
		self.assertEqual(
			set(ALLOWED_VARIABLES),
			{"L", "W", "T", "MF"},
		)

	def test_arbitrary_names_are_rejected(self):
		for formula in ("L * W * D * T", "length * width", "L * W * MF / Q", "self.x"):
			with self.subTest(formula=formula):
				with self.assertRaises(frappe.ValidationError):
					formula_variables(formula)

	def test_calls_attributes_and_strings_are_rejected(self):
		# Part F3 T2 - nothing may reach safe_eval carrying code.
		for formula in (
			"__import__('os').system('ls')",
			"open('/etc/passwd')",
			"L.__class__",
			"L * W * (1 if True else 2)",
			"L if __import__('os') else W",
		):
			with self.subTest(formula=formula):
				with self.assertRaises(frappe.ValidationError):
					formula_variables(formula)

	def test_junk_is_rejected(self):
		for formula in (None, "", "L W T", "not a formula at all"):
			with self.subTest(formula=formula):
				with self.assertRaises(frappe.ValidationError):
					formula_variables(formula)

	def test_a_formula_with_no_variables_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			formula_variables("100000")

	def tearDown(self):
		frappe.db.rollback()
