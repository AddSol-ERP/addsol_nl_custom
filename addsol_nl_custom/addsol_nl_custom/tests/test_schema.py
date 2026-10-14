# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Invariants over the files this app ships.

Checked against the repository rather than the database, so they fail fast
without needing a site.

Scope note: the fixture also carries a number of pre-existing HR custom fields
that belong to another project and are deliberately left alone. These tests
cover the plate work only, so they do not fail on someone else's fields.
"""

import glob
import json
import os
import unittest

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODULE_DIR = os.path.join(APP_DIR, "addsol_nl_custom")
CUSTOM_FIELD_FIXTURE = os.path.join(APP_DIR, "fixtures", "custom_field.json")

# DocTypes this app builds fields on.
PLATE_DOCTYPES = {
	"Item",
	"Item Group",
	"Supplier",
	"Purchase Order",
	"Purchase Order Item",
	"Purchase Receipt",
	"Purchase Receipt Item",
	"Purchase Invoice",
	"Purchase Invoice Item",
	"Batch",
	"Serial No",
	"Stock Entry Detail",
}


def load(path):
	with open(path) as f:
		return json.load(f)


def plate_custom_fields():
	return [f for f in load(CUSTOM_FIELD_FIXTURE) if f["dt"] in PLATE_DOCTYPES]


class TestSelectDefaults(unittest.TestCase):
	"""Frappe's first-option-as-default trap.

	`frappe/model/create_new.py` does:

	    elif df.fieldtype == "Select" and df.options ...:
	        return df.options.split("\\n", 1)[0]

	So a Select with no explicit default silently takes its first option, and
	that value is applied to every new document. A Select whose first option is
	not blank therefore invents data - which is exactly how every Item Group on
	`qa.nlemech.com` came to look like a weighed grade.
	"""

	def selects(self):
		for path in glob.glob(os.path.join(MODULE_DIR, "doctype", "*", "*.json")):
			doc = load(path)
			for field in doc.get("fields", []):
				if field.get("fieldtype") == "Select" and field.get("options"):
					yield f"{doc['name']}.{field['fieldname']}", field["options"]

		for field in plate_custom_fields():
			if field.get("fieldtype") == "Select" and field.get("options"):
				yield f"{field['dt']}.{field['fieldname']}", field["options"]

	def test_every_select_we_ship_starts_with_a_blank_option(self):
		offenders = []
		for name, options in self.selects():
			first = options.split("\n", 1)[0]
			if first != "":
				offenders.append(f"{name} -> {first!r}")

		self.assertEqual(
			offenders,
			[],
			"These Select fields would default themselves to their first option on every new "
			"document. Prefix their options with a blank line: " + "; ".join(offenders),
		)

	def test_the_weight_formula_in_particular(self):
		field = next(
			f for f in plate_custom_fields() if f["dt"] == "Item Group" and f["fieldname"] == "custom_formula"
		)
		self.assertEqual(
			field["options"].split("\n", 1)[0],
			"",
			"custom_formula must start blank or every Item Group created gets a formula.",
		)

	def test_the_multiplication_factor_has_no_default(self):
		"""It used to default to 1, which weighs steel 27% heavy."""
		field = next(
			f
			for f in plate_custom_fields()
			if f["dt"] == "Item Group" and f["fieldname"] == "custom_multiplication_factor"
		)
		self.assertIsNone(field.get("default"))


class TestCustomFieldFixture(unittest.TestCase):
	def test_every_plate_field_is_generated_or_hand_tuned(self):
		"""Anything on a plate DocType has a home, so a generator re-run cannot drop it."""
		import importlib.util

		spec = importlib.util.spec_from_file_location(
			"gen", os.path.join(os.path.dirname(APP_DIR), "tools", "generate_plate_custom_fields.py")
		)
		generator = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(generator)

		managed = {(dt, fn) for dt, fn, *_ in generator.FIELD_SPECS}
		hand_tuned = {
			("Item", "custom_thickness_dropdown"),
			("Item", "custom_length_mm"),
			("Item", "custom_width_mm"),
			("Item", "custom_estimated_weight"),
			("Item Group", "custom_formula"),
			("Item Group", "custom_multiplication_factor"),
			("Item Group", "custom_batch_number_series"),
			("Item Group", "custom_serial_no_series"),
		}

		orphans = [
			f"{f['dt']}.{f['fieldname']}"
			for f in plate_custom_fields()
			if (f["dt"], f["fieldname"]) not in managed | hand_tuned
		]
		self.assertEqual(
			orphans,
			[],
			"These plate fields are neither generated nor hand-tuned, so re-running the "
			"generator would delete them: " + ", ".join(orphans),
		)

	def test_no_custom_field_carries_a_link_filter(self):
		"""tabDocField has a CHECK constraint that rejected ours during migrate."""
		for field in load(CUSTOM_FIELD_FIXTURE):
			self.assertIn(field.get("link_filters"), (None, "", []))
