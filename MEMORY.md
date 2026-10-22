# addsol_nl_custom project memory

## Scope and architecture

Frappe v15 app for N L Electromech. Plate handling is opt-in and is implemented
under `addsol_nl_custom/plates/`, with DocTypes, reports, client scripts, and
patches in the app package. The single Plate Settings document holds company
wide plate controls; item and Item Group metadata describe plate dimensions and
defaults. Keep ordinary ERPNext purchasing unaffected when plate purchasing is
disabled.

Finished goods are the other half of the app: an Item in the Item Group named
`Finished Goods` is named from its Project (`<Project>-00001`) and may only be
sold against that Project. That rule lives under
`addsol_nl_custom/finished_goods/`, not under `plates/`.

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

`Plate Stock Register`, `Plate Offcut Register` and `Plate Receipt Weight
Variance` have Python implementations beside their report JSON. Their Report
records must be standard (`is_standard: "Yes"`) so Frappe imports the module's
`execute()` function.
Otherwise Frappe treats them as custom script reports and tries to compile the
database `report_script`; an empty value raises `TypeError: Not allowed source
type: "NoneType"`.

The migration `mark_plate_reports_standard` updates existing Report records as
well as the JSON definitions. It is listed in `patches.txt`; after deployment,
run `bench migrate` for the target site.

`add_plate_offcut_register` creates the `Plate Offcut Register` record on sites
that predate it, and `drop_include_offcuts_filter` removes the filter the
plate register used to carry. Both are idempotent, and both need a `bench
migrate` on the target site.

## The plate register and the offcut register are two populations (2026-10-22)

`Plate Stock Register` holds WHOLE PLATES and the remainder a cutting leaves
behind. `Plate Offcut Register` holds the PIECES a cutting produced. They were
one report until this change: the plate register had an `include_offcuts`
checkbox, ON by default, so offcut rows sat in the plate figures and the only
thing distinguishing them was a flag nobody was looking at.

- **One report per population.** No figure is ever counted in two places, and
  each register answers one question: how much plate do we hold, and how much
  offcut do we hold.
- **The offcut set is the `Plate Offcut Item` child rows, not a flag.** The
  offcut register INNER JOINs `tabPlate Offcut Item` on the serial number,
  which is the authoritative "this piece was produced by a cutting" set. The
  remainder piece has no such row, so it cannot leak in.
- **The plate register excludes offcuts in SQL**, with
  `coalesce(i.custom_is_offcut, 0) = 0`. `custom_is_offcut` is a CHECK, so an
  Item that was never flagged carries NULL rather than 0 -- a plain `= 0` would
  drop every ordinary plate from the register.
- **The remainder stays plate stock.** `get_or_create_remainder_item` marks it
  `custom_is_remainder` and NOT `custom_is_offcut`, because a remainder IS
  plate stock: it is the piece of the plate the order keeps. It cannot be
  asserted as a row of the plate register, though -- the cutting issues it
  against the Project, so its serial is consumed and it is not stock by the
  time anyone reads a register. The rule is asserted on the Item.
- **Each offcut piece gets its OWN Batch** (`make_piece_batch` is called once
  per row), so grouping by the piece's own batch would give one row per piece,
  which is a list and not a register. The offcut register groups by the SOURCE
  batch (`Batch.custom_source_batch`, the plate it was cut from): one row per
  size, per warehouse, per heat. Two cuttings of one size from two plates are
  two rows, not one row with two pieces in it.
- **The value comes from the `Plate Offcut Item` row**, which holds what the
  Repack actually booked for that piece. The batch's cost per kg is the source
  plate's rate and every piece of a cutting shares it, so cost per kg times
  weight would reproduce it only approximately -- each piece is priced on its
  own measured weight. The booked value is the number the ledger holds.
- **`weight_per_piece` and `value_per_kg` are derived, never stored.** They are
  quotients of the two figures beside them, and a stored copy drifts the moment
  a piece's weight is corrected.
