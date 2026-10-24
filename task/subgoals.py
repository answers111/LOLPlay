"""Stable, independent subgoal checks derived from task targets and evidence."""
import math


def subgoal_details(result, targets):
    """Expand items, abilities, towers and enemy kills into individual goals.

    Configuration and the overall deadline are not numbered gameplay goals.
    These checks describe observed progress, independently of the total score.
    """
    details = []
    labels = {
        "target_cs": "Creep score", "min_cs": "Creep score", "max_cs": "Creep score",
        "min_level": "Champion level", "min_gold": "Current gold", "min_current_gold": "Current gold",
        "max_deaths": "Deaths", "min_kills": "Personal kills within the time limit",
        "min_assists": "Assists within the time limit",
        "min_ally_assists": "Assists on allied kills within the time limit",
        "min_participations": "Kills and assists within the time limit",
        "target_max_health": "Maximum health", "min_mana_ratio": "Current mana ratio",
        "min_voidgrubs": "Personal Voidgrub kills within the time limit",
        "required_items": "Item count", "target_abilities": "Ability level", "exact_abilities": "Ability level",
        "stat_requirements": "Champion stat", "attribute_gain": "Stat gain",
        "resource_ratio": "Resource ratio", "alive": "Currently alive", "require_alive": "Currently alive",
        "kill_each_enemy": "Personally kill enemy within the time limit",
        "turrets": "Enemy turrets destroyed within the time limit",
        "ordered": "Complete objectives in the required order",
        "first_elemental_dragon": "Personally kill the first elemental dragon within the time limit",
        "enemy_mid_outer_turret": "Destroy the enemy middle outer turret within the time limit",
    }
    invalid_context = result.get("reason") in {
        "setup_error", "invalid_live_data", "active_player_not_found",
        "wrong_champion", "wrong_game_environment", "invalid_scores_or_time",
    }

    def add(name, expected, actual, operator=">="):
        achieved = None
        if not invalid_context and actual is not None:
            if isinstance(expected, bool):
                if isinstance(actual, bool):
                    achieved = actual == expected
            elif (not isinstance(actual, bool) and isinstance(actual, (int, float))
                  and math.isfinite(actual)):
                achieved = {">=": actual >= expected, "<=": actual <= expected,
                            "==": actual == expected}[operator]
        group, _, component = name.partition(".")
        description = labels.get(group, group)
        if component:
            description += f" ({component})"
        details.append({"name": name, "description": description,
                        "expected": expected, "actual": actual,
                        "operator": operator, "achieved": achieved})

    numeric = {
        "target_cs": ("creep_score", ">="), "min_cs": ("creep_score", ">="),
        "max_cs": ("creep_score", "<="), "min_level": ("level", ">="),
        "min_gold": ("current_gold", ">="), "min_current_gold": ("current_gold", ">="),
        "max_deaths": ("deaths", "<="), "min_kills": ("personal_kills", ">="),
        "min_assists": ("ally_assists", ">="), "min_ally_assists": ("ally_assists", ">="),
        "min_participations": ("participations", ">="),
        "target_max_health": ("max_health", ">="), "min_mana_ratio": ("mana_ratio", ">="),
        "min_voidgrubs": ("personal_voidgrubs", ">="),
    }
    for key, expected in targets.items():
        if key in numeric:
            field, operator = numeric[key]
            add(key, expected, result.get(field), operator)
        elif key in {"required_items", "target_abilities", "exact_abilities", "stat_requirements"}:
            field = {"required_items": "item_counts", "target_abilities": "ability_levels",
                     "exact_abilities": "ability_levels", "stat_requirements": "attributes"}[key]
            values = result.get(field)
            for component, minimum in expected.items():
                actual = None
                if isinstance(values, dict):
                    actual = values.get(component, values.get(str(component)))
                    if key == "required_items":
                        actual = values.get(int(component), values.get(str(component), 0))
                add(f"{key}.{component}", minimum, actual,
                    "==" if key == "exact_abilities" else ">=")
        elif key == "attribute_gain":
            add(f"attribute_gain.{expected[0]}", expected[1], result.get("attribute_gain"))
        elif key == "resource_ratio":
            add(f"resource_ratio.{expected[0]}/{expected[1]}", expected[2], result.get(key))
        elif key in {"alive", "require_alive"} and expected:
            add(key, True, result.get("alive"), "==")
        elif key == "kill_each_enemy" and expected:
            killed, enemies = result.get("killed_enemies"), result.get("enemy_players")
            for champion in targets.get("enemy_bots", ()):
                actual = None
                if isinstance(killed, list) and isinstance(enemies, list):
                    identities = [p["identity"] for p in enemies if p["champion"] == champion]
                    if identities and all(identity is not None for identity in identities):
                        actual = all(identity in killed for identity in identities)
                add(f"kill_each_enemy.{champion}", True, actual, "==")
        elif key == "turrets":
            progress = result.get("turret_progress")
            for lane, tier in expected:
                matches = ([p for p in progress if p["lane"] == lane and p["tier"] == tier]
                           if isinstance(progress, list) else [])
                add(f"turrets.{lane}.{tier}", 1,
                    matches[0]["count"] if len(matches) == 1 else None, "==")
        elif key == "ordered" and expected:
            progress = result.get("turret_progress")
            grubs = result.get("voidgrub_events")
            actual = None
            if isinstance(progress, list):
                if "min_voidgrubs" in targets:
                    if isinstance(grubs, list):
                        actual = bool(grubs and progress and progress[0]["game_times"]
                                      and min(e["EventTime"] for e in grubs)
                                      < min(progress[0]["game_times"]))
                elif len(progress) == len(targets.get("turrets", ())):
                    times = [p["game_times"] for p in progress]
                    actual = (all(len(t) == 1 for t in times)
                              and all(a[0] < b[0] for a, b in zip(times, times[1:])))
            add("ordered", True, actual, "==")
        elif key == "target":
            # The legacy single-objective scorers check event ownership/time.
            # Their result is authoritative; malformed evidence stays unknown.
            reason = result.get("reason", "")
            known = {"target_reached", "target_not_reached", "execution_budget_exhausted",
                     "not_elemental_dragon", "dragon_killed_before_task",
                     "first_dragon_not_killed_by_player", "turret_destroyed_before_task"}
            actual = result.get("success") if reason in known else None
            add(expected, True, actual, "==")
    return details


def add_target_results(result, targets):
    """Add numbered objects in evaluator order, plus a compact count summary."""
    details = subgoal_details(result, targets)
    for index, detail in enumerate(details, 1):
        result[f"target_{index}"] = detail
    result["target_summary"] = {
        "total": len(details),
        "achieved": sum(d["achieved"] is True for d in details),
        "not_achieved": sum(d["achieved"] is False for d in details),
        "unknown": sum(d["achieved"] is None for d in details),
    }
    return result
