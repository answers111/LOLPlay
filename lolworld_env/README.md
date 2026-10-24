# League client and game data operations

**English** | [简体中文](README.zh-CN.md)

`lolworld_env` provides composable League client operations, Live Client Data access, and evidence parsing. It uses the Python standard library. Importing the package does not start a game; constructing `LoLWorldClient` discovers a running client through Windows PowerShell.

Install from the project root with `python -m pip install -e .`. Client operations require exactly one running, signed-in League client. Live data requires a running match.

## Environment in the execution workflow

![Data flow between client, agent, and independent evaluation](../assets/overview.png)

This package connects to the client and reads states and events. The desktop environment supplies screenshots and input; task evaluators decide whether objectives are met.

## Example: prepare a custom game

```python
from lolworld_env import (
    LoLWorldClient, create_custom_lobby, start_champion_select,
    wait_for_phase, wait_for_pick_action, select_champion,
    lock_champion, set_default_skin, wait_for_live_game, validate_live_game,
)

client = LoLWorldClient()
create_custom_lobby(client, lobby_name="Ahri Practice", position="MIDDLE")
start_champion_select(client)
wait_for_phase(client, "ChampSelect", timeout=30)
root, action = wait_for_pick_action(client, timeout=30)
select_champion(client, 103, action_id=action["id"], api_root=root)
lock_champion(client, 103, action_id=action["id"], api_root=root)
set_default_skin(client, 103, api_root=root)
wait_for_phase(client, "InProgress", timeout=120)
data = wait_for_live_game(client, timeout=60)
summary = validate_live_game(
    data, champion_name="Ahri", player_count=1, game_mode="CLASSIC",
)
```

The example composes individual operations. Registered tasks also configure spells, runes, normal casting, bots where needed, and initial-state validation. See [tasks](../task/README.md).

## Client operations

| Group | Public functions |
| --- | --- |
| Queues and lobbies | `list_queues`, `find_practice_queue`, `get_lobby`, `create_lobby`, `create_custom_lobby`, `create_practice_lobby` |
| Lobby validation and bots | `validate_practice_lobby`, `validate_custom_lobby`, `add_custom_bot`, `validate_custom_bot_lobby` |
| Position and input settings | `set_position_preferences`, `set_normal_skill_cast` |
| Champion selection | `start_champion_select`, `get_champion_select_session`, `get_local_pick_action`, `wait_for_pick_action`, `get_pickable_champions`, `select_champion`, `lock_champion` |
| Loadout | `set_summoner_spells`, `set_runes`, `set_default_skin` |
| Game lifecycle | `wait_for_phase`, `wait_for_live_game`, `validate_live_game`, `validate_roster`, `exit_custom_game` |
| Transport | `LoLWorldClient.request`, `LoLWorldClient.phase`, `ApiError` |

Lobby creation requires client phase `None`. Custom and practice lobbies have separate creation functions; starting champion select is a separate operation. A position preference does not force the agent to play that lane. The creation helpers use `FILL` as the secondary preference; `position=None` skips preference configuration.

Selecting and locking require an active local pick action and an available champion. Configure D/F spells and runes before locking, and the default skin after locking. `set_runes()` overwrites and selects the first returned rune page, preserving its name; an absent or noneditable first page is an error. It accepts four primary perks, two secondary perks, and three stat shards.

`set_normal_skill_cast()` persists normal casting for Q/W/E/R. Waiting helpers have their own timeouts; an in-flight HTTP request may take up to another 10 seconds. Failures raise exceptions for the caller to handle.

## Live data and evidence

```python
from lolworld_env import get_live_data, get_player, get_creep_score, stat_ratio

data = get_live_data()
player = get_player(data)
if player is not None:
    creep_score = get_creep_score(player)
    mana_ratio = stat_ratio(data, "resourceValue", "resourceMax")
```

| Module | Responsibility / functions |
| --- | --- |
| `live_data.py` | Snapshot validation, player/champion/CS/time access, `item_counts`, `ability_levels`, `stat_value`, `stat_ratio`, player identities |
| `live_events.py` | Identity mapping, `champion_kill_events`, `objective_events`, `turret_identity` |
| `evaluation_state.py` | `capture_evaluation_state`, `capture_event_progress` |
| `validation.py` | `valid_number`, `valid_count`, `is_valid_scores_and_time` |

Except for API fetch functions, parsers work on caller-supplied snapshots. They do not decide task scores. Missing data is distinct from zero: `item_counts(None)` returns `None`, while `item_counts([])` returns an empty dictionary. Event attribution requires unambiguous identities and valid timestamps. Callers supply start times, target configurations, and initial-stat baselines.

The package does not depend on `task`. Task classes define objectives, limits, and success conditions; this package provides operations and evidence.

## Standalone example

[examples/initialize_match.py](../examples/initialize_match.py) demonstrates practice-game orchestration outside the installed package:

```powershell
python examples/initialize_match.py --champion-id 103 --lobby-name "My Practice"
```

See the [project guide](../README.md) for full agent execution.
