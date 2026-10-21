#!/usr/bin/env python3
"""Regenerate the plate Property Setters in fixtures/property_setter.json.

Run from the app directory:

    python3 ../../../tools/generate_plate_property_setters.py

This produces precision 6 on the money fields of the buying item tables, so
that amount = quantity x rate lands within a few paise of accepted weight x
rate per kg (Part C7). The Supplier Quotation Item is in the list for the
same reason: a quotation prices a plate line by weight, and the Purchase
Order built from it prices the same line the same way, so the two documents
have to carry the same precision or they drift apart by a paisa or two.

Field order is deliberately NOT produced here. A field_order Property Setter
replaces the DocType's entire field order, so one built from a guess would hide
every standard column on the form. The patch v1_0/set_plate_field_order reads
the live metadata instead and appends to whatever is already there.

Anything already in the file that this tool does not own is kept untouched.
"""

import json
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(APP_DIR, "addsol_nl_custom", "fixtures", "property_setter.json")

# Money fields that need enough decimal places for amount = qty x rate.
PRECISION_6_DOCTYPES = [
	"Purchase Order Item",
	"Purchase Receipt Item",
	"Purchase Invoice Item",
	"Supplier Quotation Item",
]
PRECISION_6_FIELDS = ["rate", "base_rate", "net_rate", "base_net_rate", "price_list_rate"]

# The field order of these DocTypes belongs to the layout patches, which
# rebuild it from the live metadata on every migrate. A field_order Property
# Setter freezes the layout, and a frozen order overrides insert_after, so
# this app never ships one - it lets the patch own it.
#
# The export picks the site's runtime setters up, which would put one in the
# fixture and freeze the layout on the next migrate, so they are dropped
# here rather than carried over.
LAYOUT_DOCTYPES = ["Purchase Order Item", "Supplier Quotation Item"]

MODIFIED = "2026-10-14 00:00:00.000000"


def make(doc_type, field_name, prop, value, prop_type):
	return {
		"doctype": "Property Setter",
		"doc_type": doc_type,
		"doctype_or_field": "DocField" if field_name else "DocType",
		"field_name": field_name,
		"property": prop,
		"value": value,
		"property_type": prop_type,
		"name": f"{doc_type}-{field_name or 'main'}-{prop}",
		"modified": MODIFIED,
	}


def owned(prop, field_name):
	"""Is this Property Setter one this tool generates?"""
	return (
		field_name is not None
		and prop == "precision"
		and field_name in PRECISION_6_FIELDS
	)


def is_a_layout_setter(record):
	"""Is this the field order a layout patch owns?

	See LAYOUT_DOCTYPES: the patch rebuilds it on every migrate, so shipping
	one in the fixture would freeze the layout.
	"""
	return record.get("property") == "field_order" and record.get("doc_type") in LAYOUT_DOCTYPES


def main():
	with open(FIXTURE) as f:
		existing = json.load(f)

	kept = [
		p
		for p in existing
		if not owned(p.get("property"), p.get("field_name")) and not is_a_layout_setter(p)
	]

	for doc_type in PRECISION_6_DOCTYPES:
		for field_name in PRECISION_6_FIELDS:
			kept.append(make(doc_type, field_name, "precision", "6", "Int"))

	kept.sort(
		key=lambda p: (
			p.get("doc_type") or "",
			p.get("field_name") or "",
			p.get("property") or "",
		)
	)

	with open(FIXTURE, "w") as f:
		json.dump(kept, f, indent=1, ensure_ascii=False, sort_keys=True)
		f.write("\n")

	print(f"property_setter.json: {len(kept)} entries ({len(existing)} before)")


if __name__ == "__main__":
	main()
