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
- Keep weight tolerance, over-billing allowance, approval roles, and the
  offcut settings (minimum cut size, offcut batch series, scrap Item) in
  Plate Settings unless the data is truly an item-specific property.
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

## Weight not recorded on receipt serials (2026-10-17)

`plates/receipt_meta.py` (uncommitted). Symptom: the weight never got recorded
for each plate - `custom_weight_kg` on a receipt's Serial Nos stayed empty.

`apply_receipt_metadata` runs on `Purchase Receipt.on_submit`, and Frappe runs
the controller's `on_submit` before any `doc_events` hook. The Serial and Batch
Bundle is created inside that controller lifecycle with `do_not_submit=True`,
and its entries were not always visible when the hook fired, so
`get_bundle_entries` returned `[]` and `stamp_row` bailed out with a print. The
live log recorded exactly this for PR-26-00011 (rows 1-3) and PR-26-00012 (row
1): "no serial/batch bundle, nothing stamped." Those receipts are not explained
by the backfill patch either - `backfill_batch_metadata` ran at 12:39 that day,
before both of them - so only the new post-commit pass below could have repaired
them, and it did (their serials and batches now carry the weight, heat number,
grade and cost).

Two changes, both in `receipt_meta.py`:

- `stamp_row` no longer returns when the bundle carries serials but no batch.
  The batch is written only `if batch_nos`; the serials are always stamped and
  the line prints "no batch produced; stamping serials only" instead of
  discarding everything. The old `if not batch_nos: return` meant a serial-only
  line got weight nowhere.
- `apply_receipt_metadata` stamps every row that is `custom_is_plate` or
  carries `custom_heat_number`/`custom_mtc_no`, and if at least one row
  qualified it enqueues `stamp_submitted_receipt(receipt_name)` with
  `enqueue_after_commit=True, queue="short"`. That pass re-reads the receipt
  but only while `docstatus == 1`, and stamps it again against the committed
  bundle entries. Both writers use `db.set_value(..., update_modified=False)`,
  so the second pass overwrites the same values without aging the document and
  running twice is harmless.

Keeping the trap straight for the next edit:

- The enqueue is guarded by `not frappe.flags.in_test`, so the re-stamp never
  fires in a test run; `tests/test_receipt_meta.py` calls `stamp_row` and
  `stamp_submitted_receipt` directly instead. That suite pins the bug - the
  no-batch test fails on the previous code with `0.0 != 250.0`.
- The pass depends on the `short` queue worker being up. If it is down, only
  the immediate pass runs, and `backfill_batch_metadata` is the manual backstop
  for receipts that slipped through. Both reasons it can miss are printed, never
  raised.
- Do not turn those prints into a `frappe.throw`. An intermediate version did,
  rejected PR-26-00014 with "ERPNext created no serial-and-batch bundle", and
  blocked the submit. The hook must stay non-blocking; retrying after commit is
  the guarantee, not failing the receipt.

## Plate Offcut replaces the Work Order cutting flow (2026-10-17, cutting model reworked 2026-10-20)

The Work Order/Job Card coupled flow is gone, deleted outright (clean
cutover, no data preserved): `Plate Cutting Record`, `Plate Cutting Offcut`,
`plates/offcut_stock.py`, the Job Card and cutting-record client scripts and
their tests were removed; `cutting_operation`/`offcut_warehouse` were dropped
from Plate Settings; and `patches/v1_0/remove_plate_cutting_flow.py`
(post_model_sync, idempotent, developer-mode restored) deletes the old Custom
Fields, drops both tables and removes the DocType records on existing sites.

Its replacement is the submittable `Plate Offcut` DocType
(`format:OFC-{YY}-{#####}` -> `OFC-26-00045`, Manufacturing User/Manager),
entered from its own list, a
Create Offcut button on Serial No, or the same button on Item. The operator
always provides the offcut dimensions; what the offcuts and the scrap do not
take is one remainder piece, and only the weight actually cut for the order
becomes its cost. One cutting is made for one order, so the Project is
mandatory on every Plate Offcut:

