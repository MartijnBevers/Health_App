"""
estimation.py - Shared calorie/duration estimation for strength sets
=========================================================================
Strength-training logs (FitNotes CSV imports, or sets logged natively
via pages/3_Log_Workout.py) only record weight x reps per set -- no
duration or calorie figure. These two constants convert "number of
sets" into a rough duration and calorie estimate, so strength work can
sit on the same charts as cardio/Garmin data. Tune them to match how
your sessions actually feel.
"""

ESTIMATED_MIN_PER_SET = 3     # covers the set itself + rest between sets
ESTIMATED_KCAL_PER_MIN = 6    # ~moderate-intensity strength training