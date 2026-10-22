# Working on `addsol_nl_custom`

This is a Frappe/ERPNext v15 app with customer specific plate purchasing,
receipt, cutting, offcut, and stock reporting. Read `MEMORY.md` before making a
non-trivial change; it records the app's data model and known integration traps.

## Project layout

- `addsol_nl_custom/plates/`: plate settings, weight calculations, purchasing,
  receipt validation, item defaults, cutting, offcut handling, and API methods.
- `addsol_nl_custom/finished_goods/`: the finished-goods item code rule. An
  Item in the Item Group named `Finished Goods` is named from its Project
  (`<Project>-00001`) and may only be sold against that Project.
- `addsol_nl_custom/doctype/`: app DocTypes, including the single Plate Settings
  record and plate cutting records.
- `addsol_nl_custom/report/`: standard Python Script Reports. Keep the report
  JSON marked `is_standard: "Yes"` when its implementation is in the matching
  Python module. `Plate Stock Register` and `Plate Offcut Register` are two
  populations, not two views of one: the first holds whole plates and the
  remainder a cutting leaves behind, the second holds the pieces a cutting
  produced. Do not merge them back into one report with a filter.
- `addsol_nl_custom/patches/` and `patches.txt`: ordered, idempotent site
  migrations. Add patches in the correct pre/post model-sync section.
- `addsol_nl_custom/tests/`: Python tests for formula, schema, item, and weight
  behavior.

## Development checks

Run Python lint from the repository root:

```bash
ruff check addsol_nl_custom
```

Run app tests from the bench root against a development site:

```bash
bench --site <site> run-tests --app addsol_nl_custom
```

After changing a DocType, fixture, report, or patch, review whether the target
site needs `bench migrate`. Never run migrations against a production site from
this workspace.

## Implementation rules

- Keep plate-specific behavior opt-in through Plate Settings or the relevant
  Item Group/item configuration. Do not make ordinary purchasing behave as
  plate purchasing.
- Enforce permissions and business rules on the server. Client visibility is
  only a usability aid; it is not authorization.
- Whitelisted APIs must use `allow_guest=False` unless a documented public
  endpoint requires guest access.
- Make patches safe to rerun and safe when optional legacy records are absent.
- Preserve ERPNext's stock, valuation, serial/batch, and document lifecycle
  behavior. Prefer supported document APIs and verify field names against the
  installed ERPNext v15 schema.
- Keep formulas constrained to supported variables (`L`, `W`, `T`, `MF`) where
  weight formula validation applies. Do not use `custom_formula` as an input to
  the weight formula itself.
- Keep customer-specific React receipt presentation in `erpnext-ui`; this app
  owns the server-side plate settings, item checks, and validation contracts.
- The Item hooks are registered as a list, because more than one rule can own
  the Item name. The plate rule and the finished-goods rule are told apart by
  the Item Group, and each one stands down for the other's groups.
