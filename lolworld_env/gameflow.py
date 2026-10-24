"""Wait operations and pure live-game validation, with no lobby or pick mutations."""
import time
import urllib.error
from .client import ApiError
from .live_data import get_champion, player_identity


def exit_custom_game(client, *, timeout=30, leave_game=None):
    """Return to the client home screen through LCU and verify phase None."""
    initial_phase = client.phase()
    if initial_phase == "None":
        return {"method": "already_exited", "phase": initial_phase}
    if initial_phase == "Lobby":
        client.request("DELETE", "/lol-lobby/v2/lobby")
        phase = wait_for_phase(client, "None", timeout=timeout)
        return {"method": "leave_lobby", "phase": phase}
    method = "dismiss_stats_api"
    if initial_phase not in {"EndOfGame", "PreEndOfGame", "WaitingForStats"}:
        session = client.request("GET", "/lol-gameflow/v1/session")
        if session.get("gameData", {}).get("isCustomGame") is not True:
            raise RuntimeError("Expected a custom game before requesting exit")
        if leave_game is not None and initial_phase in {"InProgress", "GameStart"}:
            leave_game()
            method = "double_alt_f4"
        else:
            accepted = client.request("POST", "/lol-gameflow/v1/session/request-lobby")
            if accepted is False:
                raise RuntimeError(f"Client refused the request to return to lobby after {initial_phase}")
            method = "request_lobby_api"
    phase = wait_for_phase(
        client, {"None", "Lobby", "EndOfGame", "PreEndOfGame", "WaitingForStats",
                 "TerminatedInError", "Reconnect"},
        timeout=timeout,
    )
    if phase in {"Reconnect", "TerminatedInError"}:
        accepted = client.request("POST", "/lol-gameflow/v1/session/request-lobby")
        if accepted is False:
            raise RuntimeError(f"Client refused the request to return to lobby after {phase}")
        phase = wait_for_phase(client, {"None", "Lobby"}, timeout=timeout)
    if phase in {"EndOfGame", "PreEndOfGame", "WaitingForStats"}:
        client.request("POST", "/lol-end-of-game/v1/state/dismiss-stats")
        phase = wait_for_phase(client, {"None", "Lobby"}, timeout=timeout)
    if phase == "Lobby":
        client.request("DELETE", "/lol-lobby/v2/lobby")
        phase = wait_for_phase(client, "None", timeout=timeout)
    return {"method": method, "phase": phase}


def wait_for_phase(client, phases, timeout=180, *, poll_interval=0.5, progress=None):
    if isinstance(phases, str):
        phases = {phases}
    else:
        phases = set(phases)
    if not phases or timeout <= 0 or poll_interval <= 0:
        raise ValueError("phases must be nonempty; timeout and poll_interval must be positive")
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        phase = client.phase()
        if phase != previous and progress:
            progress(f"Phase: {phase}")
        previous = phase
        if phase in phases:
            return phase
        if phase in {"FailedToLaunch", "TerminatedInError"}:
            raise RuntimeError(f"Game flow failed: {phase}")
        time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    raise TimeoutError(f"Timed out waiting for {sorted(phases)}")


def wait_for_live_game(client, timeout=180, *, poll_interval=1):
    """Wait for live API readiness and return raw data without scenario assumptions."""
    if timeout <= 0 or poll_interval <= 0:
        raise ValueError("timeout and poll_interval must be positive")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data = client.request("GET", "/liveclientdata/allgamedata", live=True)
            # The endpoint can respond during loading before players are populated.
            if isinstance(data, dict) and data.get("allPlayers"):
                return data
        except ApiError as exc:
            if exc.status not in {404, 500, 502, 503, 504}:
                raise
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    raise TimeoutError("Live Client Data API was not ready before timeout")


def validate_live_game(data, *, champion_name=None, player_count=None, game_mode=None):
    """Validate caller-specified expectations; return metadata. Does not make requests.

    champion_name uses the internal English name (e.g. Ahri), not a localized name.
    With multiple players, validation matches the active player by Riot ID/name.
    """
    players = data.get("allPlayers", [])
    game = data.get("gameData", {})
    if player_count is not None and len(players) != player_count:
        raise RuntimeError(f"Expected {player_count} players, got {len(players)}")
    if game_mode is not None and game.get("gameMode") != game_mode:
        raise RuntimeError(f"Expected game mode {game_mode}, got {game.get('gameMode')}")
    active = data.get("activePlayer", {})
    player = next((p for p in players if
                   (active.get("riotId") and p.get("riotId") == active["riotId"])
                   or (active.get("summonerName") and p.get("summonerName") == active["summonerName"])),
                  players[0] if len(players) == 1 else {})
    actual = player.get("rawChampionName", "").removeprefix("game_character_displayname_")
    if champion_name is not None and actual.lower() != champion_name.lower():
        raise RuntimeError(f"Expected active champion {champion_name}, got {actual or 'unknown'}")
    return {"success": True, "champion": actual or None, "players": len(players),
            "gameMode": game.get("gameMode"), "gameTime": game.get("gameTime")}


def validate_roster(data, player, *, enemy_champions=(), ally_champions=()):
    """Require exactly the specified bots, on the correct sides, and one human."""
    players = data.get("allPlayers", [])
    team = player.get("team")
    if team not in ("ORDER", "CHAOS"):
        return False
    if len(players) != 1 + len(enemy_champions) + len(ally_champions):
        return False
    identities = [player_identity(p) for p in players]
    if any(identity is None for identity in identities) or len(set(identities)) != len(identities):
        return False
    if player.get("isBot") is not False:
        return False
    enemies, allies = [], []
    for other in players:
        if other is player:
            continue
        if other.get("isBot") is not True or other.get("team") not in ("ORDER", "CHAOS"):
            return False
        (allies if other["team"] == team else enemies).append(get_champion(other))
    return (sorted(enemies) == sorted(enemy_champions)
            and sorted(allies) == sorted(ally_champions))
