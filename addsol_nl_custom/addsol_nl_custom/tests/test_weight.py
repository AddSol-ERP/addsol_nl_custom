# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.addsol_nl_custom.plates.grouping import is_weighed_group
from addsol_nl_custom.addsol_nl_custom.plates.weight import compute_theoretical_weight

THREE_D_FORMULA = "(L * W * T * MF) / 100000"


def make_plate_group(group_name, mf=None, formula=None, is_group=0, weighed=True):
	"""Create (or reset) a weighed Item Group for a test.

	`weighed` sets the opt-in flag, and that flag is what makes a grade a
	weighed grade at all. Pass False for a grade that is being built up and has
	not opted in yet.
	"""
	if frappe.db.exists("Item Group", group_name):
		frappe.delete_doc("Item Group", group_name, force=True, ignore_missing=True)

	frappe.get_doc(
		{
			"doctype": "Item Group",
			"item_group_name": group_name,
			"parent_item_group": "All Item Groups",
			"is_group": is_group,
			"custom_is_weighed_grade": 1 if weighed else 0,
			"custom_multiplication_factor": mf,
			"custom_formula": formula,
		}
	).insert(ignore_permissions=True)

	return group_name


class TestItemGroup(FrappeTestCase):
	"""Part B6 - a weighed grade has to opt in, and be usable once it has."""

	def setUp(self):
		super().setUp()
		self.group = make_plate_group("MS Plate 250", 0.785, THREE_D_FORMULA)

	def test_a_good_formula_is_accepted(self):
		self.assertTrue(is_weighed_group(self.group))

	def test_a_formula_alone_does_not_make_a_weighed_grade(self):
		# The opt-in is explicit. A group carrying a Formula is still an ordinary
		# group until the flag is ticked, so no rate per kg is demanded of it.
		group = make_plate_group("Formula No Flag", 0.785, THREE_D_FORMULA, weighed=False)
		self.assertFalse(is_weighed_group(group))

	def test_opting_in_without_a_formula_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_plate_group("Flagged No Formula", None, None)

	def test_an_unticked_grade_may_carry_a_half_finished_formula(self):
		# This used to be refused outright. Only a grade that has opted in has to
		# be usable, so a formula can be entered before the flag is ticked.
		group = make_plate_group("Draft Formula", None, THREE_D_FORMULA, weighed=False)
		self.assertFalse(is_weighed_group(group))

	def test_a_group_without_a_formula_is_left_alone(self):
		# Progressive setup: the group can exist before it opts in.
		group = make_plate_group("Plain Group", None, None, weighed=False)
		self.assertFalse(is_weighed_group(group))

	def test_a_formula_with_a_bad_multiplication_factor_is_rejected(self):
		for mf in (None, 0, -1):
			with self.subTest(mf=mf):
				with self.assertRaises(frappe.ValidationError):
					make_plate_group(f"Bad MF {mf}", mf, THREE_D_FORMULA)

	def test_an_unsafe_formula_is_rejected(self):
		# Part F3 T2.
		for formula in ("__import__('os').system('ls')", "L * W * D", "L W T"):
			with self.subTest(formula=formula):
				with self.assertRaises(frappe.ValidationError):
					make_plate_group(f"Bad Formula {abs(hash(formula))}", 0.785, formula)

	def test_is_weighed_group_handles_nonsense(self):
		self.assertFalse(is_weighed_group(None))
		self.assertFalse(is_weighed_group(""))
		self.assertFalse(is_weighed_group("No Such Group At All"))

	def test_multiplication_factor_has_no_silent_default(self):
		# It used to default to 1, which weighs a 10 mm 250 grade plate at
		# 312.5 kg instead of 245.313 kg and matches no steel at all.
		field = frappe.db.get_value("Custom Field", "Item Group-custom_multiplication_factor", "default")
		self.assertIsNone(field)


