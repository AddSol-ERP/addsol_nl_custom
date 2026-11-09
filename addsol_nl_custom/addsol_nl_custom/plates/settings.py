# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Read Plate Settings, including DocType defaults for an unsaved record."""

import frappe


def get_setting(fieldname, default=None):
	"""Read the Single DocType values, falling back to field defaults.

	The fallback matters: a Single DocType row does not exist until somebody
	opens and saves the form, and a None tolerance or a None series would
	quietly break receiving.

	A BLANK value is treated as unset, not as a choice. `get_single_value`
	returns '' (empty string), never None, for a Single field that has never
	been written - so testing only for None meant a field shipped with a
	default in its DocType JSON silently resolved to '' on every site that
	had not opened the form yet. That is how `remainder_naming_series` ended
	up blank and every cutting's remainder drew from one global counter
	instead of one per Project. An empty string is never a meaningful choice
	for these settings, so blank falls through to the default.
	"""
	value = frappe.db.get_single_value("Plate Settings", fieldname)
	if value is not None and str(value).strip():
		return value

	if default is None:
		field = frappe.get_meta("Plate Settings").get_field(fieldname)
		default = field.default if field else None

	return default
