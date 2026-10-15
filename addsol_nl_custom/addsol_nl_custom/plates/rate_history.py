# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

"""The last rate per kg agreed for an item, offered as a starting point.

This is a suggestion and nothing more. The rate per kg is the buyer's to
enter, so nothing here overwrites a figure someone has already typed - a rate
found here is only ever handed back to fill a line that is still empty.

There is deliberately no supplier price list behind this. A Purchase Order
reads a rate the buyer types, not one a supplier's record dictates.
"""

import frappe

from addsol_nl_custom.addsol_nl_custom.plates.utils import round_half_up

# Enough recent orders to be useful without pulling a whole history into
# memory for one suggestion.
LOOKBACK_ROWS = 20


def last_rate(item_code, supplier=None) -> float:
	"""The last rate per kg agreed for this item, or 0.0 when there is none.

	Prefers this supplier's own last rate, and falls back to any supplier's, so
	a new supplier is still offered the going rate instead of an empty field.
	Draft and cancelled orders are ignored - only what was actually agreed
	counts.
	"""
	if not item_code:
		return 0.0

	rows = frappe.db.sql(
		"""
		select po.supplier as supplier, poi.custom_rate_per_kg as rate_per_kg
		  from `tabPurchase Order Item` poi
		  join `tabPurchase Order` po on po.name = poi.parent
		 where poi.docstatus = 1
		   and poi.item_code = %s
		   and ifnull(poi.custom_rate_per_kg, 0) > 0
		 order by po.transaction_date desc, poi.modified desc
		 limit %s
		""",
		(item_code, LOOKBACK_ROWS),
		as_dict=True,
	)

	if not rows:
		return 0.0

	if supplier:
		for row in rows:
			if row.supplier == supplier:
				return _clean(row.rate_per_kg)

	return _clean(rows[0].rate_per_kg)


def _clean(value) -> float:
	return round_half_up(frappe.utils.flt(value), 4)
