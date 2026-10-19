# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Whitelisted helpers the desk forms call."""

import frappe
from frappe import _

from addsol_nl_custom.addsol_nl_custom.plates import cutting
from addsol_nl_custom.addsol_nl_custom.plates.settings import get_setting
from addsol_nl_custom.addsol_nl_custom.plates.weight import compute_theoretical_weight


@frappe.whitelist()
def get_theoretical_weight(
	item_group=None, thickness=None, thickness_mm=None, length_mm=None, width_mm=None
) -> float:
	"""Preview the theoretical weight of one piece while the Item form is open.

	public/js/item.js calls this whenever the grade or a dimension changes and
	shows the result in the read-only custom_estimated_weight field. The same
	calculation runs on save in item_hooks.set_estimated_weight; this one is
	only for the preview.

	Pass thickness as the Thickness record name - the browser must not turn a
	link value into a number, or the two paths would disagree.
	"""
	if thickness_mm is None and thickness:
		thickness_mm = frappe.db.get_value("Thickness", thickness, "thickness_mm")

	return compute_theoretical_weight(
		item_group=item_group,
		thickness_mm=thickness_mm,
		length_mm=length_mm,
		width_mm=width_mm,
	)


@frappe.whitelist(allow_guest=False)
def estimate_offcut_weights(source_serial_no, rows) -> dict:
	"""Preview every offcut's weight and the cutting's total while the form is open.

	public/js/plate_offcut.js asks for this whenever a dimension or a row
	changes. It runs the same functions the save will run -
	cutting.get_offcut_details, cutting.compute_offcut, cutting.auto_scrap_weight
	and cutting.offcut_totals - so the preview is not a second implementation
	that can drift; it is the same arithmetic, asked for earlier. The save
	keeps the say, and this deliberately does not reject a cutting that runs
	over - it reports over_by_kg and lets the operator decide.

	`rows` is the offcut lines as JSON: [{"name", "length_mm", "width_mm"}].
	Each line's `name` is echoed straight back, so a reply that lands after the
	operator has typed again is recognised and dropped instead of being written
	onto the wrong row.

	Scrap is not an input: the plate is consumed whole, so the scrap balances
	the weight automatically and is reported back for the form to show.

	A line with a length but no width yet returns zeroes rather than asking for
	the weight of a zero-size plate, which the formula refuses to guess. That
	line is simply not drawn yet; the save rejects it properly through
	check_offcut_fits, as it always has.
	"""
	frappe.has_permission("Plate Offcut", "write", throw=True)

	details = cutting.get_offcut_details(source_serial_no)
	weights: list[float] = []
	values: list[float] = []
	previewed: list[dict] = []

	for line in frappe.parse_json(rows) or []:
		line = frappe._dict(line)
		estimate = {"name": line.get("name")}

		if frappe.utils.flt(line.length_mm) > 0 and frappe.utils.flt(line.width_mm) > 0:
			row = frappe._dict({"length_mm": line.length_mm, "width_mm": line.width_mm})
			cutting.compute_offcut(row, details)
			estimate.update(
				theoretical_weight_kg=row.theoretical_weight_kg,
				weight_kg=row.weight_kg,
				value=row.value,
			)
		else:
			estimate.update(theoretical_weight_kg=0.0, weight_kg=0.0, value=0.0)

		previewed.append(estimate)
		weights.append(estimate["weight_kg"])
		values.append(estimate["value"])

	# The same scrap the save will derive, so the preview and the save can
	# never disagree about how much of the plate is left over.
	# The smallest offcut this grade keeps, so the form can say "too small" on
	# the row instead of letting the save refuse it. Read through the SAME
	# function `check_offcut_fits` calls, so the threshold here and the threshold
	# enforced at save cannot drift apart. Zero means "not configured", which the
	# client treats as no check rather than as "nothing may be kept".
	min_length, min_width = cutting.minimum_offcut(details["grade"])

	scrap_weight_kg = cutting.auto_scrap_weight(details["weight"], weights)

	totals = cutting.offcut_totals(
		source_weight_kg=details["weight"],
		scrap_weight_kg=scrap_weight_kg,
		row_weights=weights,
		row_values=values,
		cost_per_kg=details["cost_per_kg"],
	)

	return {
		"source_weight_kg": totals["source_weight_kg"],
		"rows": previewed,
		"total_offcut_weight_kg": totals["total_offcut_weight_kg"],
		"total_offcut_value": totals["total_offcut_value"],
		"scrap_weight_kg": totals["scrap_weight_kg"],
		"scrap_value": totals["scrap_value"],
		"over_by_kg": totals["over_by_kg"],
		# The plate's own size, straight off `get_offcut_details` above. The
		# caller draws a scaled cut layout from these, and re-deriving them in
		# the browser from the Item name would be a second source of truth for
		# something the server has already read. `thickness_mm` rather than the
		# Item's `custom_thickness_dropdown`, because that is a Link to a
		# Thickness whose *label* is a display string like "10 mm".
		"source_length_mm": details["length_mm"],
		"source_width_mm": details["width_mm"],
		"source_thickness_mm": details["thickness_mm"],
		"min_offcut_length_mm": min_length,
		"min_offcut_width_mm": min_width,
	}