- **validate** reads the plate through `cutting.get_offcut_details` (Active,
  weighed, in a warehouse - a serial with no warehouse throws, because a
  Repack row without `s_warehouse` is an inbound row), insists on a Project
  (`check_project`, so an API or an import cannot slip past the form's
  mandatory), checks each cut fits the plate and meets the Item Group
  minimums, recomputes every row, then runs `compute_totals`, which derives
  `consumed_weight_kg = source - offcuts - scrap` and refuses an overage
  beyond `OVERAGE_TOLERANCE`. **Scrap is now an input**, not a computed
  balance: `scrap_weight_kg` defaults to 0 and is what the operator books
  as waste; a negative value is refused, and zero scrap needs no scrap Item
  at all. The removed `auto_scrap_weight` used to fill this field as the
  remainder, which is no longer what the field means.
- **on_submit** (`create_offcut_stock`) reuses or creates one Item per cut
  piece, creates one Batch per piece (`offcut_batch_series`, heat/MTC/
  grade/ratio/cost stamped - grade read from the Item's `item_group`, never
  the batch label), reserves a Serial No per piece, inserts AND submits a
  **Repack** Stock Entry in one go, and - when anything is left after the
  offcuts and the scrap - creates the remainder piece and submits a second
  Stock Entry, a **Material Issue**, that spends it against the Project.
  Finally it stamps `custom_weight_kg` and `custom_source_serial_no` onto
  every new serial.
- Offcuts may be **rectangles or circles**. A rectangle keeps the name
  `<Item Group>-<T>x<L>x<W>`; a circle is entered by diameter, is named
  `<Item Group>-<T>-D<d>`, and weighs what the square across it weighs
  times pi/4 (`theoretical_offcut_weight`, applied before the batch's
  actual-to-theoretical ratio). The two shapes can never collide on an
  Item name, and `check_circle_fits` refuses a diameter that is wider than
  either side of the plate.
- The **remainder piece** is one Item per piece, never reused, named
  `<Item Group>-<T>-<Project>-<Running No>` from the Plate Settings series
  `remainder_naming_series` (default `RMD-.{project}.-.#####`). The running
  number counts per Project (`next_remainder_running_no`), so two cuttings
  for one order read `-00001`, `-00002`, and another order starts again at
  `-00001`. The piece gets its own Batch and Serial, points back at the
  plate it was cut from, and stays plate stock - the Item carries
  `custom_is_remainder` and `custom_remainder_project` but **not**
  `custom_is_offcut`, so the Plate Stock Register keeps listing it as stock.
- The Repack takes the plate out of its own warehouse and puts offcuts, the
  remainder and the scrap back **into the same warehouse**; full serial
  consumption, qty 1 per piece. Destination rows set
  `set_basic_rate_manually=1` with **both** `basic_rate` and
  `basic_amount`: `set_basic_rate` skips manual rows so `basic_amount`
  would stay 0, and `validate_repack_entry` refuses a Repack with more than
  one finished item unless every row is manual. The remainder row is priced
  at the consumed value, so the Material Issue that follows spends exactly
  that. No work order, no BOM, no header/target warehouses, no
  `fg_completed_qty`.
- The **Material Issue** carries the Project on its row, which is what puts
  the consumed value on the order in the general ledger; it uses the same
  legacy `use_serial_batch_fields` pattern as the Repack, so
  `make_bundle_using_old_serial_batch_fields` turns it into a Serial and
  Batch Bundle on submit. When the offcuts take the whole plate there is no
  remainder, no issue, and the Repack is just plate out plus pieces in.
- `cutting.insert_piece_item` is the one place that puts a piece Item into
  stock, and `item_autoname`/`item_validate` skip cutting-generated Items
  (`is_cutting_generated` = `custom_is_offcut` or `custom_is_remainder`):
  they already carry their final name and their size is weightless, so the
  ordinary rectangle naming and weight maths must not claim them.
- **Frappe runs `db_update()` + `update_children()` before `on_submit`** -
  anything decided while submitting (the stock_entry name, the
  material_issue name, batch/serial names, offcut_item, remainder_item)
  must be written explicitly with `self.db_update()` / `row.db_update()` or
  it exists only in memory. The old flow had exactly this latent bug.
- **on_cancel** cancels the Material Issue first - while it stood the
  remainder serial was out of stock and the Repack could not have taken it
  back - then the Repack (ERPNext's own refusal to cancel once an offcut
  serial has moved stays in force), force-deletes the piece Batches and
  blanks each row's `serial_no`/`batch_no` plus the remainder fields, so an
  amend/resubmit reserves fresh names instead of tripping over the cancelled
  attempt's inactive serials.
