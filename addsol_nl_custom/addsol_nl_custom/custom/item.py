# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _
import re


def item_validate(doc, method):
	"""
	Auto-name Item based on Item Group and Thickness if thickness is selected.
	Format: <Item Group Name>-<Thickness x Length x Width>
	For items without dimensions, use the manually entered item name.
	"""
	if doc.custom_thickness_dropdown:
		# Fetch the thickness value and extract numeric part
		thickness_doc = frappe.get_doc("Thickness", doc.custom_thickness_dropdown)
		thickness_value = thickness_doc.thickness_value
		
		# Extract numeric value from thickness (e.g., "4 mm" -> "4")
		thickness_numeric = re.sub(r'[^0-9.]', '', thickness_value) or thickness_value
		
		# Get Item Group name
		item_group_name = doc.item_group
		
		# Get dimensions
		length = doc.custom_length_mm or 0
		width = doc.custom_width_mm or 0
		
		# Generate new name with dimensions
		if length and width:
			new_name = f"{item_group_name}-{thickness_numeric}x{length}x{width}"
		elif length:
			new_name = f"{item_group_name}-{thickness_numeric}x{length}"
		elif width:
			new_name = f"{item_group_name}-{thickness_numeric}x{width}"
		else:
			new_name = f"{item_group_name}-{thickness_numeric}"
		
		# Set item_name if it's different
		if doc.item_name != new_name:
			doc.item_name = new_name
	
	# Set description with dimensions if it contains "*New*" or is empty
	if doc.description == "*New*" or not doc.description:
		if doc.custom_thickness_dropdown:
			thickness_doc = frappe.get_doc("Thickness", doc.custom_thickness_dropdown)
			thickness_value = thickness_doc.thickness_value
			
			length = doc.custom_length_mm or 0
			width = doc.custom_width_mm or 0
			
			if length and width:
				doc.description = f"{thickness_numeric} x {length} x {width} mm"
			elif length:
				doc.description = f"{thickness_numeric} x {length} mm"
			elif width:
				doc.description = f"{thickness_numeric} x {width} mm"
			else:
				doc.description = f"{thickness_value}"
		else:
			doc.description = ""


def item_autoname(doc, method):
	"""
	Override autoname to use custom naming when thickness is selected.
	For items without thickness, use the manually entered item name.
	"""
	if doc.custom_thickness_dropdown and doc.item_group:
		# Fetch the thickness value and extract numeric part
		thickness_doc = frappe.get_doc("Thickness", doc.custom_thickness_dropdown)
		thickness_value = thickness_doc.thickness_value
		
		# Extract numeric value from thickness (e.g., "4 mm" -> "4")
		thickness_numeric = re.sub(r'[^0-9.]', '', thickness_value) or thickness_value
		
		# Get Item Group name
		item_group_name = doc.item_group
		
		# Get dimensions
		length = doc.custom_length_mm or 0
		width = doc.custom_width_mm or 0
		
		# Generate unique name with dimensions
		if length and width:
			doc.name = f"{item_group_name}-{thickness_numeric}x{length}x{width}"
		elif length:
			doc.name = f"{item_group_name}-{thickness_numeric}x{length}"
		elif width:
			doc.name = f"{item_group_name}-{thickness_numeric}x{width}"
		else:
			doc.name = f"{item_group_name}-{thickness_numeric}"
	else:
		# For items without thickness, use the manually entered item name
		if doc.item_name:
			doc.name = doc.item_name
		else:
			# Safety check: prevent saving if no item name is provided
			frappe.throw("Item Name is required for items without thickness.")


def item_on_update(doc, method):
	"""
	Renames the item when thickness or dimensions change on an existing document.
	"""
	if not (doc.custom_thickness_dropdown and doc.item_group):
		return

	# Fetch the thickness value and extract numeric part
	thickness_doc = frappe.get_doc("Thickness", doc.custom_thickness_dropdown)
	thickness_value = thickness_doc.thickness_value
	
	# Extract numeric value from thickness (e.g., "4 mm" -> "4")
	thickness_numeric = re.sub(r'[^0-9.]', '', thickness_value) or thickness_value
	
	# Get dimensions
	length = doc.custom_length_mm or 0
	width = doc.custom_width_mm or 0
	
	# Generate new name with dimensions
	if length and width:
		new_name = f"{doc.item_group}-{thickness_numeric}x{length}x{width}"
	elif length:
		new_name = f"{doc.item_group}-{thickness_numeric}x{length}"
	elif width:
		new_name = f"{doc.item_group}-{thickness_numeric}x{width}"
	else:
		new_name = f"{doc.item_group}-{thickness_numeric}"

	# Only rename if name actually changed
	if doc.name == new_name:
		return

	try:
		frappe.rename_doc(
			"Item",
			doc.name,       # old name
			new_name,       # new name
		)
		frappe.db.commit()
	except Exception as e:
		frappe.msgprint(f"Could not rename Item: {str(e)}")


# def item_on_update(doc, method):
#     """
#     Renames the item (and updates all linked documents) when thickness
#     or item_group changes on an *existing* document.
#     """
#     if not (doc.custom_thickness_dropdown and doc.item_group):
#         return

#     thickness_doc = frappe.get_doc("Thickness", doc.custom_thickness_dropdown)
#     thickness_value = thickness_doc.thickness_value
#     new_name = f"{doc.item_group}-{thickness_value}"

#     # Only rename if the name actually changed — avoids infinite loop
#     if doc.name == new_name:
#         return

#     frappe.rename_doc(
#         "Item",
#         doc.name,       # old name
#         new_name,       # new name
#         ignore_permissions=True,
#     )