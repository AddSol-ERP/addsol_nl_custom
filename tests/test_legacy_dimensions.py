"""Legacy geometry uses Item fields and the linked Thickness master."""

import sys
import types
import unittest
from unittest.mock import Mock, patch

from addsol_nl_custom.addsol_nl_custom.plates.legacy_dimensions import item_dimensions


class LegacyDimensionsTests(unittest.TestCase):
	def test_item_geometry_includes_thickness_and_ignores_item_code(self):
		item = dict(
			item_code="MISLEADING-100x200", custom_length_mm=3000, custom_width_mm=1500, thickness_mm=10
		)
		self.assertEqual(item_dimensions(item), "L 3000 mm \u00d7 W 1500 mm \u00d7 T 10 mm")

	def test_linked_thickness_uses_existing_master_resolver(self):
		resolver = Mock(return_value=12)
		module = types.SimpleNamespace(get_item_thickness_mm=resolver)
		item = dict(custom_length_mm=2000, custom_width_mm=1000, custom_thickness_dropdown="Thickness-link")
		with patch.dict(sys.modules, {"addsol_nl_custom.addsol_nl_custom.plates.weight": module}):
			self.assertEqual(item_dimensions(item), "L 2000 mm \u00d7 W 1000 mm \u00d7 T 12 mm")
		resolver.assert_called_once_with(item)

	def test_missing_dimensions_are_not_invented(self):
		self.assertEqual(item_dimensions({}), "")
		self.assertEqual(item_dimensions(dict(custom_length_mm=3000, custom_width_mm=0)), "L 3000 mm")
