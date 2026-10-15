# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""Plate Receipt Weight Variance.

Every weighed receipt line with the supplier's weight against the estimate,
and whether it was accepted automatically or had to be decided by somebody.
Rows above the tolerance are flagged so the approvers can see at a glance what
is waiting on them.
"""

import frappe
from frappe.utils import flt

from addsol_nl_custom.addsol_nl_custom.plates.settings import get_setting

COLUMNS = [
	{
		"fieldname": "receipt",
		"label": "Receipt",
		"fieldtype": "Link",
		"options": "Purchase Receipt",
		"width": 160,
	},
	{"fieldname": "posting_date", "label": "Date", "fieldtype": "Date", "width": 100},
	{"fieldname": "supplier", "label": "Supplier", "fieldtype": "Link", "options": "Supplier", "width": 160},
	{"fieldname": "item", "label": "Item", "fieldtype": "Link", "options": "Item", "width": 240},
	{"fieldname": "plates", "label": "Plates", "fieldtype": "Int", "width": 80},
	{"fieldname": "estimated_kg", "label": "Estimated (Kg)", "fieldtype": "Float", "width": 120},
	{"fieldname": "supplier_kg", "label": "Supplier (Kg)", "fieldtype": "Float", "width": 130},
	{"fieldname": "variance_pct", "label": "Variance %", "fieldtype": "Percent", "width": 110},
	{"fieldname": "decision", "label": "Decision", "fieldtype": "Data", "width": 170},
	{"fieldname": "accepted_kg", "label": "Accepted (Kg)", "fieldtype": "Float", "width": 130},
	{"fieldname": "amount", "label": "Amount", "fieldtype": "Currency", "width": 130},
	{"fieldname": "above_tolerance", "label": "Above Tolerance", "fieldtype": "Check", "width": 130},
]


def execute(filters=None):
	filters = filters or {}
	tolerance = flt(get_setting("weight_tolerance_pct", 10))
	above_only = bool(filters.get("above_tolerance_only"))

	data = []
	for row in fetch_rows(filters):
		variance = flt(row.custom_variance_pct)
		is_above = abs(variance) > tolerance
		if above_only and not is_above:
			continue
		data.append(
			{
				"receipt": row.parent,
				"posting_date": row.posting_date,
				"supplier": row.supplier,
				"item": row.item_code,
				"plates": flt(row.qty),
				"estimated_kg": flt(row.custom_est_weight_kg),
				"supplier_kg": flt(row.custom_supplier_weight_kg),
				"variance_pct": variance,
				"decision": row.custom_weight_decision or "",
				"accepted_kg": flt(row.custom_billable_weight_kg),
				"amount": flt(row.amount),
				"above_tolerance": 1 if is_above else 0,
			}
		)

	data.sort(key=lambda row: (row["posting_date"] or "", row["receipt"], row["item"]))

	totals = {
		"plates": sum(row["plates"] for row in data),
		"estimated_kg": sum(row["estimated_kg"] for row in data),
		"supplier_kg": sum(row["supplier_kg"] for row in data),
		"accepted_kg": sum(row["accepted_kg"] for row in data),
		"amount": sum(row["amount"] for row in data),
	}

	return list(COLUMNS), data, None, totals, None


def fetch_rows(filters):
	"""Submitted, plate receipt lines inside the date range."""
	conditions = ["pr.docstatus = 1", "pri.custom_is_plate = 1"]

	if filters.get("from_date"):
		conditions.append(f"pr.posting_date >= {_quote(filters['from_date'])}")
	if filters.get("to_date"):
		conditions.append(f"pr.posting_date <= {_quote(filters['to_date'])}")
	if filters.get("supplier"):
		conditions.append(f"pr.supplier = {_quote(filters['supplier'])}")
	if filters.get("item_group"):
		conditions.append(f"i.item_group = {_quote(filters['item_group'])}")

	where = " and ".join(conditions)

	return frappe.db.sql(
		f"""
		select pri.parent, pr.posting_date, pr.supplier, pri.item_code, pri.qty, pri.amount,
		       pri.custom_est_weight_kg, pri.custom_supplier_weight_kg,
		       pri.custom_variance_pct, pri.custom_weight_decision,
		       pri.custom_billable_weight_kg
		  from `tabPurchase Receipt Item` pri
		  inner join `tabPurchase Receipt` pr on pr.name = pri.parent
		  left join `tabItem` i on i.name = pri.item_code
		 where {where}
		 order by pr.posting_date, pri.parent, pri.idx
		""",
		as_dict=True,
	)


def _quote(value) -> str:
	return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"
