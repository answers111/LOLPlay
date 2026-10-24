"""Lobby operations. Creating a lobby does not start champion selection."""
import time

PRACTICE_QUEUE_ID = 314
POSITIONS = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY", "FILL")


def _position_preferences(first_position, second_position):
    if first_position not in POSITIONS or second_position not in POSITIONS:
        raise ValueError(f"Position must be one of {POSITIONS}")
    if first_position == second_position and first_position != "FILL":
        raise ValueError("First and second position must differ")
    return {"firstPreference": first_position, "secondPreference": second_position}


def set_position_preferences(client, first_position, second_position="FILL", *,
                             confirmation_timeout=3.0):
    """Save lobby preferences and verify them; this does not assign a lane."""
    preferences = _position_preferences(first_position, second_position)
    client.request("PUT", "/lol-lobby/v2/lobby/members/localMember/position-preferences",
                   preferences)
    deadline = time.monotonic() + confirmation_timeout
    while True:
        lobby = get_lobby(client)
        local = lobby.get("localMember", {})
        config = lobby.get("gameConfig", {})
        if config.get("isCustom"):
            # Custom lobbies save preferences on team members, not localMember.
            summoner_id = local.get("summonerId")
            members = config.get("customTeam100", []) + config.get("customTeam200", [])
            matches = [member for member in members
                       if summoner_id is not None and member.get("summonerId") == summoner_id
                       and not member.get("isBot")]
            if len(matches) != 1:
                raise RuntimeError("Could not identify the local player in the custom lobby teams")
            local = matches[0]
        if (local.get("firstPositionPreference") == first_position
                and local.get("secondPositionPreference") == second_position):
            return preferences
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            actual = {field: local.get(field, "<missing>") for field in
                      ("firstPositionPreference", "secondPositionPreference")}
            raise RuntimeError(
                "Client did not confirm the requested position preferences: "
                f"expected={preferences!r}, actual={actual!r}")
        time.sleep(min(0.2, remaining))


def list_queues(client):
    queues = client.request("GET", "/lol-game-queues/v1/queues")
    return list(queues.values()) if isinstance(queues, dict) else queues


def find_practice_queue(client, queue_id=None):
    """Read available practice queues; optionally require a specific queue ID."""
    queues = [q for q in list_queues(client) if q.get("gameMode") == "PRACTICETOOL"
              and q.get("isEnabled") and q.get("queueAvailability") == "Available"]
    if queue_id is not None:
        queues = [q for q in queues if q["id"] == queue_id]
    if not queues:
        raise RuntimeError("No matching enabled Practice Tool queue found")
    return next((q for q in queues if q["id"] == PRACTICE_QUEUE_ID), queues[0])


def get_lobby(client):
    return client.request("GET", "/lol-lobby/v2/lobby")


def create_lobby(client, queue_id, *, custom_configuration=None,
                 lobby_name="Practice", lobby_password="",
                 position=None):
    """Create a lobby and optionally save the local player's position preferences."""
    if position is not None:
        _position_preferences(position, "FILL")
    if client.phase() != "None":
        raise RuntimeError("A lobby can only be created during phase None")
    body = {"queueId": queue_id}
    if custom_configuration is not None:
        body.update({"isCustom": True, "customGameLobby": {
            "configuration": dict(custom_configuration),
            "lobbyName": lobby_name, "lobbyPassword": lobby_password}})
    lobby = client.request("POST", "/lol-lobby/v2/lobby", body)
    if position is not None:
        set_position_preferences(client, position, "FILL")
        lobby = get_lobby(client)
    return lobby


def validate_practice_lobby(lobby, queue_id):
    """Validate a solo, bot-free practice lobby led by the local player."""
    config = lobby.get("gameConfig", {})
    bots = config.get("customTeam100", []) + config.get("customTeam200", [])
    if config.get("queueId") != queue_id or len(lobby.get("members", [])) != 1 or bots:
        raise RuntimeError("Existing lobby is not an empty solo Practice Tool lobby")
    if not lobby.get("localMember", {}).get("isLeader"):
        raise RuntimeError("Local player must be lobby leader")
    return lobby


def create_practice_lobby(client, progress=None, *, queue_id=None,
                          lobby_name="Solo Practice", lobby_password="", map_id=11):
    """Create a practice lobby only. Existing lobbies must be validated separately."""
    queue = find_practice_queue(client, queue_id)
    configuration = None
    if queue.get("isCustom"):
        configuration = {
            "gameMode": "PRACTICETOOL", "mapId": map_id,
            "gameMutator": "", "gameServerRegion": "",
            "gameTypeConfigId": queue["gameTypeConfig"]["id"],
            "mutators": {"id": 1}, "spectatorPolicy": "NotAllowed", "teamSize": 1}
    create_lobby(client, queue["id"], custom_configuration=configuration,
                 lobby_name=lobby_name, lobby_password=lobby_password)
    if progress:
        progress(f"Created Practice Tool lobby: {queue['id']}")
    return queue["id"]


def start_champion_select(client):
    """Start champion selection in the current custom/practice lobby; do not wait."""
    if client.phase() != "Lobby":
        raise RuntimeError("Champion selection can only start from a lobby")
    return client.request("POST", "/lol-lobby/v1/lobby/custom/start-champ-select")