- **The SPA renders both reports from their own metadata.** The report key
  (`plate-stock-register`, `plate-offcut-register`) is all the SPA sends; the
  name and the owning app stay in `erpnext_ui`'s `SPA_CUSTOM_REPORTS`.

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
  `custom_unit_weight_kg` set by `set_line_weights`.
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
  string literal in the app for `custom_%` names and asserts each is declared
  in the fixture or a shipped DocType JSON, plus pins `stock_entry` on
  Plate Offcut; `tests/test_plate_offcut.py` exercises it live.
- **A Custom Field record's NAME matters as much as its fieldname.** Frappe
  names one `<DocType>-<fieldname>`, and `sync_fixtures` matches on that
  name. The three `custom_document_attachments` records shipped with one
  identical name, so only the last of them could ever be on a site, and
  every site that ran that fixture kept the wrongly named one as an
  ORPHAN - a record `sync_fixtures` can neither update (the name does not
  match) nor re-create (the fieldname is already on the DocType). The
  symptom on the next migrate was:
  "A field with the name custom_document_attachments already exists in
  Stock Entry". `patches/v1_0/remove_orphaned_custom_field_records.py`
  removes it before the fixture import, and the fixture puts the three
  fields back properly. `tests/test_orphaned_custom_fields.py` pins both
  halves: the orphan goes, a properly named record stays.

## Purchase Order item layout (2026-10-18)

`patches/v1_0/setup_purchase_order_item_layout.py` runs from both `after_sync`
(fresh install) and `after_migrate` (regular migrations) to put the Quantity
and Rate block, including conditional Plate Details, before Description. It
builds the Property Setter's full `field_order` from live metadata and moves
the blocks without assuming a fixed ERPNext field list. Plate Custom Fields
remain sourced from `tools/generate_plate_custom_fields.py`; Rate per Kg is
editable in the expanded row, not shown as an always-visible grid column.

The same layout is applied to the Supplier Quotation Item, by
`patches/v1_0/setup_supplier_quotation_item_layout.py`, which calls the
shared `apply_layout` in the module above. Two modules, not one: a patch is
run once and recorded in the patch log, so a change to an existing patch
would never reach a site that had already run it. A new module is the only
way to be a new migration step.

## Finished-goods item codes (2026-10-21)

A finished good is an Item in the Item Group named `Finished Goods`, or in any
Item Group nested under it. Its code is generated, never typed:

	<Item.custom_project>-<auto number>		W-0268-00001

The code lives in `addsol_nl_custom/addsol_nl_custom/finished_goods/`, which
is a package of its own - the plate rules are about a plate's size, these are
about a product the customer makes.

- The Project comes from `Item.custom_project`, a Link to Project. The field
  carries the customer's own name for it. `addsol_devoltrans_custom` ships a
  field of the same name on the Item master for the same purpose, but the two
  apps are not installed on the same site, so this is a naming choice and not
  a shared field.
- The number is counted per Project, in a `tabSeries` row keyed
  `<project>-`: `make_autoname("{project}.-.#####", doc={"project": ...})`.
  One Sales Order with three finished goods draws 00001, 00002, 00003; a
  second order on the same Project continues at 00004; another Project starts
  again at 00001. A number is used even if the Item it was minted for is
  later discarded - the same behaviour the remainder naming already has.
- The code is given once, when the Item is created, and never moves.
  Renaming an Item orphans the stock, the batches, the bills of materials
  and every document that quotes it, so changing the Project on an existing
  Item is reported, not acted on.
- A typed code is replaced by the generated one, and the typed text is kept
  as the `item_name`. Refusing it instead would break ERPNext's quick entry,
  where `item_code` IS the mandatory name field.
- The Sales Order may only book a finished good against that same Project
  (the row's project, else the order's). A finished good with no Project was
  made before the rule and is left alone.
- The group is created by `setup_finished_goods_group` if the site has none.
  A site without one has the rule switched off rather than broken.

Traps that cost a look:

- **`autoname` is not the last word on the name.** Frappe runs `validate`
  inside `run_before_save_methods` and `db_insert` after it, so a name set
  during `validate` is the name the row is stored under - and a rename done
  by another app during `autoname` is overridden by one done during
  `validate`. The code is therefore minted ONCE (in `autoname`, stashed on
  `doc.flags`, never written to the database) and re-asserted in `validate`.
  Minting twice would burn two numbers.
