"""Pure parsing and attribution of Live Client events and map identities."""
import re

from .live_data import player_names
from .validation import valid_count, valid_number


def event_player_names(players):
    """Map every accepted event name to one player; ambiguous aliases fail closed."""
    names = {}
    for player in players:
        for name in player_names(player):
            if name in names and names[name] is not player:
                return None
            names[name] = player
    return names


def champion_kill_events(data, *, start_game_time, game_time):
    """Validate final event history; reject duplicate IDs and invalid attribution."""
    container = data.get("events")
    events = container.get("Events") if isinstance(container, dict) else None
    if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
        return None
    ids, kills = set(), []
    for event in events:
        event_id, when = event.get("EventID"), event.get("EventTime")
        if (not valid_count(event_id) or event_id in ids
                or not valid_number(when) or when > game_time):
            return None
        ids.add(event_id)
        if event.get("EventName") != "ChampionKill":
            continue
        if (not isinstance(event.get("KillerName"), str) or not event["KillerName"]
                or not isinstance(event.get("VictimName"), str) or not event["VictimName"]
                or not isinstance(event.get("Assisters"), list)
                or not all(isinstance(a, str) and a for a in event["Assisters"])
                or len(set(event["Assisters"])) != len(event["Assisters"])):
            return None
        if when >= start_game_time:
            kills.append(event)
    return kills


def objective_events(data, *, start_game_time, game_time):
    """Validate objective evidence, including the per-Voidgrub HordeKill event."""
    container = data.get("events")
    events = container.get("Events") if isinstance(container, dict) else None
    if not isinstance(events, list):
        return None
    ids, objectives = set(), []
    for event in events:
        if not isinstance(event, dict):
            return None
        event_id, when = event.get("EventID"), event.get("EventTime")
        name = event.get("EventName")
        if (not valid_count(event_id) or event_id in ids
                or not valid_number(when) or when > game_time
                or not isinstance(name, str) or not name):
            return None
        ids.add(event_id)
        if name not in ("TurretKilled", "HordeKill"):
            continue
        field = "TurretKilled" if name == "TurretKilled" else "KillerName"
        if not isinstance(event.get(field), str) or not event[field]:
            return None
        if when >= start_game_time:
            objectives.append(event)
    return objectives


def turret_identity(name):
    """Decode a Map11 tower's team, lane and tier, ignoring only its numeric hash.

    Legacy map names: LeagueSandbox Map11/LevelScriptObjects.cs.
    Current event names: Zernomis/328b5de7b381659c81cb7a587473237a.
    Unknown names remain unknown; substrings and ARAM IDs are not accepted.
    """
    if not isinstance(name, str):
        return None
    modern = re.fullmatch(r"Turret_T(Order|Chaos)_L([012])_P([123])_([0-9]+)", name)
    if modern:
        team, lane, tier, _ = modern.groups()
        return (team.upper(), {"2": "TOP", "1": "MIDDLE", "0": "BOTTOM"}[lane],
                {"3": "OUTER", "2": "INNER", "1": "INHIBITOR"}[tier])
    legacy = re.fullmatch(r"Turret_T([12])_([LRC])_(0[1-7])_A", name)
    if not legacy:
        return None
    team, lane, tier = legacy.groups()
    tiers = {"05": "OUTER", "04": "INNER", "03": "INHIBITOR"} if lane == "C" else {
        "03": "OUTER", "02": "INNER", "01": "INHIBITOR"}
    if tier not in tiers:
        return None
    return ({"1": "ORDER", "2": "CHAOS"}[team],
            {"L": "TOP", "C": "MIDDLE", "R": "BOTTOM"}[lane], tiers[tier])
