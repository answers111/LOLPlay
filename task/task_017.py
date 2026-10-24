"""Control DrMundo final-state task."""

import copy
import time

from lolworld_env import (
    capture_evaluation_state,
    LoLWorldClient,
    create_custom_lobby,
    set_normal_skill_cast,
    get_lobby,
    validate_custom_lobby,
    start_champion_select,
    wait_for_pick_action,
    select_champion,
    set_default_skin,
    lock_champion,
    set_summoner_spells,
    set_runes,
    wait_for_phase,
    wait_for_live_game,
    validate_live_game,
    get_live_data,
    is_valid_live_data,
    is_valid_scores_and_time,
    get_player,
    get_champion,
    get_creep_score,
    get_game_time,
    valid_number,
    valid_count,
    item_counts,
    stat_ratio,
    player_identity,
    validate_roster,
)

from .base_task import BaseTask
from .subgoals import add_target_results


CHAMPION_ID = 36
CHAMPION_NAME = "DrMundo"
POSITION = "TOP"
SPELL_D_ID = 6  # Ghost
SPELL_F_ID = 4  # Flash
RUNE_PAGE = {
    "primaryStyleId": 8400,  # Resolve
    "subStyleId": 8300,  # Inspiration
    "selectedPerkIds": [
        8437,  # Grasp of the Undying
        8446,  # Demolish
        8444,  # Second Wind
        8453,  # Revitalize
        8345,  # Biscuit Delivery
        8410,  # Approach Velocity
        5005,  # Attack speed
        5008,  # Adaptive force
        5001,  # Scaling health
    ],
}
TARGET_CS = 20
RESOURCE_RATIO = ("currentHealth", "maxHealth", 0.8)
REQUIRE_ALIVE = True
TIME_LIMIT_SECONDS = 480
SETUP_TIMEOUT_SECONDS = 600
LOBBY_NAME = "Dr. Mundo: Healthy Harvest"


