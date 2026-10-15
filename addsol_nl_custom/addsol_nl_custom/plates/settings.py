# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Read Plate Settings, including DocType defaults for an unsaved record."""

import frappe


def get_setting(fieldname, default=None):
	"""Read the Single DocType values, falling back to field defaults.

	The fallback matters: a Single DocType row does not exist until somebody
	opens and saves the form, and a None tolerance or a None series would
	quietly break receiving.
	"""
	value = frappe.db.get_single_value("Plate Settings", fieldname)
	if value is not None:
		return value

	if default is None:
		field = frappe.get_meta("Plate Settings").get_field(fieldname)
		default = field.default if field else None

	return default


def is_enabled() -> bool:
	"""Whether the weight based purchasing rules should act.

	Off by default. While this is off the whole of Part D stands down and rates
	and amounts are whatever the user typed, so a half-finished deployment
	cannot move money.
	"""
	return bool(get_setting("enable_weight_based_purchasing", 0))


def require_enabled() -> None:
	"""Guard for entry points that must not silently do nothing."""
	if not is_enabled():
		frappe.throw(
			"Weight based purchasing is switched off in Plate Settings. Turn it on to use "
			"weight based rates and amounts on Purchase Orders, Receipts and Invoices.",
			title="Weight based purchasing is off",
		)
