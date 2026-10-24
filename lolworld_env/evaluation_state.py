"""Collect Live Client state and event evidence without computing task scores."""
import copy

from .live_data import (
    get_game_time, get_player, player_identity, get_champion,
    ability_levels, item_counts, stat_ratio, stat_value,
)
from .live_events import (
    champion_kill_events, event_player_names, objective_events, turret_identity,
)
from .validation import valid_count, valid_number


def capture_evaluation_state(result, data, *, targets, start_game_time=0, initial_stats=None):
    """Populate evidence from one snapshot, using caller-supplied context.

    Missing values remain unknown. The caller owns the task configuration,
    start time and baseline; this module does not depend on task classes.
    """
    result.update(level=None, deaths=None, items=None, current_gold=None,
                  ability_levels=None, attributes=None, attribute_gain=None,
                  resource_ratio=None, events=None, alive=None, mana_ratio=None,
                  max_health=None, item_counts=None, kills=None, assists=None,
                  initial_attributes=None)
    result.setdefault("targets", copy.deepcopy(targets))
    result["task_start_game_time"] = 0 if start_game_time is None else start_game_time
    targets = targets if isinstance(targets, dict) else {}
    capture_event_progress(result, data, targets)
    if not isinstance(data, dict):
        return
    result["events"] = copy.deepcopy(data.get("events"))
    player = get_player(data)
    if player is None:
        return
    active = data.get("activePlayer", {})
    level = player.get("level")
    scores = player.get("scores", {})
    deaths = scores.get("deaths") if isinstance(scores, dict) else None
    gold = active.get("currentGold")
    stats = active.get("championStats")
    result.update(
        level=level if valid_count(level) and 1 <= level <= 18 else None,
        deaths=deaths if valid_count(deaths) else None,
        items=copy.deepcopy(player.get("items")),
        current_gold=gold if valid_number(gold) else None,
        ability_levels=ability_levels(data),
        attributes=copy.deepcopy(stats) if isinstance(stats, dict) else None,
        alive=not player["isDead"] if isinstance(player.get("isDead"), bool) else None,
        mana_ratio=stat_ratio(data, "resourceValue", "resourceMax"),
        max_health=stat_value(data, "maxHealth"),
        item_counts=item_counts(player.get("items")),
        kills=scores.get("kills") if isinstance(scores, dict) and valid_count(scores.get("kills")) else None,
        assists=scores.get("assists") if isinstance(scores, dict) and valid_count(scores.get("assists")) else None,
    )
    if isinstance(initial_stats, dict):
        result["initial_attributes"] = copy.deepcopy(initial_stats)
    gain_target = targets.get("attribute_gain")
    if isinstance(gain_target, (list, tuple)) and len(gain_target) >= 1:
        key = gain_target[0]
        current = stat_value(data, key)
        initial = initial_stats.get(key) if isinstance(initial_stats, dict) else None
        if current is not None and valid_number(initial):
            result["attribute_gain"] = current - initial
    ratio_target = targets.get("resource_ratio")
    if isinstance(ratio_target, (list, tuple)) and len(ratio_target) >= 2:
        result["resource_ratio"] = stat_ratio(data, *ratio_target[:2])
    else:
        result["resource_ratio"] = stat_ratio(data, "resourceValue", "resourceMax")


def capture_event_progress(result, data, targets):
    kill_targets = {"min_kills", "min_assists", "min_ally_assists",
                    "min_participations", "kill_each_enemy"}
    needs_kills = bool(kill_targets.intersection(targets))
    needs_objectives = "turrets" in targets or "min_voidgrubs" in targets
    if needs_kills:
        result.update(personal_kills=None, ally_assists=None, participations=None,
                      killed_enemies=None, enemy_players=None)
    if needs_objectives:
        result.update(turret_events=None, turret_progress=None)
    if "min_voidgrubs" in targets:
        result.update(personal_voidgrubs=None, voidgrub_events=None)
    if not isinstance(data, dict):
        return
    player = get_player(data)
    if player is None:
        return
    start, now = result["task_start_game_time"], get_game_time(data)
    limit = targets.get("time_limit_seconds")
    if (not valid_number(start) or not valid_number(now) or now < start
            or not valid_number(limit, positive=True)):
        return
    names = event_player_names(data["allPlayers"])
    if needs_kills:
        enemies = [p for p in data["allPlayers"] if p.get("team") != player.get("team")]
        result["enemy_players"] = [{"identity": player_identity(p), "champion": get_champion(p)}
                                   for p in enemies]
        events = champion_kill_events(data, start_game_time=start, game_time=now)
        if events is not None and names is not None:
            personal, assisted, victims = [], [], set()
            for event in events:
                if event["EventTime"] - start > limit:
                    continue
                killer = names.get(event["KillerName"])
                victim = names.get(event["VictimName"])
                assisters = [names.get(name) for name in event["Assisters"]]
                if (victim is None or any(p is None for p in assisters)
                        or killer is victim or any(p is killer or p is victim for p in assisters)
                        or (killer is not None and killer.get("team") == victim.get("team"))
                        or len({id(p) for p in assisters}) != len(assisters)):
                    break
                if victim.get("team") == player.get("team"):
                    continue
                if killer is player:
                    personal.append(event)
                    victims.add(player_identity(victim))
                elif (killer is not None and killer.get("team") == player.get("team")
                      and any(p is player for p in assisters)):
                    assisted.append(event)
            else:
                if None not in victims:
                    result.update(personal_kills=len(personal), ally_assists=len(assisted),
                                  participations=len(personal) + len(assisted),
                                  killed_enemies=sorted(victims),
                                  qualifying_events=copy.deepcopy(personal + assisted))
    if not needs_objectives:
        return
    events = objective_events(data, start_game_time=start, game_time=now)
    team = player.get("team")
    if events is None or team not in ("ORDER", "CHAOS"):
        return
    enemy = "CHAOS" if team == "ORDER" else "ORDER"
    towers, progress = [], []
    for lane, tier in targets.get("turrets", ()):
        matches = [e for e in events if e["EventName"] == "TurretKilled"
                   and turret_identity(e["TurretKilled"]) == (enemy, lane, tier)
                   and e["EventTime"] - start <= limit]
        towers.extend(matches)
        progress.append({"lane": lane, "tier": tier, "count": len(matches),
                         "game_times": [e["EventTime"] for e in matches]})
    result.update(turret_events=copy.deepcopy(towers), turret_progress=progress)
    if "min_voidgrubs" in targets and names is not None:
        grubs = [e for e in events if e["EventName"] == "HordeKill"
                 and names.get(e["KillerName"]) is player and e["EventTime"] - start <= limit]
        result.update(personal_voidgrubs=len(grubs), voidgrub_events=copy.deepcopy(grubs))
