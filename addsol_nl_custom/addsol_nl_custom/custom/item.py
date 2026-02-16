# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def item_validate(doc, method):
	"""
	Auto-name Item based on Item Group and Thickness if thickness is selected.
	Format: <Item Group Name>-<Thickness Value>
	"""
	if doc.custom_thickness_dropdown:
		# Fetch the thickness value
		thickness_doc = frappe.get_doc("Thickness", doc.custom_thickness_dropdown)
		thickness_value = thickness_doc.thickness_value
		
		# Get Item Group name
		item_group_name = doc.item_group
		
		# Generate new name
		new_name = f"{item_group_name}-{thickness_value}"
		
		# Set item_code if it's different
		if doc.item_code != new_name:
			doc.item_code = new_name
			
		# Set item_name if it's different
		if doc.item_name != new_name:
			doc.item_name = new_name


def item_autoname(doc, method):
	"""
	Override autoname to use custom naming when thickness is selected.
	"""
	if doc.custom_thickness_dropdown and doc.item_group:
		# Fetch the thickness value
		thickness_doc = frappe.get_doc("Thickness", doc.custom_thickness_dropdown)
		thickness_value = thickness_doc.thickness_value
		
		# Get Item Group name
		item_group_name = doc.item_group
		
		# Generate new name
		doc.name = f"{item_group_name}-{thickness_value}"