class Task017(BaseTask):
    id = "task_017"
    trajectory = "results"

    instruction = (
        "Control Dr. Mundo in the top lane. At the end of 8 minutes, be alive with at "
        "least 20 CS and 80% health. Use Q for safe last hits and allow time to "
        "recover; keep playing until the deadline."
    )

    source = "lolworld_env"
    capture_evaluation_at_deadline = True
    execution_time_limit_seconds = TIME_LIMIT_SECONDS

    evaluator = {
        "type": "live_client_data",
        "champion": CHAMPION_NAME,
        "min_cs": TARGET_CS,
        "resource_ratio": RESOURCE_RATIO,
        "require_alive": REQUIRE_ALIVE,
        "time_limit_seconds": TIME_LIMIT_SECONDS,
        "timing": "execution_wall_time_deadline",
    }

    def setup(self, setup_controller=None, *, timeout=SETUP_TIMEOUT_SECONDS, position=POSITION):
        """Prepare the specified custom game and start timing after verification."""
        self._setup_time_seconds = None
        self._task_started_at = None
        self._task_start_game_time = None
        self._initial_roster = None
        started = time.monotonic()

        if not valid_number(timeout, positive=True):
            raise ValueError("timeout must be finite and positive")

        deadline = started + timeout
        client = getattr(setup_controller, "client", None)

        if client is None:
            client = LoLWorldClient()

        create_custom_lobby(client, lobby_name=LOBBY_NAME, position=position)
        set_normal_skill_cast(client)
        wait_for_phase(client, "Lobby", timeout=deadline - time.monotonic())
        validate_custom_lobby(get_lobby(client))

        start_champion_select(client)
        wait_for_phase(client, "ChampSelect", timeout=deadline - time.monotonic())

        root, action = wait_for_pick_action(client, timeout=deadline - time.monotonic())
        select_champion(client, CHAMPION_ID, action_id=action["id"], api_root=root)

        set_summoner_spells(client, SPELL_D_ID, SPELL_F_ID, api_root=root)
        set_runes(client, primary_style_id=RUNE_PAGE["primaryStyleId"], sub_style_id=RUNE_PAGE["subStyleId"], selected_perk_ids=RUNE_PAGE["selectedPerkIds"])

        lock_champion(client, CHAMPION_ID, action_id=action["id"], api_root=root)
        set_default_skin(client, CHAMPION_ID, api_root=root)

        wait_for_phase(client, "InProgress", timeout=deadline - time.monotonic())
        data = wait_for_live_game(client, timeout=deadline - time.monotonic())

        validate_live_game(data, champion_name=CHAMPION_NAME, player_count=1, game_mode="CLASSIC")

        if not is_valid_live_data(data) or not isinstance(data.get("activePlayer"), dict) or (not isinstance(data.get("gameData"), dict)):
            raise RuntimeError("Expected valid fresh Live Client Data")

        player = get_player(data)

        if player is None:
            raise RuntimeError("Active player not found")

        if get_champion(player).lower() != CHAMPION_NAME.lower() or data.get("gameData", {}).get("gameMode") != "CLASSIC" or data.get("gameData", {}).get("mapNumber") != 11 or (not validate_roster(data, player, enemy_champions=(), ally_champions=())):
            raise RuntimeError("Fresh game roster does not match the task configuration")

        cs, game_time = (get_creep_score(player), get_game_time(data))
        deaths = player.get("scores", {}).get("deaths")

        if not is_valid_scores_and_time(cs, game_time) or cs != 0 or (not valid_count(player.get("level"))) or (player["level"] != 1) or (not valid_count(deaths)) or (deaths != 0):
            raise RuntimeError("Expected level 1, zero CS, and zero deaths at setup")

        counts = item_counts(player.get("items"))

        if counts is None:
            raise RuntimeError("Initial inventory was not confirmed")

        if time.monotonic() >= deadline:
            raise TimeoutError("Task preparation exceeded its deadline")

        self._initial_roster = sorted((player_identity(p) for p in data["allPlayers"]))
        self._task_start_game_time = game_time
        finished = time.monotonic()
        self._setup_time_seconds = finished - started
        self._task_started_at = finished

    def evaluate(self, env=None):
        """Score final API evidence only; transport errors propagate to the runner."""
        evaluated_at = time.monotonic()
        started = getattr(self, "_task_started_at", None)
        start_game_time = getattr(self, "_task_start_game_time", None)

        if start_game_time is None:
            start_game_time = 0

        data = env.get_live_data() if env is not None and callable(getattr(env, "get_live_data", None)) else get_live_data()
        wall_time = evaluated_at - started if started is not None else None

        result = {
            "score": 0.0,
            "success": False,
            "reason": "invalid_live_data",
            "champion": None,
            "level": None,
            "creep_score": None,
            "deaths": None,
            "items": None,
            "current_gold": None,
            "ability_levels": None,
            "attributes": None,
            "attribute_gain": None,
            "resource_ratio": None,
            "qualifying_events": None,
            "game_time": None,
            "setup_time_seconds": getattr(self, "_setup_time_seconds", None),
            "execution_time_seconds": wall_time,
            "execution_game_time_seconds": None,
            "time_limit_seconds": TIME_LIMIT_SECONDS,
            "targets": copy.deepcopy(self.evaluator),
            "timing": "execution_wall_time_deadline",
        }

        capture_evaluation_state(
            result, data, targets=self.evaluator,
            start_game_time=getattr(self, "_task_start_game_time", None),
            initial_stats=getattr(self, "_initial_stats", None),
        )

        if not is_valid_live_data(data) or not isinstance(data.get("activePlayer"), dict) or (not isinstance(data.get("gameData"), dict)):
            return add_target_results(result, self.evaluator or {})

        player = get_player(data)

        if player is None:
            result["reason"] = "active_player_not_found"
            return add_target_results(result, self.evaluator or {})

        champion = get_champion(player)
        cs, game_time = (get_creep_score(player), get_game_time(data))
        result.update(champion=champion, creep_score=cs, game_time=game_time)

        if champion.lower() != CHAMPION_NAME.lower():
            result["reason"] = "wrong_champion"
            return add_target_results(result, self.evaluator or {})

        game = data.get("gameData", {})

        if game.get("gameMode") != "CLASSIC" or game.get("mapNumber") != 11 or (not validate_roster(data, player, enemy_champions=(), ally_champions=())):
            result["reason"] = "wrong_game_environment"
            return add_target_results(result, self.evaluator or {})

        roster = sorted((player_identity(p) for p in data["allPlayers"]))
        initial_roster = getattr(self, "_initial_roster", None)

        if initial_roster is not None and roster != initial_roster:
            result["reason"] = "wrong_game_environment"
            return add_target_results(result, self.evaluator or {})

        if not is_valid_scores_and_time(cs, game_time) or game_time < start_game_time:
            result["reason"] = "invalid_scores_or_time"
            return add_target_results(result, self.evaluator or {})

        elapsed = game_time - start_game_time
        result["execution_game_time_seconds"] = elapsed
        elapsed_for_deadline = wall_time if wall_time is not None else elapsed

        if elapsed_for_deadline < TIME_LIMIT_SECONDS:
            result["reason"] = "task_not_finished"
            return add_target_results(result, self.evaluator or {})

        level, items = (player.get("level"), player.get("items"))
        scores = player.get("scores", {})
        deaths = scores.get("deaths") if isinstance(scores, dict) else None
        active = data.get("activePlayer", {})
        gold = active.get("currentGold") if isinstance(active, dict) else None
        result.update(level=level if valid_count(level) and 1 <= level <= 18 else None, deaths=deaths if valid_count(deaths) else None, items=copy.deepcopy(items), current_gold=gold if valid_number(gold) else None)

        if not valid_count(level) or not 1 <= level <= 18:
            result["reason"] = "invalid_level"
            return add_target_results(result, self.evaluator or {})

        ratio = None
        current, maximum, minimum = RESOURCE_RATIO
        ratio = stat_ratio(data, current, maximum)
        result["resource_ratio"] = ratio

        if ratio is None:
            result["reason"] = "invalid_resource_stats"
            return add_target_results(result, self.evaluator or {})

        if REQUIRE_ALIVE and (not isinstance(player.get("isDead"), bool)):
            result["reason"] = "invalid_alive_state"
            return add_target_results(result, self.evaluator or {})

        if cs < TARGET_CS or ratio < RESOURCE_RATIO[2] or player["isDead"]:
            result["reason"] = "target_not_reached"
        else:
            result.update(score=1.0, success=True, reason="target_reached")

        return add_target_results(result, self.evaluator or {})


MundoHealthTask = Task017
