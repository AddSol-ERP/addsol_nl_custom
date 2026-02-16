# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import re


class Thickness(Document):
	def autoname(self):
		"""Generate autoname using normalized thickness value"""
		if self.thickness_value:
			normalized_value = self.normalize_thickness(self.thickness_value)
			self.name = normalized_value
		else:
			frappe.throw("Thickness Value is required for autoname")
	
	def validate(self):
		"""Normalize thickness value to format: <number> mm"""
		if self.thickness_value:
			self.thickness_value = self.normalize_thickness(self.thickness_value)
	
	@staticmethod
	def normalize_thickness(value):
		"""
		Normalize thickness input to standard format: <number> mm
		Handles inputs like: '4', '04', '110', '4 mm', '4mm', '04mm'
		Returns: '4 mm', '110 mm', etc.
		"""
		if not value:
			return value
		
		# Convert to string and strip whitespace
		value = str(value).strip()
		
		# Remove 'mm' if present (case insensitive)
		value_cleaned = re.sub(r'\s*mm\s*$', '', value, flags=re.IGNORECASE).strip()
		
		# Extract numeric value
		try:
			# Convert to float first to handle decimals, then to int if it's a whole number
			numeric_value = float(value_cleaned)
			
			# If it's a whole number, convert to int to remove .0
			if numeric_value.is_integer():
				numeric_value = int(numeric_value)
			
			# Return formatted value
			return f"{numeric_value} mm"
		except ValueError:
			frappe.throw(f"Invalid thickness value: {value}. Please enter a valid number.")