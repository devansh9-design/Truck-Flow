"""Unit conversions at the provider boundary.

The wire is always imperial. Providers that speak metric (HERE: meters, kg)
are converted exactly once, here.
"""

METERS_PER_MILE = 1609.344  # international mile, exact
KG_PER_LB = 0.45359237  # international avoirdupois pound, exact


def meters_to_miles(meters: float) -> float:
    return meters / METERS_PER_MILE


def miles_to_meters(miles: float) -> float:
    return miles * METERS_PER_MILE


def lb_to_kg(lb: float) -> float:
    return lb * KG_PER_LB
