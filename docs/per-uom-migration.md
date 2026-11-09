# Retiring per-Kg purchasing

ERP UI owns all new commercial pricing through UI Uom Pricing Rule. This app
retains physical plate weights, heat/MTC traceability, and cutting metadata.
Legacy monetary columns are hidden/read-only, rather than dropped.

Deploy ERP UI first and run its migration so generic pricing columns exist.
Enable UOM pricing and buying pricing before retiring an enabled legacy workflow.
Existing enabled Item Group rules are retained. Previously weighed groups without
an enabled rule receive a Direct Entry Kg rule; review these groups in the preview
and configure their intended future pricing before entering new documents.

On a backed-up QA copy, preview the conversion before migrating this app:

```sh
bench --site <qa-site> execute addsol_nl_custom.addsol_nl_custom.plates.legacy_pricing_migration.run
```

The preview reports transaction/serial/batch counts, groups needing rules, and
conflicts. Resolve every conflict, then run `bench --site <qa-site> migrate`.
The registered post-model-sync patch applies the conversion. It never saves or
resubmits purchasing documents and never changes rates, amounts, taxes, stock
quantities, or accounting/stock ledger entries. A rerun skips existing snapshots.
No explicit database commit is issued by the patch.

Historical rows retain their agreed Kg rate and booked amount in generic metadata.
If a stored weight disagrees with rate × amount, migration stops before writing.
Missing weights may be recovered from the booked amount / agreed rate. Otherwise
measurement must be corrected explicitly. Existing generic snapshots always win.

Partial receipts/invoices linked to historical contracts retain Kg pricing even
when the Item's current rule uses another UOM. A copied source measurement is
prorated to the partial quantity; an explicitly entered measurement is retained.
Returns retain their original metadata. New standalone rows use current rules.

Historical serials receive frozen per-piece Kg snapshots, including offcuts and
remainders. Missing measurements on active stock block conversion. Non-Nos active
plate serials require explicit review. Mixed-measurement batches use their serial
snapshots; a single batch average is not guessed. Existing snapshots are untouched.
Cutting requires a snapshot, with source cost resolved from current stock valuation.

QA acceptance: compare PO/PR/PI totals and stock/account balances before and after;
receive part of an old Kg PO after changing the Item's live pricing UOM; invoice
that receipt; test a new standalone order with the current rule; reverse an old
receipt; cut an old whole plate and an old offcut; rerun the preview to check no
remaining transaction/serial conversions. Heat-number requirements move to the
independent Plate Settings option and remain enabled on previously enabled sites.

PO prints use one compact Dimensions column with configured parameter symbols and
units (`L 2 m × W 1250 mm × T 10 mm`). ERP UI's dimensions patch backfills the
builder display from existing snapshots; the NL retirement migration fills it for
converted rows. Missing historical units are left unspecified, never inferred
from today's Item or pricing rule. New snapshots retain Item parameter unit
overrides. ERP UI must be migrated before these print fixtures are imported.

Missing whole-plate serial weights can be recovered from one verified submitted
Purchase Receipt bundle. Every stock unit must have a distinct matching serial
entry with quantity 1, and the historical Kg rate/amount must reconcile. The
receipt's accepted line weight is allocated over its stock quantity, matching
receipt stamping; this is not an individual physical measurement. The preview
reports `recovered_serial_weights` with receipt and row identifiers. Only absent
serial weights are repaired; existing weights/snapshots, stock quantities and
accounting amounts remain unchanged. Offcuts/remainders, ambiguous receipts,
returns, mismatched bundles and missing source records still require review.