- **Any other app that renames Items would fight this rule.**
  `addsol_devoltrans_custom` renames Items to include the Project ID, but it
  is not installed on this site. The rule here is still written to survive one:
  the code is minted ONCE (in `autoname`, stashed on `doc.flags`, never
  written to the database) and re-asserted in `validate`, and
  `item_after_insert` compares the stored name with the minted one and says
  so when they differ. The Item is stored by then, so nothing is changed - but
  a finished good filed under a code this app did not mint is one the project
  reports will not find.
- **The plate rules and the finished-goods rules are told apart by the Item
  Group.** `plates.item_hooks.is_finished_good` makes the plate rule stand
  down, and the plate rule's "Item Name is required for items without
  thickness" throw would otherwise refuse every finished good whose name
  was left empty. The Item hooks are registered as a LIST in `hooks.py`, so
  both rules run.
- **A Project name has to be usable inside a code**: letters, digits, a dash
  and an underscore. A Project typed by hand as "Job #12" is refused with the
  reason, rather than silently stripped into a different code.
- **`groups.finished_good_groups()` is deliberately NOT cached.** The set is
  read from the whole Item Group table on every call. `frappe.local` survives
  from one test to the next, and a cached set would go stale inside a
  request that creates the group and then uses it - and across the test
  suite, where the group is created in `setUp`.

## Supplier Quotations price plates by weight (2026-10-21)

A plate line on a Supplier Quotation is priced by weight, exactly as a
Purchase Order line is, and the Purchase Order built from the quotation
inherits the price. The problem it answers: an order raised from a
quotation arrived with no rate per kg, so the buyer typed the price again
and the two documents could disagree about it.

The supplier can enter the rate per kg directly. If they enter only a
per-plate rate, the hook derives the equivalent rate per kg:

	rate per kg = entered rate per kg OR quoted rate per plate / kg per plate
	amount      = estimated weight x rate per kg
	rate        = amount / quantity

- `plates/purchase.py::sq_before_validate` is the hook, on
  `doc_events["Supplier Quotation"]["before_validate"]`. It marks the plate
  rows, applies the Purchase Order's UoM rule (a plate line is in Nos with a
  conversion factor of 1), works out the two weights, preserves an entered
  rate per kg (or derives one from the per-plate rate) and prices the line
  with the same `apply_amount` the order uses.
- **A price is OPTIONAL on a quotation.** A quote is often raised before the
  supplier has answered, so a line with no quoted rate is left alone rather
  than refused. The Purchase Order is where the price is demanded. This is
  the one place the quotation is more permissive than the order.
- The entered rate per kg is authoritative. If it is blank and a per-plate
  rate exists, the hook derives it from the known unit weight. The PO mapper
  carries the resulting rate per kg forward.
- **What the supplier quoted and what the weight pricing gives can differ by
  a paisa or two** - the rate per kg is stored at four decimals and a plate
  weighs a quarter of a tonne, so the bound is half a rupee per ten tonnes.
  The quotation and the Purchase Order agree EXACTLY, because they price the
  same weights with the same stored rate per kg. The Purchase Order Item's
  money fields are at precision 6 for the same reason, and the Supplier
  Quotation Item's are now too (`tools/generate_plate_property_setters.py`).
- **A discount on a plate line is cleared and folded into the rate**, the
  same as on the Purchase Order. The effective price is preserved; the
  document ends up in the same shape as an order line.
- **ERPNext's mapper copies the rate per kg across by name**
  (`frappe/model/mapper.py:161` copies every field the source and the target
  share), so no `field_map` entry is needed. The Purchase Order side needed
  no change at all.

Traps:

- The quotation's rate per kg is editable. Changing it previews the per-piece
  rate, amount, and estimated weight on the form; the server recomputes the
  same values on save. Entering a per-piece rate derives the equivalent rate
  per kg when the field is blank.
- **`public/js/purchase_weight_pricing.js` did not parse, so none of it ran.**
  An `if` statement sat inside the object literal handed to
  `frappe.ui.form.on`, with the braces doubled (`{{` / `}}`) as if the file
  were still a Jinja template. The browser rejected the whole file, so the
  plate marking before the first save, the rate suggestion, the live price
  preview AND the attachments panel it mounts were all dead on the site.
  A syntax error in a desk script is invisible until you run a parser over
  it - `npx prettier --check` or `node --check` both say so in a second.
