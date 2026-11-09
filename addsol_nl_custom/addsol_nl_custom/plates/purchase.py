"""Physical plate classification only; ERP UI owns all monetary pricing."""

from addsol_nl_custom.addsol_nl_custom.plates.grouping import is_weighed_item


def mark_plate_rows(doc, method=None):
	for row in doc.get("items") or []:
		row.custom_is_plate = int(is_weighed_item(row.get("item_code")))
