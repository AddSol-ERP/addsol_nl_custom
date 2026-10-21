# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Invariants over the files this app ships.

Checked against the repository rather than the database, so they fail fast
without needing a site.

Scope note: the fixture also carries a number of pre-existing HR custom fields
that belong to another project. The plate work is what this app is about, but
the fixture-wide rules - every record has a name, every Custom Field is named
the way Frappe names it - apply to those too, because a name that does not
match is what lets two apps ship the same field and collide on import.
"""

import glob
import json
import os
import unittest

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODULE_DIR = os.path.join(APP_DIR, "addsol_nl_custom")
CUSTOM_FIELD_FIXTURE = os.path.join(APP_DIR, "fixtures", "custom_field.json")
PRINT_FORMAT_FIXTURE = os.path.join(APP_DIR, "fixtures", "print_format.json")

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


def items_table_columns(layout) -> list:
	"""The columns of the items table in a Print Format Builder layout.

	The layout is a JSON document of sections, each with columns of fields,
	and the items table carrying its own `table_columns`. The walk is the same
	one the layout patch uses to find the table.
	"""

	def visit(node):
		if isinstance(node, dict):
			if node.get("fieldname") == "items":
				return node.get("table_columns", [])
			for value in node.values():
				found = visit(value)
				if found is not None:
					return found
		elif isinstance(node, list):
			for value in node:
				found = visit(value)
				if found is not None:
					return found
		return None

	return visit(layout) or []


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
		# Frappe checks a Select value against its options before the weight
		# engine ever sees it, so every financial formula the engine supports
		# has to be in the dropdown - the four cases tests/test_weight.py
		# computes.
		self.assertEqual(
			field["options"].split("\n")[1:],
			[
				"(L * W * T * MF) / 100000",
				"(L * W * MF) / 10000",
				"(L * T * MF) / 10000",
				"(W * T * MF) / 10000",
			],
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
	def test_every_field_the_generator_declares_is_shipped(self):
		"""The other way round: what the generator declares has to be in the file.

		The export can empty this file - it writes whatever the site matched,
		and a site whose fixture import failed matches nothing. An empty file
		means a fresh install gets no plate customisation at all, and nothing
		else here says so: the file is simply empty, and the sweep below has
		nothing to complain about.
		"""
		import importlib.util

		spec = importlib.util.spec_from_file_location(
			"gen", os.path.join(os.path.dirname(APP_DIR), "tools", "generate_plate_custom_fields.py")
		)
		generator = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(generator)

		declared = {(dt, fn) for dt, fn, *_ in generator.FIELD_SPECS}
		shipped = {(f["dt"], f["fieldname"]) for f in load(CUSTOM_FIELD_FIXTURE)}

		missing = sorted(f"{dt}.{fn}" for dt, fn in declared - shipped)
		self.assertEqual(
			missing,
			[],
			"the fixture ships no field the generator declares: " + ", ".join(missing),
		)

	def test_the_fixture_is_not_empty(self):
		self.assertTrue(
			load(CUSTOM_FIELD_FIXTURE),
			"the custom field fixture is empty, so the app would ship no custom fields at all",
		)

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
			# The attached-documents panel is a generic transaction-form feature,
			# not plate logic: document_attachments.js mounts it on Purchase
			# Receipt, Quality Inspection and Stock Entry alike, and only the
			# first is a plate DocType. The plate generator has no business
			# owning a field that is mostly about DocTypes it does not cover, so
			# it stays hand-written - which is safe because main() keeps any
			# record FIELD_SPECS does not claim.
			("Purchase Receipt", "custom_document_attachments"),
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

		The Custom Field check covers every record, not just the plate DocTypes.
		The fixture used to carry a stale copy of Employee.custom_aadhar_card
		under a name with a transposed letter. That imported cleanly only while
		no other record held the same fieldname: addsol_devoltrans_custom ships
		the same field under Frappe's own name, so on a site with both apps the
		second import died with "A field with the name custom_aadhar_card already
		exists". A name that is not <DocType>-<fieldname> is never this app's
		record to keep.
		"""
		for path in glob.glob(os.path.join(APP_DIR, "fixtures", "*.json")):
			for record in load(path):
				if record["doctype"] == "Custom Field":
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


