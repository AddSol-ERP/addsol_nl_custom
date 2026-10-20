"""Remove the Custom Field record the attachments field left behind under a wrong name.

Frappe names a Custom Field `<DocType>-<fieldname>`, and `sync_fixtures`
matches on that name. The three `custom_document_attachments` records were
shipped with one identical name instead, so only the last of them could ever
be on a site: the others collided with it and died with "A field with the
name custom_document_attachments already exists".

They are named the way Frappe names them now, which leaves the wrongly named
record on every site that ran the old fixture as an orphan.
`sync_fixtures` cannot update it - the name does not match - and it cannot
be re-created either, because the fieldname is already on the DocType:

    "A field with the name custom_document_attachments already exists in
    Stock Entry"

The orphan is removed here, before the fixture import, and the fixture puts
the three fields back properly - on the same fieldnames, so the panel and
anything that reads it are unaffected. The column is not dropped: Frappe only
adds columns when a table is synced, and the field holds a rendering of the
File records rather than anything of its own.

Idempotent: a site with no orphan is left alone.
"""

import frappe

from addsol_nl_custom.patches import with_developer_mode_restored

# The field the attachments panel puts on each of its DocTypes.
ATTACHMENTS_FIELD = "custom_document_attachments"


@with_developer_mode_restored
def execute():
	for record in orphaned_records():
		frappe.delete_doc("Custom Field", record.name, force=True, ignore_missing=True)
		print(f"Deleted orphaned Custom Field: {record.name} (on {record.dt})")


def orphaned_records():
	"""The records this app shipped under a name Frappe would never use.

	Frappe names a Custom Field `<DocType>-<fieldname>`, so a record whose
	name is anything else was never made by Frappe: it is a leftover of a
	hand-written fixture, and it can only ever block the record that
	replaces it.
	"""
	records = frappe.get_all(
		"Custom Field",
		filters={"fieldname": ATTACHMENTS_FIELD},
		fields=["name", "dt", "fieldname"],
	)

	return [record for record in records if record.name != f"{record.dt}-{record.fieldname}"]