def _weighed_item_groups() -> list[str]:
	"""Item Groups that opted in to being weighed -- the grades a plate can be.

	`grouping.is_weighed_group` additionally insists on a usable formula and a
	multiplication factor. This is a LIST, so the gate is the flag alone: a group
	that was flagged but is half-configured still has real plates sitting in
	stock, and hiding those would look like data loss rather than a filter.
	"""
	from addsol_nl_custom.addsol_nl_custom.plates.grouping import WEIGHED_GRADE_FLAG

	return frappe.get_all("Item Group", filters={WEIGHED_GRADE_FLAG: 1}, pluck="name")


# `limit_page_length` reaches us as whatever JSON sent, so it is clamped rather
# than trusted: a single request must not be able to ask for the whole table.
MAX_PAGE_LENGTH = 200


def _thickness_mm(thickness_mm, thickness_value) -> float:
	"""Thickness in mm from a Thickness row, mirroring weight.get_item_thickness_mm.

	`thickness_value` is a Data display string like "10 mm", so it is split with
	`Thickness.split_thickness` rather than `flt` -- which would return 0 for the
	whole string. Doing the split here (once, in Python) instead of per row keeps
	this a single query: calling `get_item_thickness_mm` per plate would issue a
	further `get_value` for every row on the page.
	"""
	if frappe.utils.flt(thickness_mm):
		return frappe.utils.flt(thickness_mm)

	if not thickness_value:
		return 0.0

	from addsol_nl_custom.addsol_nl_custom.doctype.thickness.thickness import Thickness

	_, number = Thickness.split_thickness(thickness_value)
	return frappe.utils.flt(number)