- `plates/api.py:estimate_offcut_weights(source_serial_no, rows,
  scrap_weight_kg=None)` powers the live preview in
  `public/js/plate_offcut.js` (debounced, scrap included, `allow_guest=False`
  plus an explicit
  `has_permission("Plate Offcut", "write", throw=True)`, row names echoed
  back). It reports the scrap and the consumed weight and value alongside
  the offcuts, so the operator sees the order's cost before saving. A line
  still being drawn (a rectangle with no width, a circle with no diameter)
  returns zeroes rather than asking for the weight of a zero-size plate,
  which the formula refuses to guess. The generated Stock Entries are an
  implementation detail (`flags.ignore_permissions`); the permission gate is
  submitting the Plate Offcut itself.
- `tests/test_plate_offcut.py` covers submit end to end - Repack shape,
  manual rates, serial/batch traceability, scrap as input, circles, the
  remainder Item/serial/batch, the Material Issue against the Project, the
  per-Project running numbers, cancel (Material Issue then Repack), amend -
  and `tests/test_cutting_estimate.py` pins the preview against the real
  post-insert totals.

Traps that carried over into the new flow:

- The grade the weight maths needs is the **Item's `item_group`**, never
  `get_offcut_details()["grade"]` (the Batch's `custom_grade` label).
- Grid events do not dispatch where their names suggest: `offcuts_add`,
  `offcuts_remove` and every row-field event fire under the **child**
  doctype, so `frappe.ui.form.on("Plate Offcut Item", ...)` holds them;
  registering them on the parent silently does nothing. `clear_doc` drops a
  deleted row before `offcuts_remove` fires, so re-requesting after a delete
  cannot leave a stale weight standing in the total. Rows are matched back
  by the `name` the server echoes, and `estimate_seq` discards replies that
  arrive out of order.
- A DocType's `autoname: "format:..."` expands **braced** params only in
  this Frappe version (`format:OFC-{YY}-{#####}`; `_format_autoname` regexes
  `{...}` and leaves anything else verbatim). The dot syntax (`OFB-.YY.-
  .#####`) belongs to `make_autoname`/naming series: passing
  `format:OFC-.YY.-.#####` silently names every document with the literal
  series string, and the second insert dies on a duplicate key - only tests
  that insert twice ever notice. `make_autoname(series, doc=...)` needs the
  **dict** about to be inserted, not a doctype name string:
  `parse_naming_series` calls `doc.get()` on every literal series part, so
  `OFB-.YY.-.#####` dies on "OFB" when handed a string. Both
  `make_offcut_batch` and `cutting.reserve_serial_no` pass their dict (the
  first production submit of the old flow crashed exactly here). The
  remainder naming series uses the same mechanism: `make_autoname(series,
  doc={"project": project})` with the default `RMD-.{project}.-.#####`.
  `parse_naming_series` splits the template on `.`, so `{project}` must be a
  **whole** dot-separated part, and the running number is the digits the
  expanded name ends with (`re.search(r"\d+$", ...)`).
- **`get_setting` must treat a blank Single value as unset, not as a choice.**
  `frappe.db.get_single_value` returns `''` — never `None` — for a Single
  DocType field nobody has saved yet. The old guard tested only `is not None`,
  so a field shipped with a `default` in its DocType JSON silently resolved to
  `''` on any site that had not opened the form. `remainder_naming_series` was
  blank that way, `make_autoname('')` minted bare numbers under the **empty**
  series key `''`, and every Project drew from one global counter — the two
  running-number tests (`-00001`) failed because an earlier test had advanced
  that shared counter. `settings.py:get_setting` now falls through to the
  default when the stored value is blank; an empty string is never meaningful
  for these settings.
- **`tabSeries` counters survive a test rollback.** Even with the naming fixed,
  a per-project remainder number is a row in `tabSeries`, so a Project reused by
  name across tests inherits whatever counter an earlier test or run left, and
  the first piece is no longer `-00001`. Worse, a Project's own autoname counter
  IS rolled back, so every test re-collides on the same Project name and hence
  the same series key. `tests/test_cutting_estimate.py:make_project` deletes the
  project's Series row on each call to make the starting number deterministic; a
  test that asserts an absolute running number must reset it first.
- **A form field filled only by the live preview never reaches a submitted
  document.** `source_plate_text` (the Item + Batch spelled out under the serial)
  is written two ways: `set_source` on save, and the JS estimate reply while the
  form is open. The JS path bails on `frm.doc.docstatus`, so a submitted cutting
  shows only what its own save stored — and cuttings filed before the field
  existed stored nothing. Filling such a field needs a backfill patch, and it
  **cannot reuse `get_source_details`**: that reader throws on a non-Active
  serial, and a submitted cutting's plate is by then `Consumed`. Hence
  `cutting.plate_text_for` — the formatting is split out so the live reader and
  the patch (`patches/v1_0/backfill_offcut_plate_text.py`) spell a plate
  identically while the patch reads the Serial No directly.
- Cutting-generated Items are exempt from the ordinary Item naming and
  weight rules via `is_cutting_generated` (`custom_is_offcut` or
  `custom_is_remainder`) in `item_hooks.py`. Without it `item_autoname`
  renames the remainder Item to the rectangle name and `item_validate`
  fails the weight maths on a piece that has no L/W. They still get
  `apply_plate_item_defaults` (batch + serial series).
- Legacy `use_serial_batch_fields` works for a **Material Issue** exactly as
  it does for the Repack: `stock_controller.make_bundle_using_old_serial_batch_fields`
  runs on submit and turns the row's `serial_no`/`batch_no` into a Serial and
  Batch Bundle, so the automatic issue needs no bundle of its own.
- **An accounting-dimension row must belong to the Stock Entry's company.**
  Carrying `project` on the Material Issue row makes ERPNext run
  `accounts_controller.validate_company_in_accounting_dimension`, which throws
  "Project: X does not belong to the Company: Y" when the Project's `company`
  differs from the warehouse's. `check_project` now catches it at validate
  with a plain message; a test helper that builds a Project must set
  `company` explicitly (`make_project` pins it, and repairs a leftover that
  carries another company's default).
- The child `shape` column arrives empty on rows cut before circles existed;
  `cutting.is_circle` reads blank as Rectangle, and the post-model-sync
  `backfill_offcut_shape` patch stamps those rows explicitly so nothing has
  to rely on the fallback. It is post- not pre-model-sync because the column
  is created by the DocType sync that runs first.
- `length_mm`/`width_mm` on Plate Offcut Item lost their `reqd` when circles
  arrived (a circle has neither): they are now `mandatory_depends_on` per
  shape, which is only a form convenience. The server must keep enforcing it
  through `check_offcut_fits`/`check_circle_fits`, because an API or an
  import never sees the desk's conditional mandatory.
- A DocType JSON edit reaches a site only through `bench migrate` (Frappe
  compares the file hash against `tabDocType.migration_hash`, not its
  `modified` stamp); `.py` and `hooks.py` edits need a `bench restart`,
  because gunicorn runs with `--preload` and caches controllers in
  `sys.modules`.

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

## Declared-field incidents (2026-10-16)

- The old `plates/offcut_stock.py` shipped field-incomplete: it selected and
  stamped `Stock Entry Detail.custom_cutting_record` and db_set
  `Plate Cutting Record.stock_entry`, but neither field existed in the
  fixture nor in a DocType JSON, so the first submitted Manufacture
  (`MAT-STE-00008`) died with "Unknown column 'custom_cutting_record' in
  'SELECT'". The old flow is gone; the DocType-owned field the new flow
  writes is `Plate Offcut.stock_entry`.
- The trap is that a missing Custom Field and a missing DocType-owned field
  fail the same way, at runtime, on the first real document, and only the
  custom_% half is visible to a fixture-wide check.
  `tests/test_schema.py::TestFieldsWeUseAreDeclared` now AST-scans every
  string literal in the app for `custom_*` names and asserts each is declared
  in the fixture or a shipped DocType JSON, plus pins `stock_entry` on
  Plate Offcut; `tests/test_plate_offcut.py` exercises it live.

## Purchase Order item layout (2026-10-18)

`patches/v1_0/setup_purchase_order_item_layout.py` runs from both `after_sync`
(fresh install) and `after_migrate` (regular migrations) to put the Quantity
and Rate block, including conditional Plate Details, before Description. It
builds the Property Setter's full `field_order` from live metadata and moves
the blocks without assuming a fixed ERPNext field list. Plate Custom Fields
remain sourced from `tools/generate_plate_custom_fields.py`; Rate per Kg is
editable in the expanded row, not shown as an always-visible grid column.
