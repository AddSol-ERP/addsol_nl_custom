"""Preserve historical commercial measurements before retiring their workflow."""

from addsol_nl_custom.patches import with_developer_mode_restored


@with_developer_mode_restored
def execute():
	from addsol_nl_custom.addsol_nl_custom.plates.legacy_pricing_migration import run

	run(dry_run=False)
