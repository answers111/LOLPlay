"""Develop Sion and finish ten minutes with at least 2000 maximum health."""

import copy
import math
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
    wait_for_phase,
    wait_for_live_game,
    validate_live_game,
    get_live_data,
    set_summoner_spells,
    set_runes,
    is_valid_live_data,
    is_valid_scores_and_time,
    get_player,
    get_champion,
    get_creep_score,
    get_game_time,
)

from .base_task import BaseTask
from .subgoals import add_target_results


CHAMPION_ID = 14
CHAMPION_NAME = "Sion"
POSITION = "TOP"
SPELL_D_ID = 12  # Teleport
SPELL_F_ID = 4  # Flash
RUNE_PAGE = {
    "primaryStyleId": 8400,  # Resolve
    "subStyleId": 8300,  # Inspiration
    "selectedPerkIds": [
        8437,  # Grasp of the Undying
        8446,  # Demolish
        8429,  # Conditioning
        8451,  # Overgrowth
        8304,  # Magical Footwear
        8347,  # Cosmic Insight
        5005,  # Attack speed
        5008,  # Adaptive force
        5001,  # Scaling health
    ],
}
TARGET_MAX_HEALTH = 2000
TIME_LIMIT_SECONDS = 600
SETUP_TIMEOUT_SECONDS = 600
LOBBY_NAME = "Sion: 2000 maximum health at 10 minutes"


def _valid_number(value, *, positive=False):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and (value > 0 if positive else value >= 0))


def get_max_health(data):
    """Read actual maximum health, independent of current health or shields."""
    active = data.get("activePlayer", {})
    stats = active.get("championStats", {}) if isinstance(active, dict) else {}
    return stats.get("maxHealth") if isinstance(stats, dict) else None


