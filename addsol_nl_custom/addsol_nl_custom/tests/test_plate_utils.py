# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import unittest

import frappe

from addsol_nl_custom.addsol_nl_custom.plates.cutting import plate_text_for
from addsol_nl_custom.addsol_nl_custom.plates.utils import (
	build_plate_description,
	build_plate_item_name,
	fmt_dim,
	round_half_up,
)


class TestPlateUtils(unittest.TestCase):
	"""Item naming and dimension formatting.

	These used to be f-strings built from Float fields, which produced
	"MS Plate 250-10x2500.0x1250.0". See Part B2.
	"""

	def test_fmt_dim_drops_the_trailing_zero(self):
		# The case that made the old names ugly.
		self.assertEqual(fmt_dim(2500.0), "2500")
		self.assertEqual(fmt_dim(1250.0), "1250")
		self.assertEqual(fmt_dim(10.0), "10")

	def test_fmt_dim_keeps_real_decimals(self):
		self.assertEqual(fmt_dim(4), "4")
		self.assertEqual(fmt_dim(2.5), "2.5")
		self.assertEqual(fmt_dim(0.125), "0.125")

	def test_fmt_dim_strips_trailing_zeros(self):
		self.assertEqual(fmt_dim(4.50), "4.5")
		self.assertEqual(fmt_dim("2.500"), "2.5")
		self.assertEqual(fmt_dim("04"), "4")

	def test_fmt_dim_rounds_to_three_decimals(self):
		self.assertEqual(fmt_dim(1.23456), "1.235")
		# Half rounds away from zero, matching the old JavaScript.
		self.assertEqual(fmt_dim(2.0005), "2.001")

	def test_fmt_dim_of_nothing(self):
		self.assertEqual(fmt_dim(None), "")
		self.assertEqual(fmt_dim(""), "")

	def test_fmt_dim_rejects_junk(self):
		for bad in ("abc", "10 x 5", "ten"):
			with self.assertRaises(Exception):
				fmt_dim(bad)

	def test_build_plate_item_name(self):
		# The worked example from the specification, Part F3 T1.
		self.assertEqual(
			build_plate_item_name("MS Plate 250", 10, 2500.0, 1250.0),
			"MS Plate 250-10x2500x1250",
		)

	def test_build_plate_item_name_with_partial_dimensions(self):
		self.assertEqual(build_plate_item_name("MS Plate 250", 10, 2500, None), "MS Plate 250-10x2500")
		self.assertEqual(build_plate_item_name("MS Plate 250", 10, None, 1250), "MS Plate 250-10x1250")
		self.assertEqual(build_plate_item_name("MS Plate 250", 10, None, None), "MS Plate 250-10")

	def test_build_plate_item_name_needs_a_group_and_a_thickness(self):
		with self.assertRaises(Exception):
			build_plate_item_name("", 10, 2500, 1250)
		with self.assertRaises(Exception):
			build_plate_item_name("MS Plate 250", None, None, None)

	def test_build_plate_description(self):
		self.assertEqual(build_plate_description(10, 2500.0, 1250.0), "10 x 2500 x 1250 mm")
		self.assertEqual(build_plate_description(10, None, None), "10 mm")

	def test_round_half_up_matches_javascript(self):
		# Python's round() is banker's rounding and would give 245.312 here.
		self.assertEqual(round_half_up(245.3125, 3), 245.313)
		self.assertEqual(round(245.3125, 3), 245.312)  # the behaviour we are avoiding
		self.assertEqual(round_half_up(78.5, 3), 78.5)
		self.assertEqual(round_half_up(2.5, 0), 3.0)
		self.assertEqual(round_half_up(-2.5, 0), -3.0)

	def tearDown(self):
		frappe.db.rollback()


class TestPlateTextFor(unittest.TestCase):
	"""The plate spelled out under the serial, on the form and in the backfill.

	The same words have to come out of the live reader and out of the patch
	that names cuttings filed before the field existed, or a reopening of an
	old document would disagree with a new one. So the formatting lives in
	one helper both call, and these cases pin it.
	"""

	def test_a_batch_is_named_after_the_item(self):
		self.assertEqual(
			plate_text_for("MS Sheet 350-20-D240", "MS Sheet 350-20-D240", "OFC000008"),
			"MS Sheet 350-20-D240 · Batch OFC000008",
		)

	def test_a_plate_with_no_batch_still_names_its_item(self):
		self.assertEqual(plate_text_for("MS Plate 250", "MS Plate 250", None), "MS Plate 250")

	def test_an_item_with_no_name_falls_back_to_its_code(self):
		# Item.item_name is optional; a blank line would say less than the
		# code it stands for.
		self.assertEqual(plate_text_for(None, "SOME-CODE", "B-1"), "SOME-CODE · Batch B-1")
		self.assertEqual(plate_text_for("", "SOME-CODE", None), "SOME-CODE")

	def tearDown(self):
		frappe.db.rollback()