@frappe.whitelist(allow_guest=False)
def get_available_plates(warehouse=None, search=None, limit_start=0, limit_page_length=10) -> dict:
	"""Plate ITEMS awaiting a cut, each carrying its own plates.

	Grouping and paging both happen here, per item, rather than being left to the
	client. Paging the SERIALS and grouping the page afterwards is wrong in two
	ways that only show up once there is more than one page of stock:

	  - a parent row's count and total weight describe the page, not the item, so
	    twenty-five plates of one mill read as "10";
	  - an item whose plates straddle a page boundary appears as two separate
	    groups, and paging forward shows the operator the same item again.

	`limit_page_length` is therefore ITEMS, not serials.

	`status = 'Active'` does the exclusion work by itself: submitting a Plate
	Offcut repacks the source plate away, so a consumed plate leaves Active on
	its own and no bookkeeping of "already cut" can drift out of step with stock.

	Weight, heat and size each live on a different table -- `Serial No
	custom_weight_kg`, `Batch custom_heat_number`, `Item custom_length_mm` -- so
	this joins rather than issuing three `get_value` calls per plate. Heat is read
	from the Batch for the same reason `get_source_details` reads it there: the
	list and the form must not disagree about which heat a plate belongs to.

	`can_cut` is reported rather than filtered, exactly as `get_source_details`
	would refuse it: a plate with no recorded weight is a record to fix, and
	dropping it would leave the operator asking where their plate went. The
	aggregate carries a `blocked_count` so the parent row can say how many of its
	plates need attention without opening anything.
	"""
	frappe.has_permission("Serial No", "read", throw=True)

	weighed = _weighed_item_groups()
	if not weighed:
		return {"groups": [], "total": 0}

	where = ["s.status = 'Active'", "i.item_group IN %(weighed)s"]
	values = {"weighed": tuple(weighed)}

	if warehouse:
		where.append("s.warehouse = %(warehouse)s")
		values["warehouse"] = warehouse

	if search:
		where.append("(s.name LIKE %(q)s OR i.name LIKE %(q)s OR b.custom_heat_number LIKE %(q)s)")
		values["q"] = f"%{search}%"

	clause = " AND ".join(where)
	page_length = min(max(int(limit_page_length or 10), 1), MAX_PAGE_LENGTH)
	start = max(int(limit_start or 0), 0)

	# A plate can be cut when it has a weight AND is sitting in a warehouse --
	# the same two conditions `get_source_details` and `plate_offcut.py` check.
	# Repeated verbatim in the aggregate below so a blocked plate is counted the
	# same way it is labelled; the two must not be able to disagree.
	BLOCKED = "(COALESCE(s.custom_weight_kg, 0) <= 0 OR s.warehouse IS NULL OR s.warehouse = '')"

	# An f-string, deliberately: this is interpolated into another f-string, and
	# a plain string here would leave a literal `{clause}` in the SQL. ruff's
	# unused-variable check is what caught that -- `clause` looked assigned and
	# used but reached the database un-substituted.
	FROM_JOIN = f"""
		FROM `tabSerial No` s
		INNER JOIN `tabItem` i ON i.name = s.item_code
		LEFT JOIN `tabBatch` b ON b.name = s.batch_no
		LEFT JOIN `tabThickness` t ON t.name = i.custom_thickness_dropdown
		WHERE {clause}
	"""

	# 1. the page of items, with their totals across EVERY matching plate
	items = frappe.db.sql(
		f"""
		SELECT
			i.name AS item_code,
			MAX(i.item_group) AS item_group,
			MAX(COALESCE(i.custom_length_mm, 0)) AS length_mm,
			MAX(COALESCE(i.custom_width_mm, 0)) AS width_mm,
			MAX(COALESCE(t.thickness_mm, 0)) AS thickness_mm,
			MAX(t.thickness_value) AS thickness_value,
			COUNT(*) AS plate_count,
			COALESCE(SUM(COALESCE(s.custom_weight_kg, 0)), 0) AS total_weight_kg,
			COUNT(DISTINCT NULLIF(s.warehouse, '')) AS warehouse_count,
			COUNT(DISTINCT NULLIF(b.custom_heat_number, '')) AS heat_count,
			SUM(CASE WHEN {BLOCKED} THEN 1 ELSE 0 END) AS blocked_count
		{FROM_JOIN}
		GROUP BY i.name
		ORDER BY plate_count DESC, i.name ASC
		LIMIT %(page_length)s OFFSET %(start)s
		""",
		{**values, "page_length": page_length, "start": start},
		as_dict=True,
	)

	total = frappe.db.sql(
		f"SELECT COUNT(DISTINCT i.name) {FROM_JOIN}",
		values,
	)[0][0]

	if not items:
		return {"groups": [], "total": 0}

	codes = [row.item_code for row in items]

	# 2. the plates behind just those items.
	#
	# NO `FIELD(i.name, ...)`. pymysql escapes a tuple to `('a', 'b')`, so that
	# call reaches MariaDB as a ROW VALUE operand and a scalar function rejects
	# it with errno 1241 "Operand should contain 1 column(s)". The order is
	# irrelevant here anyway: `by_item` below buckets the rows and the groups are
	# emitted in `items` order, so the page's item ordering is preserved without
	# the database having to reproduce it.
	plates = frappe.db.sql(
		f"""
		SELECT
			s.name AS serial,
			s.item_code,
			s.batch_no,
			s.warehouse,
			s.custom_weight_kg,
			b.custom_heat_number,
			(COALESCE(s.custom_weight_kg, 0) > 0 AND COALESCE(s.warehouse, '') != '') AS can_cut
		{FROM_JOIN}
			AND i.name IN %(codes)s
		ORDER BY i.name ASC, s.name ASC
		""",
		{**values, "codes": tuple(codes)},
		as_dict=True,
	)

	by_item: dict[str, list] = {code: [] for code in codes}
	for plate in plates:
		by_item.setdefault(plate.item_code, []).append(plate)

	groups = []
	for row in items:
		children = []
		for plate in by_item.get(row.item_code, []):
			can_cut = bool(plate.can_cut)
			children.append(
				{
					"serial": plate.serial,
					"batch_no": plate.batch_no,
					"warehouse": plate.warehouse,
					"heat_number": plate.custom_heat_number,
					"weight_kg": frappe.utils.flt(plate.custom_weight_kg),
					"can_cut": can_cut,
					# The same refusal `get_source_details` raises, stated here so
					# the operator learns it before clicking rather than after.
					"blocked_reason": ""
					if can_cut
					else (
						_("Received before weights were recorded.")
						if not frappe.utils.flt(plate.custom_weight_kg)
						else _("Not in a warehouse, so there is nothing to cut.")
					),
				}
			)

		groups.append(
			{
				"item_code": row.item_code,
				"item_group": row.item_group,
				"length_mm": frappe.utils.flt(row.length_mm),
				"width_mm": frappe.utils.flt(row.width_mm),
				"thickness_mm": _thickness_mm(row.thickness_mm, row.thickness_value),
				"plate_count": int(row.plate_count),
				"total_weight_kg": frappe.utils.flt(row.total_weight_kg),
				"warehouse_count": int(row.warehouse_count or 0),
				"heat_count": int(row.heat_count or 0),
				"blocked_count": int(row.blocked_count or 0),
				"plates": children,
			}
		)

	return {"groups": groups, "total": int(total)}