class Task004(BaseTask):
    id = "task_004"
    trajectory = "results"

    instruction = (
        "Control Sion. Gain experience to level up, farm gold, and purchase "
        "equipment to have at least 2000 maximum health when the 10-minute "
        "execution period ends. Learn and upgrade abilities, including Soul "
        "Furnace, and farm enemy minions to build permanent bonus health. "
        "Buy useful health equipment with earned gold. "
    )

    source = "lolworld_env"

    capture_evaluation_at_deadline = True
    execution_time_limit_seconds = TIME_LIMIT_SECONDS

    evaluator = {
        "type": "live_client_data",
        "champion": CHAMPION_NAME,
        "target_max_health": TARGET_MAX_HEALTH,
        "time_limit_seconds": TIME_LIMIT_SECONDS,
        "timing": "execution_wall_time_deadline",
    }

    def setup(self, setup_controller=None, *, timeout=SETUP_TIMEOUT_SECONDS,
              position=POSITION):
        """Prepare a fresh solo Sion game and start the execution clock."""
        self._setup_time_seconds = None
        self._task_started_at = None
        self._task_start_game_time = None
        started = time.monotonic()

        if not _valid_number(timeout, positive=True):
            raise ValueError("timeout must be finite and positive")

        deadline = started + timeout

        client = getattr(setup_controller, "client", None)

        if client is None:
            client = LoLWorldClient()

        create_custom_lobby(
            client,
            lobby_name=LOBBY_NAME,
            position=position,
        )
        set_normal_skill_cast(client)
        wait_for_phase(client, "Lobby", timeout=deadline - time.monotonic())
        validate_custom_lobby(get_lobby(client))

        start_champion_select(client)
        wait_for_phase(client, "ChampSelect", timeout=deadline - time.monotonic())

        root, action = wait_for_pick_action(client, timeout=deadline - time.monotonic())
        select_champion(client, CHAMPION_ID, action_id=action["id"], api_root=root)

        set_summoner_spells(client, SPELL_D_ID, SPELL_F_ID, api_root=root)
        set_runes(client, primary_style_id=RUNE_PAGE["primaryStyleId"],
                  sub_style_id=RUNE_PAGE["subStyleId"],
                  selected_perk_ids=RUNE_PAGE["selectedPerkIds"])

        lock_champion(client, CHAMPION_ID, action_id=action["id"], api_root=root)
        set_default_skin(client, CHAMPION_ID, api_root=root)

        wait_for_phase(client, "InProgress", timeout=deadline - time.monotonic())
        data = wait_for_live_game(client, timeout=deadline - time.monotonic())

        validate_live_game(
            data,
            champion_name=CHAMPION_NAME,
            player_count=1,
            game_mode="CLASSIC",
        )

        if data.get("gameData", {}).get("mapNumber") != 11:
            raise RuntimeError("Expected Summoner's Rift (map 11)")

        player = get_player(data)

        if player is None:
            raise RuntimeError("Active player not found")

        cs, game_time = get_creep_score(player), get_game_time(data)

        if (not is_valid_scores_and_time(cs, game_time) or cs != 0
                or player.get("level") != 1 or isinstance(player.get("level"), bool)
                or not _valid_number(get_max_health(data), positive=True)):
            raise RuntimeError("Expected a fresh Sion game at level 1 with zero CS and valid maximum health")

        self._task_start_game_time = game_time
        finished = time.monotonic()
        self._setup_time_seconds = finished - started
        self._task_started_at = finished

    def evaluate(self, env=None):
        """Score the final snapshot; the runner captures it at the wall deadline.

        Calls before ten minutes are incomplete even if health already meets
        the target. Without setup, game time supplies the execution clock.
        Later evaluation checks the supplied state rather than failing on delay.
        """
        evaluated_at = time.monotonic()
        started = getattr(self, "_task_started_at", None)
        start_game_time = getattr(self, "_task_start_game_time", None)

        if start_game_time is None:
            start_game_time = 0

        data = (
            env.get_live_data()
            if env is not None and callable(getattr(env, "get_live_data", None))
            else get_live_data()
        )
        wall_time = evaluated_at - started if started is not None else None

        result = {
            "score": 0.0,
            "success": False,
            "reason": "invalid_live_data",
            "champion": None,
            "max_health": None,
            "level": None,
            "items": None,
            "current_gold": None,
            "creep_score": None,
            "game_time": None,
            "setup_time_seconds": getattr(self, "_setup_time_seconds", None),
            "execution_time_seconds": wall_time,
            "execution_game_time_seconds": None,
            "target_max_health": TARGET_MAX_HEALTH,
            "time_limit_seconds": TIME_LIMIT_SECONDS,
            "timing": "execution_wall_time_deadline" if started is not None else "game_time",
        }

        capture_evaluation_state(
            result, data, targets=self.evaluator,
            start_game_time=getattr(self, "_task_start_game_time", None),
            initial_stats=getattr(self, "_initial_stats", None),
        )

        if not is_valid_live_data(data):
            return add_target_results(result, self.evaluator or {})

        player = get_player(data)

        if player is None:
            result["reason"] = "active_player_not_found"
            return add_target_results(result, self.evaluator or {})

        champion = get_champion(player)
        cs, game_time = get_creep_score(player), get_game_time(data)
        max_health = get_max_health(data)
        level, items = player.get("level"), player.get("items")
        gold = data.get("activePlayer", {}).get("currentGold")

        result.update(
            champion=champion or None, creep_score=cs, game_time=game_time,
            max_health=max_health if _valid_number(max_health, positive=True) else None,
            level=level if isinstance(level, int) and not isinstance(level, bool) and level > 0 else None,
            items=copy.deepcopy(items) if isinstance(items, list) and all(
                isinstance(item, dict) for item in items) else None,
            current_gold=gold if _valid_number(gold) else None,
        )

        game = data.get("gameData", {})

        if champion.lower() != CHAMPION_NAME.lower():
            result["reason"] = "wrong_champion"
        elif (game.get("gameMode") != "CLASSIC" or game.get("mapNumber") != 11
              or len(data["allPlayers"]) != 1):
            result["reason"] = "wrong_game_environment"
        elif not is_valid_scores_and_time(cs, game_time) or game_time < start_game_time:
            result["reason"] = "invalid_scores_or_time"
        elif not _valid_number(max_health, positive=True):
            result["reason"] = "invalid_max_health"
        else:
            game_elapsed = game_time - start_game_time
            result["execution_game_time_seconds"] = game_elapsed
            elapsed = wall_time if wall_time is not None else game_elapsed

            if elapsed < TIME_LIMIT_SECONDS:
                result["reason"] = "task_not_finished"
            elif max_health < TARGET_MAX_HEALTH:
                result["reason"] = "target_not_reached"
            else:
                result.update(score=1.0, success=True, reason="target_reached")

        return add_target_results(result, self.evaluator or {})


SionHealthTask = Task004
