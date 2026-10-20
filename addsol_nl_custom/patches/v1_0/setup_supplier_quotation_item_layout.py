"""Move the quantity, rate and plate details above Description on Supplier Quotations.

The same block the Purchase Order item gets, for the same reason: a plate
line on a quotation is priced by weight, and the figures that price it
belong next to the quantity and the rate rather than below the description.

Idempotent, and it never overwrites a layout the site already has: the field
order is rebuilt from the live metadata, so the rest of this site's own
arrangement is carried over untouched.
"""

from addsol_nl_custom.patches.v1_0.setup_purchase_order_item_layout import apply_layout

DOCTYPE = "Supplier Quotation Item"
DESCRIPTION_SECTION = "section_break_5"
QUANTITY_SECTION = "quantity_and_rate"


def execute():
	apply_layout(DOCTYPE, DESCRIPTION_SECTION, QUANTITY_SECTION, "Supplier Quotation")
