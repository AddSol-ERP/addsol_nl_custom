# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""The plate register and the offcut register hold DIFFERENT stock.

`Plate Stock Register` counts whole plates (and the remainder a cutting leaves
behind); `Plate Offcut Register` counts the pieces a cutting produced. Two
reports over two populations, and the invariant that matters is that no piece
of stock sits in both and none is in neither.

These tests pin the split itself. After a cutting:

- the offcut pieces are in the offcut register, and are NOT in the plate
  register -- the plate register used to hold them behind an `include_offcuts`
  checkbox, which meant one report held two populations and every figure had
  to be read with the checkbox in mind;
- an untouched plate is still in the plate register, and is NOT in the offcut
  register;
- the remainder is plate stock, not an offcut.

`bench --site <site> run-tests --app addsol_nl_custom`
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from addsol_nl_custom.addsol_nl_custom.report.plate_offcut_register import (
	execute as offcut_register,
)
from addsol_nl_custom.addsol_nl_custom.report.plate_stock_register import (
	execute as plate_register,
)

from .test_cutting_estimate import (
	GROUP,
	PLATE_WEIGHT,
	make_project,
	make_warehouse,
	offcut_for,
	source_serial,
)
from .test_item import make_group, make_plate_item, make_thickness

# Two offcuts of the SAME size, so they share one offcut Item and land in one
# row of the register with two pieces in it. Two different sizes would make two
# Items and two rows, which is the other case and is covered separately.
ROWS = [
	{"length_mm": 1000, "width_mm": 500},
	{"length_mm": 1000, "width_mm": 500},
]


def rows_of(report):
	"""The data rows of a report's 5-tuple return."""
	return report[1]


class TestPlateOffcutRegister(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# Per-test undo, the way the rest of the suite rebuilds its world.
		self.addCleanup(frappe.db.rollback)
		frappe.db.set_single_value("Plate Settings", "min_offcut_length_mm", 0)
		frappe.db.set_single_value("Plate Settings", "min_offcut_width_mm", 0)
		self.group = make_group(GROUP)
		self.thickness = make_thickness()
		self.item = make_plate_item(group=GROUP, length=2500, width=1250)
		self.warehouse = make_warehouse()
		self.project = make_project()

	def cut(self, rows=ROWS):
		"""Cut one plate, and return the submitted Plate Offcut."""
		serial = source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse)
		document = offcut_for(serial, rows, project=self.project)
		document.insert()
		document.submit()
		return document

	def offcut_row_for(self, report, item_code):
		for row in rows_of(report):
			if row["item"] == item_code:
				return row
		return None

	# ------------------------------------------------------------------ split

	def test_the_pieces_are_in_the_offcut_register_and_not_in_the_plate_register(self):
		document = self.cut()

		offcuts = offcut_register({})
		plates = plate_register({})

		offcut_item = document.offcuts[0].offcut_item
		self.assertIsNotNone(self.offcut_row_for(offcuts, offcut_item))
		self.assertIsNone(self.offcut_row_for(plates, offcut_item))

	def test_an_untouched_plate_is_in_the_plate_register_and_not_in_the_offcut_one(self):
		# A plate that is IN stock and has not been cut. The one the cutting
		# consumes is not: the Repack consumes its serial, so it leaves the
		# register entirely.
		source_serial(self.item, PLATE_WEIGHT, warehouse=self.warehouse)

		offcuts = offcut_register({})
		plates = plate_register({})

		self.assertIsNotNone(self.offcut_row_for(plates, self.item.name))
		self.assertIsNone(self.offcut_row_for(offcuts, self.item.name))

		# The untouched plate is counted as ONE plate of its batch.
		row = self.offcut_row_for(plates, self.item.name)
		self.assertGreaterEqual(row["plates"], 1)

	def test_the_remainder_is_plate_stock_and_not_an_offcut(self):
		document = self.cut()

		remainder = frappe.db.get_value(
			"Item",
			document.remainder_item,
			["custom_is_remainder", "custom_is_offcut"],
			as_dict=True,
		)

		# The remainder is the piece of the plate the order keeps, so it is
		# plate stock. It carries `custom_is_remainder` and NOT
		# `custom_is_offcut`, and that is the flag the plate register filters
		# on -- so a remainder can never be filed as an offcut.
		#
		# It cannot be asserted as a ROW: the cutting issues the remainder
		# against the Project, so its serial is consumed and it is not stock by
		# the time anyone reads a register.
		self.assertEqual(remainder.custom_is_remainder, 1)
		self.assertFalse(remainder.custom_is_offcut)

	# --------------------------------------------------------------- the roll-up

	def test_two_pieces_of_one_size_are_one_row_with_two_in_it(self):
		document = self.cut()

		offcuts = offcut_register({})
		offcut_item = document.offcuts[0].offcut_item

		rows = [row for row in rows_of(offcuts) if row["item"] == offcut_item]
		self.assertEqual(len(rows), 1)

		row = rows[0]
		self.assertEqual(row["pieces"], 2)
		self.assertEqual(row["warehouse"], self.warehouse)

		# The weight and the value are the pieces' own, summed. The value is
		# what the Repack booked, not cost per kg times weight.
		expected_weight = sum(row.weight_kg for row in document.offcuts)
		expected_value = sum(row.value for row in document.offcuts)
		self.assertAlmostEqual(row["total_weight"], expected_weight, places=3)
		self.assertAlmostEqual(row["total_value"], expected_value, places=2)
		self.assertAlmostEqual(row["weight_per_piece"], expected_weight / 2, places=3)

		# The batch is the SOURCE batch -- the plate the pieces were cut from.
		# Each piece has a batch of its own, so grouping by the piece's own
		# batch would give one row per piece and no register at all.
		self.assertEqual(row["batch"], document.source_batch)

	def test_two_cuttings_of_one_size_from_two_plates_are_two_rows(self):
		first = self.cut()
		second = self.cut()

		offcut_item = first.offcuts[0].offcut_item
		self.assertEqual(second.offcuts[0].offcut_item, offcut_item)

		rows = [row for row in rows_of(offcut_register({})) if row["item"] == offcut_item]

		# One row per source batch: the same size, cut from two plates of two
		# heats, is two lines in the register and one line per heat in the
		# summary above them.
		self.assertEqual(len(rows), 2)
		self.assertEqual({row["pieces"] for row in rows}, {1})
		self.assertEqual({row["batch"] for row in rows}, {first.source_batch, second.source_batch})

	def test_the_totals_row_adds_the_pieces(self):
		document = self.cut()

		_columns, _data, _message, totals, _chart = offcut_register({})

		self.assertEqual(totals["pieces"], 2)
		self.assertAlmostEqual(
			totals["total_weight"],
			sum(row.weight_kg for row in document.offcuts),
			places=3,
		)
