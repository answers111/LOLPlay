"""Read and interpret Live Client snapshots without task-specific goals."""
import json
import ssl
import urllib.request

from .names import add_english_names
from .validation import valid_count, valid_number

URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"


def get_live_data(english=False):
    """Read live game data without a League client connection."""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    with opener.open(URL, timeout=10) as response:
        data = json.load(response)
    if english:
        add_english_names(data)
    return data


def is_valid_live_data(data):
    """Check the snapshot structure required for evaluation."""
    if not isinstance(data, dict):
        return False
    players = data.get("allPlayers")
    return (
        isinstance(players, list)
        and bool(players)
        and all(isinstance(player, dict) for player in players)
        and isinstance(data.get("activePlayer", {}), dict)
        and isinstance(data.get("gameData", {}), dict)
    )


def get_player(data):
    """Return the uniquely matched active player, or None if unavailable."""
    if not is_valid_live_data(data):
        return None

    players = data["allPlayers"]
    active = data.get("activePlayer", {})
    # Prefer Riot ID; do not fall back to another player when an ID is present.
    key = "riotId" if active.get("riotId") else "summonerName"
    identity = active.get(key)
    if not identity:
        return players[0] if len(players) == 1 else None

    matches = [player for player in players if player.get(key) == identity]
    return matches[0] if len(matches) == 1 else None


def get_champion(player):
    """Extract the English champion name from a player record."""
    raw = player.get("rawChampionName", "")
    return raw.removeprefix("game_character_displayname_") if isinstance(raw, str) else ""


def get_creep_score(player):
    """Read CS without converting or accepting malformed score records."""
    scores = player.get("scores", {})
    return scores.get("creepScore") if isinstance(scores, dict) else None


def get_game_time(data):
    """Read game time in seconds from the snapshot."""
    game = data.get("gameData", {})
    return game.get("gameTime") if isinstance(game, dict) else None


def item_counts(items):
    """Missing or malformed inventory is unknown, never an empty inventory."""
    if not isinstance(items, list):
        return None
    counts = {}
    for item in items:
        if not isinstance(item, dict):
            return None
        item_id, count = item.get("itemID"), item.get("count")
        if not valid_count(item_id) or item_id == 0 or not valid_count(count) or count == 0:
            return None
        counts[item_id] = counts.get(item_id, 0) + count
    return counts


def ability_levels(data):
    active = data.get("activePlayer", {})
    abilities = active.get("abilities") if isinstance(active, dict) else None
    if not isinstance(abilities, dict):
        return None
    levels = {}
    for key in ("Q", "W", "E", "R"):
        ability = abilities.get(key)
        level = ability.get("abilityLevel") if isinstance(ability, dict) else None
        if not valid_count(level) or level > (3 if key == "R" else 5):
            return None
        levels[key] = level
    return levels


def stat_value(data, key):
    active = data.get("activePlayer", {})
    stats = active.get("championStats", {}) if isinstance(active, dict) else {}
    value = stats.get(key) if isinstance(stats, dict) else None
    return value if valid_number(value) else None


def stat_ratio(data, current, maximum):
    value, limit = stat_value(data, current), stat_value(data, maximum)
    if value is None or limit is None or limit <= 0 or value > limit:
        return None
    return value / limit


def player_identity(player):
    """Prefer the full Riot ID; do not merge players by display name."""
    for key in ("riotId", "summonerName"):
        value = player.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def player_names(player):
    """Event payloads may use full Riot ID, game name, or legacy name."""
    return {player[key] for key in ("riotId", "riotIdGameName", "summonerName")
            if isinstance(player.get(key), str) and player[key]}
