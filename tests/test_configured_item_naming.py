"""Customer naming defers to an explicitly configured shared code rule."""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1] / "addsol_nl_custom/addsol_nl_custom"


def load_function(path, name, namespace):
	node = next(node for node in ast.parse(path.read_text()).body
		if isinstance(node, ast.FunctionDef) and node.name == name)
	exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
	return namespace[name]


class Doc(dict):
	__getattr__ = dict.get
	__setattr__ = dict.__setitem__


class ConfiguredNamingTests(unittest.TestCase):
	def test_customer_autoname_hooks_stand_down(self):
		for file in ("plates/item_hooks.py", "finished_goods/item_hooks.py"):
			with self.subTest(file=file):
				fn = load_function(ROOT / file, "item_autoname", {"uses_configured_item_code": lambda doc: True})
				doc = Doc(name="SHARED-CODE", item_code="SHARED-CODE")
				fn(doc, "autoname")
				self.assertEqual(doc.name, "SHARED-CODE")

	def test_plate_validation_keeps_code_and_still_applies_weight_defaults(self):
		weight, defaults = Mock(), Mock()
		namespace = {
			"uses_configured_item_code": lambda doc: True,
			"is_finished_good": lambda doc: False,
			"is_cutting_generated": lambda doc: False,
			"get_item_thickness_mm": lambda doc: 10,
			"build_plate_item_name": lambda *args: "LEGACY-CODE",
			"is_weighed_group": lambda group: True,
			"refresh_estimated_weight": weight,
			"apply_plate_item_defaults": defaults,
		}
		fn = load_function(ROOT / "plates/item_hooks.py", "item_validate", namespace)
		doc = Doc(name="SHARED-CODE", item_code="SHARED-CODE", item_name="Plate",
			custom_thickness_dropdown="10", item_group="Plate", custom_length_mm=2500,
			custom_width_mm=1250, description="Plate", __islocal=True)
		fn(doc, "validate")
		self.assertEqual((doc.name, doc.item_code, doc.item_name), ("SHARED-CODE", "SHARED-CODE", "Plate"))
		weight.assert_called_once_with(doc, 10, 2500, 1250)
		defaults.assert_called_once_with(doc)

	def test_finished_good_validate_stands_down(self):
		fn = load_function(ROOT / "finished_goods/item_hooks.py", "item_validate",
			{"uses_configured_item_code": lambda doc: True})
		doc = Doc(name="CUSTOM-CODE", item_code="CUSTOM-CODE")
		fn(doc, "validate")
		self.assertEqual(doc.item_code, "CUSTOM-CODE")

	def test_plate_legacy_naming_remains_available(self):
		fn = load_function(ROOT / "plates/item_hooks.py", "item_autoname", {
			"uses_configured_item_code": lambda doc: False,
			"is_cutting_generated": lambda doc: False,
			"is_finished_good": lambda doc: False,
			"build_plate_item_name": lambda *args: "LEGACY-CODE",
			"get_item_thickness_mm": lambda doc: 10,
		})
		doc = Doc(item_group="Plate", custom_thickness_dropdown="10", custom_length_mm=2500, custom_width_mm=1250)
		fn(doc, "autoname")
		self.assertEqual((doc.name, doc.item_code), ("LEGACY-CODE", "LEGACY-CODE"))
