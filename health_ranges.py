"""
health_ranges.py - Shared healthy target ranges for nutrition metrics
==========================================================================
Used by both the Nutrition Dashboard (for the chart) and the AI Health
Coach (for its data summary), so "what's shown to you" and "what's given
to the AI" never disagree.
"""

HEALTHY_RANGES = {
    "calories":           {"label": "Calories (kcal)",       "min": 1800, "max": 2200},
    "protein_g":          {"label": "Protein (g/kg)",         "min": 0.8,  "max": 2.0, "per_kg": True},
    "fiber_g":             {"label": "Fiber (g)",             "min": 25,   "max": 38},
    "saturated_fat_g":     {"label": "Saturated fat (g)",     "min": 0,    "max": 20},
    "sugar_g":             {"label": "Added sugar (g)",       "min": 0,    "max": 50},
    "sodium_mg":           {"label": "Sodium (mg)",           "min": 0,    "max": 2300},
    "fruit_veg_servings":  {"label": "Fruit/veg (servings)",  "min": 5,    "max": 10},
}