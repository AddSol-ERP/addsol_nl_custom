"""Legacy print geometry comes from the customer Item master, not pricing factors."""

import math


def item_dimensions(item):
	thickness = item.get("thickness_mm")
	if item.get("custom_thickness_dropdown"):
		from addsol_nl_custom.addsol_nl_custom.plates.weight import get_item_thickness_mm

		thickness = get_item_thickness_mm(item)
	parts = []
	for symbol, value in (
		("T", thickness),
		("L", item.get("custom_length_mm")),
		("W", item.get("custom_width_mm")),
	):
		if value in (None, ""):
			continue
		value = float(value)
		if math.isfinite(value) and value > 0:
			parts.append(f"{symbol} {value:.12g} mm")
	return " \u00d7 ".join(parts)
