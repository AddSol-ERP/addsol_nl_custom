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
- The hand-tuned fields (`custom_formula`, `custom_multiplication_factor`, the
  batch and serial series on Item Group) are the exception: they live only in
  `custom_field.json` and the generator carries them over untouched, so editing
  them there is the way. `Item Group.custom_formula` is a Select whose options
  must list every financial formula the weight engine accepts - Frappe checks
  Select options before the engine sees a value. The four formulas are asserted
  in `tests/test_schema.py::test_the_weight_formula_in_particular`.
- Fixture import (`sync_fixtures` via `import_file_by_path`) always runs with
  force=True, after the patch phases of a migrate. The fixture is therefore
  the source of truth for any record it ships, and a patch that edits such a
  record is overwritten again moments later. `MPO Format` carries its two
  plate columns in `print_format.json` for exactly this reason;
  `add_plate_columns_to_mpo_format` is the backstop for layouts that are not
  the shipped one.
- `frappe.modules.patch_handler.run_single` sets `conf.developer_mode = 0`
  and never restores it, so anything after a patch - notably the fixture
  import - dies on standard DocType fixtures with "Not in Developer Mode!".
  Every patch is wrapped in `@with_developer_mode_restored` from
  `addsol_nl_custom/patches/__init__.py`.

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

## Installation and site setup (2026-10-16)

- A fixture must not ship a default for a Link into master data. The old
  `plate_settings.json` default of "MS Scrap" on `scrap_item` made
  `bench install-app` fail in `init_singles` with "Could not find Scrap
  Item: MS Scrap" - install-app never runs patches, it marks them complete.
  `setup_plate_defaults` creates the Scrap group, the MS Scrap Item and the
  Plate Settings pointers; it runs as a post_model_sync patch on migrate and
  through the `after_sync` hook at the end of install-app, the only hook that
  runs after fixtures on that path.
- `MPO Format` ships its two plate columns in `fixtures/print_format.json`
  (the fixture import always runs force=True, after the patch phases of a
  migrate, so the fixture is the source of truth); the
  `add_plate_columns_to_mpo_format` patch is only the backstop for layouts
  that are not the shipped one.
- `patch_handler` leaves `conf.developer_mode = 0`, which kills the fixture
  import that follows it ("Not in Developer Mode!" on standard fixtures);
  every patch is wrapped in `@with_developer_mode_restored` from
  `addsol_nl_custom/patches/__init__.py`.
- `custom_formula` is a hand-tuned Select on Item Group (in the generator's
  `hand_tuned` set): its four financial formulas live only in
  `custom_field.json`, are asserted in
  `tests/test_schema.py::test_the_weight_formula_in_particular`, and are
  added by editing the fixture directly.
- **Custom DocPerm replaces a doctype's entire permission set.** Frappe
  ignores the standard DocPerm rows the moment any Custom DocPerm row exists
  for that doctype (`Meta.set_custom_permissions` swaps the whole list), so
  adding one row for a new role wipes read/write/create for every existing
  role unless the standard rows are copied first. The Role Permissions
  Manager does this via `frappe.permissions.setup_custom_perms`; always do
  the same. An earlier version of `create_approver_permission` skipped the
  copy and took away everyone's Purchase Receipt permissions -
  `fix_purchase_receipt_custom_perms` repairs sites that ran it, and
  `tests/test_purchase_receipt_permissions.py` pins both halves.

## Running the tests (2026-10-16)

`bench --site <site> run-tests --app addsol_nl_custom` (the site needs
`allow_tests: true` while running; set it back afterwards). The suite:

- Rolls the database back per class, not per test (FrappeTestCase), so
  `TestPlateItem` and `RateTestBase` both do
  `self.addCleanup(frappe.db.rollback)` in setUp.
- Stamps test Items with HSN 999999 through `hsn_for_tests()` in
  `tests/test_item.py`: India Compliance makes HSN mandatory on sales Items,
  and the code must exist in the GST HSN Code master because the Item
  validate reads that record's taxes back.
- Never patches `frappe.msgprint` merely to silence messages:
  `frappe.throw` raises through msgprint, so the patch would swallow the
  throw too - it quietly produced a 0 kg weight instead of leaving the old
  one standing. Capture only where a message is asserted, via a lambda that
  accepts keyword arguments.
- Has `make_order` in `tests/test_rate_history.py` stand down
  `addsol_devoltrans_custom`'s MR-origin hook during insert (that app
  requires every Purchase Order row to originate from an approved Material
  Request and tests that rule itself) and fill `schedule_date`, which
  ERPNext requires on every order row.
- Gives the BOM in `test_b4_locks_the_dimensions_once_the_item_is_used` a
  Project: BOM.project is mandatory here (a Property Setter), and a Project
  names itself from its naming series.
- Asserts on `price_list_rate` beside `rate` in the PO pricing test; the
  per-plate weight is a receipt figure (`custom_weight_per_plate_kg` is not
  a Purchase Order Item field), on an order the piece weight is
  `custom_unit_weight_kg` set by `set_po_weights`.
- `RateTestBase.setUp` writes `Plate Settings.enable_weight_based_purchasing
  = 0` itself: two tests save an order with no rate per kg, which the
  enabled hooks refuse by design, and the suite must not depend on the
  site's own choice of that switch. The per-test rollback undoes the write.
