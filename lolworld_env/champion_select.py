"""Read, select, and lock champion actions independently."""
import time
from .client import ApiError

DEFAULT_ROOT = "/lol-champ-select/v1"
LEGACY_ROOT = "/lol-champ-select-legacy/v1"


def get_champion_select_session(client):
    """Return (API root, session), supporting the legacy implementation."""
    try:
        return DEFAULT_ROOT, client.request("GET", DEFAULT_ROOT + "/session")
    except ApiError as exc:
        if exc.status != 404:
            raise
        if client.request("GET", LEGACY_ROOT + "/implementation-active") is not True:
            raise
        return LEGACY_ROOT, client.request("GET", LEGACY_ROOT + "/session")


def get_local_pick_action(session):
    """Return the current local pick action, or None; this is a pure function."""
    return next((a for group in session.get("actions", []) for a in group
                 if a.get("actorCellId") == session.get("localPlayerCellId")
                 and a.get("type") == "pick" and a.get("isInProgress")
                 and not a.get("completed")), None)


def wait_for_pick_action(client, timeout=180, poll_interval=0.5):
    """Return (API root, local action) once a pick action is available."""
    if timeout <= 0 or poll_interval <= 0:
        raise ValueError("timeout and poll_interval must be positive")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            root, session = get_champion_select_session(client)
        except ApiError as exc:
            if exc.status != 404:
                raise
        else:
            action = get_local_pick_action(session)
            if action:
                return root, action
        time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    raise TimeoutError("No active local pick action appeared")


def get_pickable_champions(client, *, api_root=DEFAULT_ROOT):
    return client.request("GET", api_root + "/pickable-champion-ids")


def set_summoner_spells(client, spell_d_id, spell_f_id, *, api_root=None):
    """Set and confirm the local player's D/F spells during champion selection."""
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
           for value in (spell_d_id, spell_f_id)):
        raise ValueError("Summoner spell IDs must be positive integers")
    if spell_d_id == spell_f_id:
        raise ValueError("D and F summoner spells must differ")
    root = api_root if api_root is not None else get_champion_select_session(client)[0]
    spells = {"spell1Id": spell_d_id, "spell2Id": spell_f_id}
    client.request("PATCH", root + "/session/my-selection", spells)
    session = client.request("GET", root + "/session")
    cell_id = session.get("localPlayerCellId")
    local_players = [player for player in session.get("myTeam", [])
                     if cell_id is not None and player.get("cellId") == cell_id]
    if (len(local_players) != 1
            or any(local_players[0].get(key) != value for key, value in spells.items())):
        raise RuntimeError("Client did not confirm the requested D/F summoner spells")
    return local_players[0]


def set_default_skin(client, champion_id, *, api_root=None):
    """Select and confirm the base skin after the champion is locked in.

    Custom blind pick publishes champion/skin IDs only after lock-in.
    """
    if isinstance(champion_id, bool) or not isinstance(champion_id, int) or champion_id <= 0:
        raise ValueError("champion_id must be a positive integer")
    root = api_root if api_root is not None else get_champion_select_session(client)[0]
    skin_id = champion_id * 1000
    client.request("PATCH", root + "/session/my-selection", {"selectedSkinId": skin_id})
    session = client.request("GET", root + "/session")
    cell_id = session.get("localPlayerCellId")
    local_players = [player for player in session.get("myTeam", [])
                     if cell_id is not None and player.get("cellId") == cell_id]
    if len(local_players) != 1 or local_players[0].get("selectedSkinId") != skin_id:
        raise RuntimeError(f"Client did not confirm champion {champion_id} default skin")
    return local_players[0]


def select_champion(client, champion_id, *, action_id=None, api_root=None):
    """Select a champion without locking or waiting. Return the PATCH response."""
    return _update_pick(client, champion_id, False, action_id, api_root)


def lock_champion(client, champion_id, *, action_id=None, api_root=None):
    """Lock the specified champion without waiting. Verify the completed action."""
    root, action_id = _resolve_action(client, action_id, api_root)
    _update_pick(client, champion_id, True, action_id, root)
    session = client.request("GET", root + "/session")
    confirmed = next((a for group in session.get("actions", []) for a in group
                      if a.get("id") == action_id), None)
    if not confirmed or not confirmed.get("completed") or confirmed.get("championId") != champion_id:
        raise RuntimeError(f"Client did not confirm champion {champion_id} lock-in")
    return confirmed


def _resolve_action(client, action_id, api_root):
    if action_id is not None and api_root is not None:
        return api_root, action_id
    root, session = get_champion_select_session(client)
    if api_root is not None and root != api_root:
        session = client.request("GET", api_root + "/session")
        root = api_root
    action = get_local_pick_action(session)
    if not action or (action_id is not None and action_id != action["id"]):
        raise RuntimeError("No matching active local pick action")
    return root, action["id"]


def _update_pick(client, champion_id, completed, action_id, api_root):
    if isinstance(champion_id, bool) or not isinstance(champion_id, int) or champion_id <= 0:
        raise ValueError("champion_id must be a positive integer")
    root, action_id = _resolve_action(client, action_id, api_root)
    if champion_id not in get_pickable_champions(client, api_root=root):
        raise RuntimeError(f"Champion {champion_id} is not pickable in this session")
    return client.request("PATCH", root + f"/session/actions/{action_id}",
                          {"championId": champion_id, "completed": completed})