def create_custom_lobby(client, *, lobby_name="Solo Custom", lobby_password="",
                        position=None):
    """Create a blind-pick Summoner's Rift custom lobby without adding bots."""
    if position is not None:
        _position_preferences(position, "FILL")
    queues = [q for q in list_queues(client)
              if q.get("isCustom") and q.get("isEnabled")
              and q.get("queueAvailability") == "Available"
              and q.get("gameMode") == "CLASSIC" and q.get("mapId") == 11
              and q.get("pickMode") == "SimulPickStrategy"]
    if not queues:
        raise RuntimeError("No enabled blind-pick Summoner's Rift custom queue found")
    queue = queues[0]
    lobby = create_lobby(
        client, queue["id"],
        custom_configuration={
            "gameMode": "CLASSIC", "mapId": 11,
            "gameMutator": "", "gameServerRegion": "",
            "gameTypeConfigId": queue["gameTypeConfig"]["id"],
            "mutators": {"id": queue["id"]},
            "spectatorPolicy": "NotAllowed", "teamSize": queue["numPlayersPerTeam"],
        },
        lobby_name=lobby_name, lobby_password=lobby_password,
        position=position,
    )
    return lobby


def validate_custom_lobby(lobby):
    """Require a solo Summoner's Rift custom lobby led by the local player."""
    config = lobby.get("gameConfig", {})
    teams = config.get("customTeam100", []) + config.get("customTeam200", [])
    if (
        not config.get("isCustom")
        or config.get("mapId") != 11
        or config.get("gameMode") != "CLASSIC"
        or len(lobby.get("members", [])) != 1
        or any(player.get("isBot") for player in teams)
    ):
        raise RuntimeError("Expected a solo Summoner's Rift custom lobby without bots")
    if not lobby.get("localMember", {}).get("isLeader"):
        raise RuntimeError("Local player must be lobby leader")
    return lobby


def custom_local_team(lobby):
    """Identify the local human's side without assuming a blue-side spawn."""
    summoner_id = lobby.get("localMember", {}).get("summonerId")
    matches = []
    for team_id in (100, 200):
        for member in lobby.get("gameConfig", {}).get(f"customTeam{team_id}", []):
            if (summoner_id is not None and member.get("summonerId") == summoner_id
                    and not member.get("isBot")):
                matches.append(team_id)
    if len(matches) != 1:
        raise RuntimeError("Could not identify the local human's custom team")
    return matches[0]


def add_custom_bot(client, champion_id, *, ally=False, difficulty="EASY", position="MIDDLE"):
    """Add one specified bot to a custom lobby and verify its champion and side."""
    if client.phase() != "Lobby":
        raise RuntimeError("Bots can only be added during phase Lobby")
    if position not in POSITIONS:
        raise ValueError(f"Position must be one of {POSITIONS}")
    available = client.request("GET", "/lol-lobby/v2/lobby/custom/available-bots")
    if not isinstance(available, list) or not any(
        bot.get("id") == champion_id and bot.get("active") is True
        and isinstance(bot.get("botDifficulties"), list)
        and difficulty in bot["botDifficulties"] for bot in available
        if isinstance(bot, dict)
    ):
        raise RuntimeError("Requested bot champion/difficulty is unavailable")
    before = get_lobby(client)
    local_team = custom_local_team(before)
    team_id = local_team if ally else 300 - local_team
    before_bots = sum(bool(p.get("isBot")) for p in
                      before["gameConfig"].get(f"customTeam{team_id}", []))
    client.request("POST", "/lol-lobby/v1/lobby/custom/bots", {
        "championId": champion_id, "botDifficulty": difficulty,
        "teamId": str(team_id), "position": position,
    })
    lobby = get_lobby(client)
    bots = [p for p in lobby.get("gameConfig", {}).get(f"customTeam{team_id}", [])
            if p.get("isBot") is True]
    if len(bots) != before_bots + 1 or not any(
        p.get("botChampionId") == champion_id and p.get("botDifficulty") == difficulty
        for p in bots
    ):
        raise RuntimeError("Client did not confirm the requested bot")
    return lobby


def validate_custom_bot_lobby(lobby, *, enemy_champion_ids, ally_champion_ids=(),
                              difficulty="EASY"):
    """Require one local human and exactly the configured bots on each side."""
    config = lobby.get("gameConfig", {})
    if (config.get("isCustom") is not True or config.get("mapId") != 11
            or config.get("gameMode") != "CLASSIC"
            or len(lobby.get("members", [])) != 1
            or not lobby.get("localMember", {}).get("isLeader")
            or config.get("customSpectators")):
        raise RuntimeError("Expected a local-led Summoner's Rift custom bot lobby")
    team_id = custom_local_team(lobby)
    humans = [p for side in (100, 200) for p in config.get(f"customTeam{side}", [])
              if p.get("isBot") is not True]
    if len(humans) != 1:
        raise RuntimeError("Expected exactly one human player")
    for side, expected in ((team_id, ally_champion_ids), (300 - team_id, enemy_champion_ids)):
        bots = [p for p in config.get(f"customTeam{side}", []) if p.get("isBot") is True]
        if (sorted(p.get("botChampionId", -1) for p in bots) != sorted(expected)
                or any(p.get("botDifficulty") != difficulty for p in bots)):
            raise RuntimeError("Custom bot roster does not match the task configuration")
    return lobby
