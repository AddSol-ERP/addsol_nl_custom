# addsol_nl_custom project memory

## Scope and architecture

Frappe v15 app for N L Electromech. Plate handling is opt-in and is implemented
under `addsol_nl_custom/plates/`, with DocTypes, reports, client scripts, and
patches in the app package. The single Plate Settings document holds company
wide plate controls; item and Item Group metadata describe plate dimensions and
defaults. Keep ordinary ERPNext purchasing unaffected when plate purchasing is
disabled.

The React Purchase Receipt UI is in the separate `erpnext-ui` repository. It
uses the whitelisted methods in `plates/api.py` to read whether the feature is
enabled, check whether an item is weight managed, and determine whether the
current user can decide a weight variance. Server-side validation remains the
source of truth.

## Weight and purchasing rules

- Weight formulas are limited to `L`, `W`, `T`, and `MF`; `custom_formula` is
  not a valid variable inside a weight formula.
- An Item Group is a weighed grade only when `Item Group.custom_is_weighed_grade`
  is ticked. A Formula alone does not make one, because that made every graded
  Item demand a rate per kg. The flag gates all plate behaviour, so an unticked
  grade is an ordinary group.
- The rate per kg is entered on the Purchase Order line and nothing overwrites
  it. `plates/rate_history.py` offers the last submitted rate for that item
  (preferring this supplier, falling back to any) purely to fill an empty line.
  A receipt is priced at the order's rate; its field is read-only.
- There is no supplier price list. `Supplier Grade Rate` was removed along with
  the per-supplier validity windows; it tied the price to the supplier's record
  and overwrote the buyer's figure on every items-grid change.
- Keep weight tolerance, over-billing allowance, approval roles, cutting
  operation, and offcut settings in Plate Settings unless the data is truly an
  item-specific property.
- API lookups that control UI behavior must not expose data to guests. The
  backend must still enforce item eligibility, permissions, tolerance, and
  approval decisions when documents are saved or submitted.
- `tools/generate_plate_custom_fields.py` is the source of truth for the plate
  Custom Fields. Edit it and re-run it; never hand-edit `custom_field.json`.
  Removing a row is not enough to drop a field, because the generator carries
  unmanaged fields over from the existing fixture - the `REMOVED` set is what
  actually deletes one.

## Script Reports

`Plate Stock Register` and `Plate Receipt Weight Variance` have Python
implementations beside their report JSON. Their Report records must be standard
(`is_standard: "Yes"`) so Frappe imports the module's `execute()` function.
Otherwise Frappe treats them as custom script reports and tries to compile the
database `report_script`; an empty value raises `TypeError: Not allowed source
type: "NoneType"`.

The migration `mark_plate_reports_standard` updates existing Report records as
well as the JSON definitions. It is listed in `patches.txt`; after deployment,
run `bench migrate` for the target site.

## Migrations and validation

- Patch order is declared in `patches.txt`, split into `pre_model_sync` and
  `post_model_sync`. Keep patches idempotent and guard optional records.
- `ensure_plate_child_table_columns` must use APIs available in the installed
  Frappe v15 database adapter. `MariaDBDatabase.add_column` is not available;
  use supported schema helpers / column checks.
- Run `ruff check addsol_nl_custom` and relevant app tests from the bench when
  available. Validate changed JSON fixtures and inspect the generated migration
  effects before deployment.

## Recent report fix (2026-10-15)

The report traceback on `query-report/Plate Stock Register` came from both plate
Script Reports being marked non-standard while their Python `execute()` methods
lived only in app modules. Both report JSON files now mark them standard, and a
post-model-sync patch upgrades existing database records. The fix was pushed to
`main` in commits `19f6746` and `e0f0789`; the latter includes the plate API
capability response used by the React receipt UI.

## Blank rows in Plate Stock Register (2026-10-15)

Commit `8212e08`. Two causes, neither in the report:

- `receipt_meta` gated the whole stamp on `row.custom_is_plate`, which is set
  from the Item Group being weighed, so a line carrying a heat number was
  skipped and the number went nowhere without a message.
- cost per kg was read only from `custom_rate_per_kg`, which `purchase.py` only
  writes when weight-based purchasing is enabled - so with the flag off, as it
  correctly is before go-live, stock value and value per kg were always blank.

Heat number and MTC are now stamped whatever the item's grade says, and weight
and cost per kg are derived from the line's own rate. `update_batch` skips
values it does not have instead of writing zeros, and every "nothing stamped"
path prints a reason. `backfill_batch_metadata` re-stamps receipts already
submitted, because the live hook only runs on submit.
