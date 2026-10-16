"""Shared helpers for this app's migrate patches."""

import functools

import frappe


def restore_developer_mode():
	"""Put conf.developer_mode back after patch_handler switched it off.

	Frappe's own patch_handler.run_single() sets conf.developer_mode = 0
	before running a patch and never restores it. migrate runs sync_fixtures
	after every patch phase, and fixture import of a standard DocType - this
	bench ships two in aitspl_integration - dies with
	CannotCreateStandardDoctypeError whenever developer_mode is off. A patch
	that leaves it off therefore breaks the rest of the migrate it is part of,
	so every patch in this app restores site_config's value on the way out,
	whether it finished or raised.
	"""
	frappe.conf.developer_mode = frappe.get_site_config().get("developer_mode", 0)


def with_developer_mode_restored(method):
	"""Run a patch's execute() with developer_mode restored afterwards.

	Only the patches.txt entry is decorated; the functions it calls stay
	plain, so a patch can still be re-run as a function in a test.
	"""

	@functools.wraps(method)
	def wrapper(*args, **kwargs):
		try:
			return method(*args, **kwargs)
		finally:
			restore_developer_mode()

	return wrapper