- **`sum_header` was summing the wrong field.** It read each row under the
  HEADER's name, and no row carries a `custom_total_...` name, so "Total
  Estimated Weight" and "Total Accepted Weight" read zero on every Purchase
  Order, Receipt and Invoice. The row figure is the header name without the
  `total_` in it. The fields are display only - nothing reads them - so
  fixing it changed nothing else.

## The Purchase Order printouts (2026-10-21)

Two Purchase Order formats are shipped, in two different shapes, and both
have to carry the plate figures - the amount of a plate line is the weight
times the rate per kg, so a printout with the amount and neither of them
cannot be checked against the invoice:

| Format | Shape | Plate figures |
|---|---|---|
| `MPO Format` | Print Format Builder layout (`format_data`) | `custom_rate_per_kg` and `custom_est_weight_kg` on the items table |
| `Purchase order` | Jinja (`html`) | `row.custom_rate_per_kg` and `row.custom_est_weight_kg` |

- **The weight on a printout is the LINE's weight**, not the weight of one
  plate. `row.custom_est_weight_kg` is the line's total and
  `row.custom_unit_weight_kg` is one plate; the per-plate figure printed
  beside the quantity reads as the line's weight, and it is not.
- **The per-piece rate does not belong on a per-kg line.** It is
  `amount / qty` - a derived figure, rounded for display - so it never
  multiplies out to the amount printed beside it: 48,000.00 x 10 is
  480,000.00 and the amount is 480,000.02. And it is not a price anybody
  agreed to; the price is the rate per kg. So a line priced per kg prints
  its weight and its rate per kg, and nothing in the per-piece rate
  column, which stays for the lines that are not priced per kg. The check
  is on `row.custom_rate_per_kg`, NOT on `custom_is_plate`: with
  weight-based purchasing switched off a plate line carries an ordinary
  rate, and that rate is a real one.
- **A figure that is not there prints nothing, not zero.** "0.000" for a
  weight a line does not have says more than an empty cell does.
- **The address lookup in a print template has to be guarded.** A Purchase
  Order with no supplier address ran `frappe.get_doc('Address', '')` and
  failed the whole print with "Address not found". The guard is
  `{% if doc.supplier_address %}` - a supplier is not an address.
- **A print template should read the fields it needs, not the whole
  document.** `frappe.db.get_value("Item", row.item_code, [...],
  as_dict=True)` per line instead of `frappe.get_doc("Item", ...)`, which
  loads the Item and its child tables once per line.
- `tests/test_schema.py::TestPrintFormats` pins all of it.

Traps around the fixtures themselves:

- **A print format in the fixture is the source of truth, and it replaces
  the site's copy on every migrate.** That is deliberate - the site cannot
  drift away from the app - but it means a format the customer edits in the
  desk loses the edit on the next migrate. Change the fixture, not the site.
- **The `field_order` Property Setters of the buying item tables belong to
  the layout patches and must NOT be in the fixture.** The patches rebuild
  them from the live metadata on every migrate, because a field_order setter
  freezes the layout and a frozen order overrides insert_after. The export
  picks the site's runtime setters up, so
  `tools/generate_plate_property_setters.py` now drops them
  (`LAYOUT_DOCTYPES`) rather than carrying them over.
- **An export can EMPTY the custom field fixture.** The export writes
  whatever the site matched, and a site whose fixture import failed matches
  nothing - so `custom_field.json` went from 82 records to `[]`, and a
  fresh install would have had no plate customisation at all. Nothing in the
  app said so: the file was simply empty, and the sweep for undeclared
  `custom_*` names had nothing to complain about.
  `tests/test_schema.py::TestCustomFieldFixture` now checks the other way
  round - every field the generator declares has to be in the file - and that
  the file is not empty.
- **A fixture that holds a runtime record is a trap in general.** The
  export is a site snapshot, and the app's fixtures are meant to be the
  app's own decisions. What the export brought back that was worth keeping:
  both standard plate reports (the fixture had lost one) and a role profile.