@frappe.whitelist(allow_guest=False)
def get_offcut_stock(search=None, limit_start=0, limit_page_length=20) -> dict:
	"""The offcut pieces already in stock, each pointing back to the plate it came from.

	The "what did I make" half of the cutting screen. `stamp_offcut_serials`
	writes `custom_source_serial_no` onto every offcut serial on submit, so that
	column IS the set of offcuts -- there is no separate flag to keep in step.

	Joining from `tabSerial No` rather than from the Plate Offcut Item matters:
	`cutting.reserve_serial_no` only takes a NAME, so a draft's row already
	carries a serial number that does not exist as a document. Starting from
	Serial No therefore shows submitted stock only, with no draft leaking in.
	"""
	frappe.has_permission("Serial No", "read", throw=True)

	where = ["s.custom_source_serial_no IS NOT NULL", "s.custom_source_serial_no != ''"]
	values: dict = {}

	if search:
		where.append(
			"(s.name LIKE %(q)s OR s.item_code LIKE %(q)s"
			" OR s.custom_source_serial_no LIKE %(q)s OR b.custom_heat_number LIKE %(q)s)"
		)
		values["q"] = f"%{search}%"

	clause = " AND ".join(where)
	page_length = min(max(int(limit_page_length or 20), 1), MAX_PAGE_LENGTH)
	start = max(int(limit_start or 0), 0)

	rows = frappe.db.sql(
		f"""
		SELECT
			s.name AS serial,
			s.item_code,
			i.item_group,
			s.custom_source_serial_no AS source_serial,
			s.batch_no,
			s.warehouse,
			s.status,
			s.custom_weight_kg,
			b.custom_heat_number,
			p.length_mm,
			p.width_mm,
			p.theoretical_weight_kg,
			p.value,
			p.parent AS offcut
		FROM `tabSerial No` s
		INNER JOIN `tabPlate Offcut Item` p ON p.serial_no = s.name
		LEFT JOIN `tabItem` i ON i.name = s.item_code
		LEFT JOIN `tabBatch` b ON b.name = s.batch_no
		WHERE {clause}
		ORDER BY p.creation DESC
		LIMIT %(page_length)s OFFSET %(start)s
		""",
		{**values, "page_length": page_length, "start": start},
		as_dict=True,
	)

	total = frappe.db.sql(
		f"""
		SELECT COUNT(*) FROM `tabSerial No` s
		INNER JOIN `tabPlate Offcut Item` p ON p.serial_no = s.name
		LEFT JOIN `tabBatch` b ON b.name = s.batch_no
		WHERE {clause}
		""",
		values,
	)[0][0]

	pieces = [
		{
			"serial": row.serial,
			"item_code": row.item_code,
			"item_group": row.item_group,
			"source_serial": row.source_serial,
			"batch_no": row.batch_no,
			"warehouse": row.warehouse,
			"status": row.status,
			"heat_number": row.custom_heat_number,
			"weight_kg": frappe.utils.flt(row.custom_weight_kg),
			"theoretical_weight_kg": frappe.utils.flt(row.theoretical_weight_kg),
			"value": frappe.utils.flt(row.value),
			"length_mm": frappe.utils.flt(row.length_mm),
			"width_mm": frappe.utils.flt(row.width_mm),
			# The Plate Offcut that produced it, so a click can open the job.
			"offcut": row.offcut,
		}
		for row in rows
	]

	return {"pieces": pieces, "total": int(total)}


@frappe.whitelist(allow_guest=False)
def get_plate_settings():
	"""Return plate-receipt UI capabilities for the signed-in user."""
	approver_role = get_setting("approver_role")
	user_roles = frappe.get_roles()
	return {
		"weight_tolerance_pct": get_setting("weight_tolerance_pct", 10),
		"enable_weight_based_purchasing": bool(get_setting("enable_weight_based_purchasing", 0)),
		"can_decide_weight": not approver_role or approver_role in user_roles,
	}


@frappe.whitelist(allow_guest=False)
def is_weight_managed_item(item_code=None):
	"""Tell the purchase forms whether to show weight pricing for an Item."""
	if not item_code or not get_setting("enable_weight_based_purchasing", 0):
		return False

	from addsol_nl_custom.addsol_nl_custom.plates.grouping import is_weighed_item

	return bool(is_weighed_item(item_code))


@frappe.whitelist(allow_guest=False)
def get_last_rate(item_code=None, supplier=None) -> float:
	"""Offer the last rate per kg agreed for an Item when a line is still empty.

	Only ever a starting point. The desk calls this as the buyer picks an item
	or a supplier, and the client is written to fill the field only when it has
	not been typed into - a rate somebody entered is never replaced by this.
	"""
	if not item_code:
		return 0.0

	from addsol_nl_custom.addsol_nl_custom.plates.rate_history import last_rate

	return last_rate(item_code, supplier)
