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


def fixture_doctypes_from_hooks():
	"""The doctypes listed in hooks.py's `fixtures`, read properly.

	The list mixes bare strings and {"dt": ..., "filters": [...]} dicts, so a
	line-based parse gets it wrong.
	"""
	import ast

	with open(os.path.join(APP_DIR, "hooks.py")) as f:
		tree = ast.parse(f.read())

	for node in tree.body:
		if not isinstance(node, ast.Assign):
			continue
		if not any(getattr(t, "id", None) == "fixtures" for t in node.targets):
			continue
		doctypes = []
		for entry in node.value.elts:
			if isinstance(entry, ast.Constant):
				doctypes.append(entry.value)
			elif isinstance(entry, ast.Dict):
				for k, v in zip(entry.keys, entry.values, strict=True):
					if getattr(k, "value", None) in ("dt", "doctype"):
						doctypes.append(v.value)
		return doctypes
	return []


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


class TestFixtures(unittest.TestCase):
	"""What `sync_fixtures` needs from every record in a fixture file."""

	def test_every_record_has_a_name(self):
		"""import_file_by_path does doc["name"] with no fallback.

		A record without one stops the whole migration with KeyError: 'name',
		which is how the hand-written Custom DocPerm did it.
		"""
		for path in glob.glob(os.path.join(APP_DIR, "fixtures", "*.json")):
			for record in load(path):
				self.assertIn(
					"name",
					record,
					f"{os.path.basename(path)} has a record with no name: {record.get('doctype')!r}",
				)
				self.assertTrue(record["name"], f"{os.path.basename(path)} has an empty name")

	def test_our_customisation_records_are_named_the_way_frappe_names_them(self):
		"""These must match on import, or the change never lands.

		Only Custom Field and Property Setter follow <DocType>-<id>. Role, Client
		Script, Print Format, Notification, Server Script, Report, Workflow and
		Role Profile are all named by their own document name.

		Scoped to the plate DocTypes. The fixture also carries pre-existing HR
		customisations that are not this app's to rename - Employee.custom_aadhar_card
		among them, whose name has a transposed letter - and it imports stably
		by name, so it is left as it is.
		"""
		for path in glob.glob(os.path.join(APP_DIR, "fixtures", "*.json")):
			for record in load(path):
				if record["doctype"] == "Custom Field" and record["dt"] in PLATE_DOCTYPES:
					self.assertEqual(record["name"], f"{record['dt']}-{record['fieldname']}")

				elif record["doctype"] == "Property Setter" and record["doc_type"] in PLATE_DOCTYPES:
					self.assertEqual(
						record["name"],
						f"{record['doc_type']}-{record.get('field_name') or 'main'}-{record['property']}",
					)

				elif record["doctype"] == "Property Setter":
					expected = (
						f"{record['doc_type']}-{record.get('field_name') or 'main'}-{record['property']}"
					)
					self.assertEqual(record["name"], expected)

	def test_every_fixture_file_is_covered_by_a_hooks_filter(self):
		"""Every file on disk must be one the export filters would produce.

		sync_fixtures imports every .json in the folder regardless of hooks.py;
		the filters only decide what export writes. A file with no filter entry
		is exported wholesale next time, and a filter with no file imports
		nothing.
		"""
		filtered = fixture_doctypes_from_hooks()
		on_disk = {
			os.path.splitext(name)[0]
			for name in os.listdir(os.path.join(APP_DIR, "fixtures"))
			if name.endswith(".json")
		}
		scrubbed = {d.replace(" ", "_").replace("-", "_").lower() for d in filtered}

		self.assertEqual(
			on_disk - scrubbed,
			set(),
			"These fixture files have no hooks.py entry, so nothing keeps them filtered",
		)
		self.assertEqual(
			scrubbed - on_disk,
			set(),
			"These hooks.py filters have no fixture file, so they import nothing",
		)

	def test_every_plate_field_says_where_it_goes(self):
		"""insert_after is what positions a custom field on the form.

		Frappe's Meta.sort_fields honours each field's insert_after outside the
		field_order property-setter branch, so this alone is enough. A DocType
		field_order setter would take priority over it and freeze the layout, so
		there is deliberately none.
		"""
		missing = [f"{f['dt']}.{f['fieldname']}" for f in plate_custom_fields() if not f.get("insert_after")]
		self.assertEqual(
			missing,
			[],
			"Without insert_after these fields land at the top of the form: " + ", ".join(missing),
		)

	def test_we_add_no_field_order_setter(self):
		"""A DocType field_order setter beats insert_after, so we add none.

		The site already carries four - Item, Item Group, Batch and Purchase
		Receipt Item - from the customer's own work on their forms. Those are
		theirs and stay. This app only ever adds precision setters, because
		insert_after is enough to place a custom field and a frozen order would
		override it.
		"""
		import importlib.util

		spec = importlib.util.spec_from_file_location(
			"ps", os.path.join(os.path.dirname(APP_DIR), "tools", "generate_plate_property_setters.py")
		)
		generator = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(generator)

		self.assertEqual(
			generator.PRECISION_6_FIELDS,
			["rate", "base_rate", "net_rate", "base_net_rate", "price_list_rate"],
		)

		runtime = os.path.join(APP_DIR, "fixtures", "property_setter.json")
		before = len(load(runtime))

		generator.main()
		self.assertEqual(
			len(load(runtime)),
			before,
			"re-running the property setter generator changed the file; it must be idempotent",
		)

		for record in load(runtime):
			if record["property"] == "field_order":
				self.assertIn(
					record["doc_type"],
					{"Item", "Item Group", "Batch", "Purchase Receipt Item"},
					f"{record['doc_type']} has a field_order setter this app must not create",
				)
