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


@frappe.whitelist(allow_guest=False)
def get_available_plates(warehouse=None, search=None, limit_start=0, limit_page_length=20) -> dict:
	"""Active serial plates that have not been cut yet, with what identifies them.

	The "what can I cut" half of the cutting screen. `status = 'Active'` does the
	exclusion work by itself: submitting a Plate Offcut repacks the source plate
	away, so a consumed plate leaves Active on its own and no bookkeeping of
	"already cut" can drift out of step with the stock.

	Weight, heat and size each live on a different table -- `Serial No
	custom_weight_kg`, `Batch custom_heat_number`, `Item custom_length_mm` -- so
	this is one join rather than three `get_value` calls per plate. Heat is read
	from the Batch for the same reason `get_source_details` reads it there: the
	list and the form must not disagree about which heat a plate belongs to.

	`can_cut` is reported rather than filtered. A plate with no recorded weight is
	refused by `get_source_details`, and dropping it from the list would leave the
	operator asking where their plate went; showing it with the reason is honest
	and lets the UI refuse the click in place.
	"""
	frappe.has_permission("Serial No", "read", throw=True)

	groups = _weighed_item_groups()
	if not groups:
		return {"plates": [], "total": 0}

	where = ["s.status = 'Active'", "i.item_group IN %(groups)s"]
	values = {"groups": tuple(groups)}

	if warehouse:
		where.append("s.warehouse = %(warehouse)s")
		values["warehouse"] = warehouse

	if search:
		where.append("(s.name LIKE %(q)s OR i.name LIKE %(q)s OR b.custom_heat_number LIKE %(q)s)")
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
			s.batch_no,
			s.warehouse,
			s.custom_weight_kg,
			b.custom_heat_number,
			i.custom_length_mm,
			i.custom_width_mm,
			COALESCE(t.thickness_mm, t.thickness_value, i.thickness_mm, 0) AS thickness_mm
		FROM `tabSerial No` s
		INNER JOIN `tabItem` i ON i.name = s.item_code
		LEFT JOIN `tabBatch` b ON b.name = s.batch_no
		LEFT JOIN `tabThickness` t ON t.name = i.custom_thickness_dropdown
		WHERE {clause}
		ORDER BY s.modified DESC
		LIMIT %(page_length)s OFFSET %(start)s
		""",
		{**values, "page_length": page_length, "start": start},
		as_dict=True,
	)

	total = frappe.db.sql(
		f"""
		SELECT COUNT(*) FROM `tabSerial No` s
		INNER JOIN `tabItem` i ON i.name = s.item_code
		LEFT JOIN `tabBatch` b ON b.name = s.batch_no
		WHERE {clause}
		""",
		values,
	)[0][0]

	plates = []
	for row in rows:
		weight = frappe.utils.flt(row.custom_weight_kg)
		plates.append(
			{
				"serial": row.serial,
				"item_code": row.item_code,
				"item_group": row.item_group,
				"batch_no": row.batch_no,
				"warehouse": row.warehouse,
				"heat_number": row.custom_heat_number,
				"weight_kg": weight,
				"length_mm": frappe.utils.flt(row.custom_length_mm),
				"width_mm": frappe.utils.flt(row.custom_width_mm),
				"thickness_mm": frappe.utils.flt(row.thickness_mm),
				"can_cut": bool(weight > 0 and row.warehouse),
				# The same refusal `get_source_details` would raise, stated here
				# so the operator learns it before clicking rather than after.
				"blocked_reason": ""
				if weight > 0 and row.warehouse
				else (
					_("Received before weights were recorded.")
					if not weight
					else _("Not in a warehouse, so there is nothing to cut.")
				),
			}
		)

	return {"plates": plates, "total": int(total)}


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
