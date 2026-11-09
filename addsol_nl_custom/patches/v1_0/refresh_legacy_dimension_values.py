"""Refresh existing legacy dimensions as values with units, in T/L/W order."""

from addsol_nl_custom.patches import with_developer_mode_restored


@with_developer_mode_restored
def execute():
	from addsol_nl_custom.patches.v1_0.repair_legacy_print_dimensions import execute as repair

	repair()
