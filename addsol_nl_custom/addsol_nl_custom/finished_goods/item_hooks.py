# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""The finished-goods rules on the Item master.

A finished good is named from its Project, not from what somebody typed:

	<Item.custom_project>-<auto number>		W-0268-00001

The code is given once, when the Item is created, and never moves afterwards.
Renaming an Item that is already in use would orphan the stock, the batches,
the bills of materials and every document that quotes it, so an Item that
already exists keeps the code it was given.
"""

import frappe
from frappe import _

from addsol_nl_custom.addsol_nl_custom.finished_goods import groups, naming

# Where the minted code is kept between the autoname stage and the validate
# stage. A flag, not a field: it is never written to the database.
CODE_FLAG = "finished_good_code"


def item_autoname(doc, method):
	"""Give a finished good its code, built from its Project."""
	known = groups.finished_good_groups()
	if not groups.is_finished_good_group(doc.get("item_group"), known):
		return

	if is_importing():
		# An import is a deliberate bulk operation over a file somebody
		# prepared, and Frappe does not even run the autoname stage for it.
		# The file's own code stands: renaming imported records would orphan
		# whatever already points at them.
		return

	if not doc.get("__islocal"):
		# An Item that already exists. See item_validate for why the code is
		# not touched here.
		return

	if is_piece_of_a_cut(doc):
		# A piece a plate was cut into is named by the cutting process and
		# already carries its final name. Renaming it would orphan the stock,
		# the batch and the serial that point at it.
		return

	project = naming.require_code_safe_project(doc.get("custom_project"))

	typed_code = (doc.get("item_code") or "").strip()
	code = naming.build_finished_good_code(project)

	doc.flags[CODE_FLAG] = code

	# What the user typed is kept as the item name, so nothing they wrote is
	# lost when the code is replaced. ERPNext copies the code into the name
	# when the name is empty, and by then the code is ours.
	if typed_code and not (doc.get("item_name") or "").strip():
		doc.item_name = typed_code

	apply_code(doc, code)


def item_validate(doc, method):
	"""Re-assert the code, and refuse a finished good with no Project.

	The validate stage is the last one before the row is written: Frappe runs
	`validate` inside `run_before_save_methods`, and `db_insert` comes after
	it. A name set here is therefore the name the Item is stored under, which
	is why the code is asserted again here and not only in the autoname stage.
	"""
	known = groups.finished_good_groups()
	if not groups.is_finished_good_group(doc.get("item_group"), known):
		return

	if is_importing():
		# See item_autoname: the import file's own code stands.
		return

	if not doc.get("__islocal"):
		# An Item that already exists. The code stays where it is; only the
		# Project may still be corrected, and a correction that no longer
		# agrees with the code is reported rather than acted on.
		report_moved_project(doc)
		return

	if is_piece_of_a_cut(doc):
		return

	project = naming.require_code_safe_project(doc.get("custom_project"))

	code = doc.flags.get(CODE_FLAG)
	if not code:
		# The autoname stage did not run - an Item built by code that skipped
		# it, for instance. The code is minted here instead, so a finished
		# good is never left under a code somebody typed.
		code = naming.build_finished_good_code(project)
		doc.flags[CODE_FLAG] = code

	apply_code(doc, code)


def item_after_insert(doc, method):
	"""Report a code that another app replaced.

	Any app that renames Items on save reaches the same Items this rule
	names, and the one that runs last in the validate stage decides the name.
	Nothing is changed here - the Item is stored by then - but it is said
	plainly, because a finished good filed under a code this app did not mint
	is one the project reports will not find.
	"""
	code = doc.flags.get(CODE_FLAG)
	if not code or doc.name == code:
		return

	message = _(
		"A finished good was stored as {0} instead of the code this app minted, {1}. Another app on this site renames finished goods and ran after this one. Only one app may name them, or the codes will not be the ones the project reports read."
	).format(doc.name, code)

	frappe.msgprint(message, alert=True)
	print(message)


def report_moved_project(doc) -> None:
	"""Say so when the Project of an existing finished good no longer matches its code.

	Nothing is renamed: an Item that is already in use cannot be renamed
	without orphaning everything that points at it. The mismatch is reported
	so the customer can decide whether to correct the Project or to make a
	new Item.
	"""
	project = (doc.get("custom_project") or "").strip()
	if not project:
		return

	expected = naming.project_of_code(doc.get("name"))
	if not expected or expected == project:
		return

	frappe.msgprint(
		_(
			"Item {0} keeps the code it was given, which belongs to project {1}. The Project on the Item is now {2}, so the two no longer agree. Create a new Item for {2} instead: the code of an Item that is already in use cannot move."
		).format(doc.get("name"), expected, project),
		alert=True,
	)


def apply_code(doc, code) -> None:
	"""Put the generated code on the document as its name and as its item code.

	Item links are stored against the name, and ERPNext's own Item controller
	keeps `item_code` and `name` in step on a plain save - but this hook
	replaces the name, so the code has to be set here too.
	"""
	doc.name = code
	doc.item_code = code


def is_piece_of_a_cut(doc) -> bool:
	"""Whether this Item is a piece a plate was cut into.

	`custom_is_offcut` covers both offcuts - rectangular and circular - and
	`custom_is_remainder` covers the piece a plate was cut down to. Neither is
	named by the finished-goods rule: the cutting code owns the name.
	"""
	return bool(doc.get("custom_is_offcut") or doc.get("custom_is_remainder"))


def is_importing() -> bool:
	"""Whether this document is being created by a data import.

	Frappe sets the flag for both the Import File tool and
	`import_file_by_path`. An import is a deliberate bulk operation over a
	file somebody prepared, and the rules stand down for it: the file's own
	code stands, and no Project is demanded. Renaming imported records would
	orphan whatever already points at them, and refusing a bulk load over a
	code is not something a file can answer.
	"""
	return bool(frappe.flags.in_import)