class TestPrintFormats(unittest.TestCase):
	"""The plate figures have to be on the printout, or the price cannot be checked.

	The amount of a plate line is the weight times the rate per kg, so a
	Purchase Order that prints the amount without either of them cannot be
	checked against the invoice - and the invoice is priced on the accepted
	weight, which is not the same figure.

	Two Purchase Order formats are shipped, and they are built in two
	different shapes: MPO Format is a Print Format Builder layout and
	Purchase order is a Jinja one. The figures are found in two different
	places, but they have to be there in both.
	"""

	def print_format(self, name):
		for record in load(PRINT_FORMAT_FIXTURE):
			if record["name"] == name:
				return record

		self.fail(f"the fixture ships no print format named {name}")

	def test_the_builder_layout_carries_the_plate_columns(self):
		layout = json.loads(self.print_format("MPO Format")["format_data"])
		columns = {column.get("fieldname") for column in items_table_columns(layout)}

		self.assertIn("custom_rate_per_kg", columns)
		self.assertIn("custom_est_weight_kg", columns)

	def test_the_jinja_format_carries_the_plate_figures(self):
		html = self.print_format("Purchase order")["html"]

		self.assertIn("row.custom_rate_per_kg", html)
		self.assertIn("row.custom_est_weight_kg", html)

	def test_the_jinja_format_prints_the_line_weight_not_the_plate_weight(self):
		# The per-plate weight beside the line's quantity reads as the line's
		# weight, and it is not: ten plates weigh ten times as much.
		html = self.print_format("Purchase order")["html"]

		self.assertIn("row.custom_est_weight_kg", html)
		self.assertNotIn("custom_estimated_weight", html)

	def test_the_jinja_format_guards_the_address_lookup(self):
		# A Purchase Order with no supplier address used to fail the whole
		# print with "Address not found".
		html = self.print_format("Purchase order")["html"]

		self.assertIn("{% if doc.supplier_address %}", html)


class TestFrappeApiUsage(unittest.TestCase):
	"""Arguments that only exist on get_all / the query builder.

	frappe.db.sql takes (query, values, ...) and nothing else useful. Passing
	it limit_page_length or pluck raises TypeError at runtime, which is how the
	Plate Stock Register died the first time it was opened.
	"""

	QUERY_BUILDER_ONLY = frozenset(
		{
			"limit_page_length",
			"pluck",
			"cache",
			"update",
			"ignore_ifnull",
			"order_by",
			"fields",
			"filters",
			"group_by",
		}
	)

	def app_python_files(self):
		for path in glob.glob(os.path.join(MODULE_DIR, "**", "*.py"), recursive=True):
			if "__pycache__" in path:
				continue
			yield path
		for path in glob.glob(os.path.join(APP_DIR, "patches", "**", "*.py"), recursive=True):
			if "__pycache__" in path:
				continue
			yield path

	def test_no_query_builder_arguments_reach_frappe_db_sql(self):
		import ast

		offenders = []
		for path in self.app_python_files():
			tree = ast.parse(open(path).read())
			for node in ast.walk(tree):
				if not isinstance(node, ast.Call):
					continue
				func = node.func
				if not (isinstance(func, ast.Attribute) and func.attr == "sql"):
					continue
				source = ast.unparse(func)
				if "db.sql" not in source and not source.endswith(".sql"):
					continue
				bad = {k.arg for k in node.keywords if k.arg} & self.QUERY_BUILDER_ONLY
				if bad:
					offenders.append(f"{os.path.relpath(path, APP_DIR)}:{node.lineno} {sorted(bad)}")

		self.assertEqual(offenders, [], "frappe.db.sql got query-builder arguments: " + "; ".join(offenders))


class TestStockFieldNames(unittest.TestCase):
	"""Column names on the stock tables, which are not all what you would guess.

	Serial No links to Item through `item_code`. Batch links through `item`.
	They read alike and are not interchangeable, and a wrong one only fails when
	the code runs - which is how Plate Stock Register died with
	"Unknown column 's.item' in 'SELECT'".
	"""

	# From erpnext/stock/doctype/serial_no/serial_no.json at version-15.
	SERIAL_NO_FIELDS = frozenset(
		{
			"name",
			"status",
			"owner",
			"creation",
			"modified",
			"docstatus",
			"serial_no",
			"item_code",
			"item_name",
			"item_group",
			"brand",
			"asset",
			"location",
			"employee",
			"warranty_expiry_date",
			"amc_expiry_date",
			"company",
			"work_order",
			"warehouse",
			"batch_no",
			"purchase_document_no",
			"customer",
			"description",
			"custom_weight_kg",
			"custom_heat_number",
			"custom_source_serial_no",
		}
	)

	def test_serial_no_has_item_code_not_item(self):
		self.assertIn("item_code", self.SERIAL_NO_FIELDS)
		self.assertNotIn("item", self.SERIAL_NO_FIELDS)

	def app_sources(self):
		for path in glob.glob(os.path.join(MODULE_DIR, "**", "*.py"), recursive=True):
			if "__pycache__" not in path:
				yield path
		for path in glob.glob(os.path.join(APP_DIR, "patches", "**", "*.py"), recursive=True):
			if "__pycache__" not in path:
				yield path

	def test_no_code_asks_serial_no_for_an_item_field(self):
		"""Nothing may read serial.item or the s.item SQL alias."""
		import ast
		import re

		offenders = []

		this_file = os.path.abspath(__file__)

		for path in self.app_sources():
			if os.path.abspath(path) == this_file:
				# The check describes the mistake in its own docstring.
				continue
			source = open(path).read()
			for match in re.finditer(r"\b(?:serial|s)\.(item)\b(?!_)", source):
				line = source[: match.start()].count("\n") + 1
				offenders.append(f"{os.path.relpath(path, APP_DIR)}:{line} {'.' + match.group(1)}")

			tree = ast.parse(source)
			for node in ast.walk(tree):
				if not isinstance(node, ast.Call):
					continue
				# frappe.db.get_value("Serial No", x, ["item", ...])
				if not (
					isinstance(node.func, ast.Attribute)
					and node.func.attr in ("get_value", "get_all", "set_value")
				):
					continue
				args = [ast.unparse(a) for a in node.args]
				if not args or "Serial No" not in args[0]:
					continue
				for literal in ast.walk(node):
					if isinstance(literal, ast.List):
						for element in literal.elts:
							if getattr(element, "value", None) == "item":
								line = source[: element.col_offset].count("\n") + 1
								offenders.append(
									f"{os.path.relpath(path, APP_DIR)}:{line} get_value(..., ['item', ...]) on Serial No"
								)

		self.assertEqual(
			offenders,
			[],
			"Serial No has item_code, not item: " + "; ".join(offenders),
		)


