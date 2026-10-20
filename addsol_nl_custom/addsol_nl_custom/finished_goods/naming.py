# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""The code a finished good is given.

`<Project>-<auto number>`, for example W-0268-00001.

The Project is the unit of work, so the number is counted per Project: the
first finished good of a project is 00001, the second is 00002, and another
project starts again at 00001. That is what makes the codes consistent - two
goods of one project can never be confused for two goods of another, and a
report grouped by project reads straight off the code.

The counter is a row in tabSeries, keyed by the expanded prefix, so two
projects never draw from the same counter. The same mechanism names the Plate
Offcut remainder, one series per project, and it behaves the same way: a
number is used even if the document it was minted for is later discarded.
"""

import re

import frappe
from frappe import _
from frappe.model.naming import make_autoname

# The series the code is built from. `{project}` is expanded from the Project
# the item belongs to, and the digits after it are counted against the
# expanded prefix, which is what makes the counter per project.
FINISHED_GOOD_SERIES = "{project}.-.#####"

# A Project name has to be usable inside a code. Project names come from a
# naming series, so they are things like W-0268 - but a Project somebody
# typed by hand could carry a space or a slash, and that has to be refused
# rather than silently stripped into a different code.
SAFE_PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]*$")

# The code split back into its two halves: the project and the number.
CODE_PARTS = re.compile(r"^(?P<project>.+)-(?P<number>\d+)$")

# The Item name column is 140 characters wide.
MAX_CODE_LENGTH = 140


def project_field_exists() -> bool:
	"""Whether Item.custom_project is on this site yet.

	The field arrives with the fixtures, so a site where the app is installed
	but the fixtures have not been synced yet has no such column. The rule
	stands down there rather than refusing every finished good for a field
	nobody can fill in yet.

	The answer is kept on frappe.local, which is released at the end of every
	request, so this costs one lookup per request rather than one per
	document. A column does not appear and vanish inside a request, so
	there is nothing to go stale here.
	"""
	cached = getattr(frappe.local, "addsol_finished_good_project_field", None)
	if cached is None:
		cached = frappe.db.has_column("Item", "custom_project")
		frappe.local.addsol_finished_good_project_field = cached

	return cached


def require_code_safe_project(project) -> str:
	"""The Project, checked for being usable inside a code.

	An empty Project is refused here rather than deeper in, because a finished
	good without a Project cannot be given a code at all.
	"""
	project = (project or "").strip()

	if not project:
		frappe.throw(
			_(
				"This is a finished good, so it needs the Project it is made for. Pick the Project and the code is built from it."
			),
			title=_("No Project for this finished good"),
		)

	if not SAFE_PROJECT.match(project):
		frappe.throw(
			_(
				"Project {0} cannot be used in an item code. A Project code may hold letters, digits, a dash and an underscore only."
			).format(project),
			title=_("Project cannot be used in an item code"),
		)

	return project


def build_finished_good_code(project) -> str:
	"""The next code for this Project, e.g. W-0268-00001.

	`make_autoname` is handed the dict it is about to name, not a string:
	`parse_naming_series` reads `{project}` off it, and that expansion is what
	puts the counter in the project's own key.
	"""
	project = require_code_safe_project(project)

	code = make_autoname(FINISHED_GOOD_SERIES, doc={"project": project})

	if len(code) > MAX_CODE_LENGTH:
		frappe.throw(
			_(
				"The code for project {0} is longer than {1} characters, so it cannot be used as an item code."
			).format(project, MAX_CODE_LENGTH),
			title=_("Project name is too long for an item code"),
		)

	return code


def project_of_code(code) -> str:
	"""The Project a code belongs to, read back off the code.

	Used to report a clash, not to enforce anything: the Item carries its
	Project in a field, and that field is what the rules read.
	"""
	if not code:
		return ""

	parts = CODE_PARTS.match(str(code))
	return parts.group("project") if parts else ""
