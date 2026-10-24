"""Pure numeric validation for API counters, timestamps and limits."""
import math


def valid_number(value, *, positive=False):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and (value > 0 if positive else value >= 0))


def valid_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_valid_scores_and_time(cs, game_time):
    """Require nonnegative integer CS and finite, nonnegative game time."""
    return (
        not isinstance(cs, bool)
        and isinstance(cs, int)
        and cs >= 0
        and not isinstance(game_time, bool)
        and isinstance(game_time, (int, float))
        and math.isfinite(game_time)
        and game_time >= 0
    )