class TestFieldsWeUseAreDeclared(unittest.TestCase):
	"""A field the code reads or writes must be declared somewhere.

	Both of this app's "Unknown column" incidents - Plate Stock Register
	reading serial.item, and the first Manufacture submit dying on a
	Stock Entry Detail column no fixture shipped - shared one shape: a query
	or a db_set naming a field that no fixture and no DocType JSON ever
	ships. Nothing notices at import time; the first real document to
	reach the code is the first test.
	"""

	@staticmethod
	def declared_fields():
		fields = {f["fieldname"] for f in load(CUSTOM_FIELD_FIXTURE)}
		for path in glob.glob(os.path.join(MODULE_DIR, "doctype", "*", "*.json")):
			for field in load(path).get("fields", []):
				if field.get("fieldname"):
					fields.add(field["fieldname"])
		return fields

	def app_sources(self):
		for path in glob.glob(os.path.join(MODULE_DIR, "**", "*.py"), recursive=True):
			if "__pycache__" not in path:
				yield path

	def test_every_custom_field_literal_is_declared(self):
		"""Every custom_% string literal in the code must exist in the schema.

		String literals only: identifiers like set_custom_perms are not
		field names, and scanning those would drown the check in noise.
		"""
		import ast

		declared = self.declared_fields()
		offenders = []

		for path in self.app_sources():
			source = open(path).read()
			tree = ast.parse(source)
			for node in ast.walk(tree):
				if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
					continue
				name = node.value
				rest = name[len("custom_") :] if name.startswith("custom_") else ""
				if "_" not in rest or not rest.replace("_", "").isalnum():
					continue
				if name not in declared:
					line = source[: node.col_offset].count("\n") + 1
					offenders.append(f"{os.path.relpath(path, APP_DIR)}:{line} {name}")

		self.assertEqual(
			offenders,
			[],
			"Fields used but never declared (add them to the generator or the DocType): "
			+ "; ".join(offenders),
		)

	def test_the_offcut_links_back_to_its_stock_entries(self):
		"""plate_offcut.py writes Plate Offcut.stock_entry and .material_issue.

		These are DocType-owned rather than Custom Fields, so the sweep above
		cannot see them. They went missing once for the old cutting record and
		would have died on the first real offcut at db_set.
		"""
		offcut = load(os.path.join(MODULE_DIR, "doctype", "plate_offcut", "plate_offcut.json"))
		fields = {f.get("fieldname") for f in offcut["fields"]}
		self.assertIn("stock_entry", fields)
		self.assertIn("material_issue", fields)

	def test_every_field_the_offcut_controller_writes_is_declared(self):
		"""The DocType-owned names plate_offcut.py assigns, all on the DocType.

		Custom Fields are swept by test_every_custom_field_literal_is_declared;
		these live in the DocType JSON, so only this list sees them. A name
		that is not here fails at db_set on the first real document.
		"""
		offcut = load(os.path.join(MODULE_DIR, "doctype", "plate_offcut", "plate_offcut.json"))
		fields = {f.get("fieldname") for f in offcut["fields"]}

		for fieldname in (
			"project",
			"consumed_weight_kg",
			"consumed_value",
			"remainder_item",
			"remainder_batch_no",
			"remainder_serial_no",
			"remainder_weight_kg",
			"remainder_value",
			"scrap_weight_kg",
			"scrap_value",
			"source_plate_text",
		):
			with self.subTest(field=fieldname):
				self.assertIn(fieldname, fields)

	def test_the_offcut_item_carries_shape_and_diameter(self):
		"""plate_offcut.py and cutting.py read shape and diameter off the child.

		Same class of trap as above: the child's fields are DocType-owned, so
		a rename would only show up when a circle is cut.
		"""
		child = load(os.path.join(MODULE_DIR, "doctype", "plate_offcut_item", "plate_offcut_item.json"))
		fields = {f.get("fieldname") for f in child["fields"]}

		for fieldname in ("shape", "diameter_mm", "length_mm", "width_mm"):
			with self.subTest(field=fieldname):
				self.assertIn(fieldname, fields)