class TestComputeTheoreticalWeight(FrappeTestCase):
	"""Part B3 and acceptance test T1."""

	def setUp(self):
		super().setUp()
		self.group = make_plate_group("MS Plate 250", 0.785, THREE_D_FORMULA)

	def test_t1_theoretical_weight_of_a_250_plate(self):
		# 2500 x 1250 x 10 x 0.785 / 100000 = 245.3125 kg
		self.assertEqual(compute_theoretical_weight(self.group, 10, 2500, 1250), 245.313)

	def test_every_financial_formula(self):
		cases = {
			THREE_D_FORMULA: 245.313,
			"(L * W * MF) / 10000": 245.313,
			"(L * T * MF) / 10000": 1.963,
			"(W * T * MF) / 10000": 0.981,
		}

		for formula, expected in cases.items():
			group = make_plate_group(f"MF Group {formula}", 0.785, formula)
			with self.subTest(formula=formula):
				self.assertEqual(
					compute_theoretical_weight(group, 10, 2500, 1250),
					expected,
				)

	def test_missing_or_non_positive_multiplication_factor(self):
		for mf in (None, 0, -1):
			# weighed=False so the half-configured group can exist at all; the
			# point of this test is what the weight calculation makes of it.
			group = make_plate_group(f"MF {mf}", mf, THREE_D_FORMULA, weighed=False)
			with self.subTest(mf=mf):
				with self.assertRaises(frappe.ValidationError):
					compute_theoretical_weight(group, 10, 2500, 1250)

	def test_missing_formula(self):
		group = make_plate_group("No Formula Group", 0.785, None, weighed=False)
		with self.assertRaises(frappe.ValidationError):
			compute_theoretical_weight(group, 10, 2500, 1250)

	def test_a_variable_the_formula_needs_cannot_be_zero(self):
		# No silent fallback to length x width x thickness.
		for thickness, length, width in ((10, 0, 1250), (10, 2500, 0), (0, 2500, 1250)):
			with self.subTest(thickness=thickness, length=length, width=width):
				with self.assertRaises(frappe.ValidationError):
					compute_theoretical_weight(self.group, thickness, length, width)

	def test_a_formula_that_does_not_need_a_dimension_still_works_without_it(self):
		# (W * T * MF) / 10000 never mentions L, so a missing length is fine.
		group = make_plate_group("No Length Needed", 0.785, "(W * T * MF) / 10000")
		self.assertEqual(compute_theoretical_weight(group, 10, 0, 1250), 0.981)

	def test_unknown_item_group(self):
		with self.assertRaises(frappe.ValidationError):
			compute_theoretical_weight("No Such Plate Group", 10, 2500, 1250)

		with self.assertRaises(frappe.ValidationError):
			compute_theoretical_weight(None, 10, 2500, 1250)

	def test_result_is_a_float_rounded_to_three_decimals(self):
		weight = compute_theoretical_weight(self.group, 10, 2500, 1250)
		self.assertIsInstance(weight, float)
		self.assertEqual(weight, round(weight, 3))

	def test_weight_is_rounded_before_the_money_is_worked_out(self):
		"""The rounding contract the rest of the spec depends on.

		Part F3 quotes T1 as 245.313 and T4 as a rate of 15,209.41 per plate.
		T4 is only reachable if the weight is rounded to three decimals FIRST
		and the money is then worked out on the rounded number:

		    245.313 -> 10 plates = 2453.13 kg -> x 62 = 152,094.06 -> /10
		    = 15,209.41

		Done on the raw 245.3125 it comes to 15,209.38 instead. Python's
		round() is banker's rounding and would give 245.312 for the weight,
		which breaks T4 as well. Hence round_half_up.
		"""
		from addsol_nl_custom.addsol_nl_custom.plates.utils import round_half_up

		unit_weight = compute_theoretical_weight(self.group, 10, 2500, 1250)
		self.assertEqual(unit_weight, 245.313)

		rate_per_kg = 62
		plates = 10

		est_kg = round_half_up(plates * unit_weight, 3)
		amount = round_half_up(est_kg * rate_per_kg, 2)
		rate_per_plate = round_half_up(amount / plates, 2)

		self.assertEqual(est_kg, 2453.13)
		self.assertEqual(amount, 152094.06)
		self.assertEqual(rate_per_plate, 15209.41)  # the figure quoted in T4
