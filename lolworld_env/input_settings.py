"""Persistent game input settings configured before launching a task game."""

INPUT_SETTINGS_PATH = "/lol-game-settings/v1/input-settings"
SKILL_QUICKBINDS = tuple(f"evtCastSpell{slot}smart" for slot in range(1, 5))


def set_normal_skill_cast(client):
    """Disable quick cast for the four champion skills, preserving other inputs.

    Quickbinds controls the mode of the existing evtCastSpell1..4 bindings;
    changing GameEvents alone would leave these bindings in quick-cast mode.
    Call before game launch so the new game loads the saved configuration.
    """
    settings = client.request("GET", INPUT_SETTINGS_PATH)
    quickbinds = settings.get("Quickbinds") if isinstance(settings, dict) else None
    if not isinstance(quickbinds, dict) or any(key not in quickbinds for key in SKILL_QUICKBINDS):
        raise RuntimeError("LCU input settings are missing champion skill Quickbinds")
    desired = {key: False for key in SKILL_QUICKBINDS}
    client.request("PATCH", INPUT_SETTINGS_PATH, {"Quickbinds": desired})
    client.request("POST", "/lol-game-settings/v1/save")
    confirmed = client.request("GET", INPUT_SETTINGS_PATH)
    actual = confirmed.get("Quickbinds", {}) if isinstance(confirmed, dict) else {}
    if not isinstance(actual, dict) or any(actual.get(key) is not False for key in desired):
        raise RuntimeError("LCU did not confirm normal casting for all four champion skills")
    return desired
