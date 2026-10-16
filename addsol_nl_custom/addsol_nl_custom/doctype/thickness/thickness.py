# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import re

import frappe
from frappe.model.document import Document


class Thickness(Document):
	def autoname(self):
		"""Generate autoname using normalized thickness value"""
		if self.thickness_value:
			normalized_value, _ = self.split_thickness(self.thickness_value)
			self.name = normalized_value
		else:
			frappe.throw("Thickness Value is required for autoname")

	def validate(self):
		"""Normalize the label and keep thickness_mm in step with it.

		thickness_mm is the value every other part of the app reads. The label
		thickness_value stays for people to look at and for existing links.
		"""
		if self.thickness_value:
			self.thickness_value, self.thickness_mm = self.split_thickness(self.thickness_value)

	@staticmethod
	def split_thickness(value):
		"""Turn a thickness input into its display label and its number of mm.

		Handles '4', '04', '4 mm', '4mm', '2.5', ' 4 ', and returns
		('4 mm', 4) for all of them. The label always reads '<number> mm' and
		the number never carries a trailing '.0'.

		Nothing at all is refused rather than passed through: a Thickness
		always carries a value (the doctype marks it required), so there is no
		empty label for the rest of the app to read.

		The only regular expression left here strips the 'mm' unit - the number
		itself is parsed as a number, not dug out of the text.
		"""
		if value is None or not str(value).strip():
			frappe.throw(f"Invalid thickness value: {value!r}. Please enter a valid number.")

		# Drop the unit, whatever spacing or casing was used.
		cleaned = re.sub(r"\s*mm\s*$", "", str(value).strip(), flags=re.IGNORECASE).strip()

		try:
			number = float(cleaned)
		except ValueError:
			frappe.throw(f"Invalid thickness value: {value}. Please enter a valid number.")

		# 4.0 reads better as 4 in the label.
		if number.is_integer():
			number = int(number)

		return f"{number} mm", number

	@staticmethod
	def normalize_thickness(value):
		"""Backwards compatible wrapper: just the display label."""
		label, _ = Thickness.split_thickness(value)
		return label

	@staticmethod
	def parse_thickness_mm(value):
		"""Backwards compatible wrapper: just the number of mm."""
		_, number = Thickness.split_thickness(value)
		return number
