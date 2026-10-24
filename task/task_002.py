"""Develop Lee Sin in the jungle and kill the first dragon in ten minutes."""

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


CHAMPION_ID = 64
CHAMPION_NAME = "LeeSin"
POSITION = "JUNGLE"
SPELL_D_ID = 11  # Smite
SPELL_F_ID = 4  # Flash
RUNE_PAGE = {
    "primaryStyleId": 8000,  # Precision
    "subStyleId": 8300,  # Inspiration
    "selectedPerkIds": [
        8010,  # Conqueror
        9111,  # Triumph
        9104,  # Legend: Alacrity
        8014,  # Coup de Grace
        8304,  # Magical Footwear
        8347,  # Cosmic Insight
        5005,  # Attack speed
        5008,  # Adaptive force
        5001,  # Scaling health
    ],
}
TIME_LIMIT_SECONDS = 600
SETUP_TIMEOUT_SECONDS = 600
LOBBY_NAME = "Lee Sin: first dragon in 10 minutes"


def _nonnegative_number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= 0)


def get_events(data):
    """Read full event history; absent evidence is not an empty history.

    Schema: https://static.developer.riotgames.com/docs/lol/liveclientdata_events.json
    """
    container = data.get("events")
    events = container.get("Events") if isinstance(container, dict) else None
    if not isinstance(events, list) or not all(isinstance(event, dict) for event in events):
        return None
    return events


class Task002(BaseTask):
    id = "task_002"
    trajectory = "results"

    instruction = (
        "Control Lee Sin (the Blind Monk). Farm jungle camps to gain as much level "
        "and equipment progress as possible, and personally kill the first elemental "
        "dragon within 10 minutes. "
    )

    source = "lolworld_env"

    evaluator = {
        "type": "live_client_data",
        "champion": CHAMPION_NAME,
        "target": "first_elemental_dragon",
        "time_limit_seconds": TIME_LIMIT_SECONDS,
    }

    def setup(self, setup_controller=None, *, timeout=SETUP_TIMEOUT_SECONDS,
              position=POSITION):
        """Prepare a fresh solo game, then start the independent task clock."""
        self._setup_time_seconds = None
        self._task_started_at = None
        self._task_start_game_time = None
        setup_started = time.monotonic()

        if not _nonnegative_number(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")

        deadline = setup_started + timeout

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
                or player.get("level") != 1 or isinstance(player.get("level"), bool)):
            raise RuntimeError("Expected a fresh LeeSin game at level 1 with zero CS and valid time")

        events = get_events(data)

        if events is None or any(event.get("EventName") == "DragonKill" for event in events):
            raise RuntimeError("Expected valid events and no dragon kills at setup")

        self._task_start_game_time = game_time
        setup_finished = time.monotonic()
        self._setup_time_seconds = setup_finished - setup_started
        self._task_started_at = setup_finished

    def evaluate(self, env=None):
        """Score the first dragon's timestamp and ownership; API errors propagate.

        Level, items and CS are progress metrics, with no invented minimums.
        A late evaluation can prove an on-time kill through its event timestamp.
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

        result = {
            "score": 0.0,
            "success": False,
            "reason": "invalid_live_data",
            "champion": None,
            "level": None,
            "items": None,
            "current_gold": None,
            "creep_score": None,
            "game_time": None,
            "first_dragon": None,
            "dragon_kill_game_time": None,
            "dragon_kill_execution_time_seconds": None,
            "setup_time_seconds": getattr(self, "_setup_time_seconds", None),
            "execution_time_seconds": (
                evaluated_at - started if started is not None else None
            ),
            "execution_game_time_seconds": None,
            "time_limit_seconds": TIME_LIMIT_SECONDS,
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
        level = player.get("level")
        items = player.get("items")
        gold = data.get("activePlayer", {}).get("currentGold")

        result.update(
            champion=champion or None, creep_score=cs, game_time=game_time,
            level=level if isinstance(level, int) and not isinstance(level, bool) and level > 0 else None,
            items=copy.deepcopy(items) if isinstance(items, list) and all(
                isinstance(item, dict) for item in items) else None,
            current_gold=gold if _nonnegative_number(gold) else None,
        )

        game = data.get("gameData", {})

        if champion.lower() != CHAMPION_NAME.lower():
            result["reason"] = "wrong_champion"
            return add_target_results(result, self.evaluator or {})

        if (game.get("gameMode") != "CLASSIC" or game.get("mapNumber") != 11
                or len(data["allPlayers"]) != 1):
            result["reason"] = "wrong_game_environment"
            return add_target_results(result, self.evaluator or {})

        if not is_valid_scores_and_time(cs, game_time) or game_time < start_game_time:
            result["reason"] = "invalid_scores_or_time"
            return add_target_results(result, self.evaluator or {})

        elapsed = game_time - start_game_time
        result["execution_game_time_seconds"] = elapsed

        events = get_events(data)

        if events is None:
            result["reason"] = "invalid_events"
            return add_target_results(result, self.evaluator or {})

        dragons = [event for event in events if event.get("EventName") == "DragonKill"]

        if any(not _nonnegative_number(event.get("EventTime"))
               or event["EventTime"] > game_time for event in dragons):
            result["reason"] = "invalid_dragon_event"
            return add_target_results(result, self.evaluator or {})

        if not dragons:
            result["reason"] = "target_not_reached"
            return add_target_results(result, self.evaluator or {})

        first = min(dragons, key=lambda event: event["EventTime"])

        if sum(event["EventTime"] == first["EventTime"] for event in dragons) != 1:
            result["reason"] = "invalid_dragon_event"
            return add_target_results(result, self.evaluator or {})

        kill_time = first["EventTime"]
        result.update(first_dragon=copy.deepcopy(first), dragon_kill_game_time=kill_time,
                      dragon_kill_execution_time_seconds=kill_time - start_game_time)

        if (not isinstance(first.get("DragonType"), str) or not first["DragonType"]
                or not isinstance(first.get("KillerName"), str) or not first["KillerName"]):
            result["reason"] = "invalid_dragon_event"
        elif first["DragonType"].lower() == "elder":
            result["reason"] = "not_elemental_dragon"
        elif kill_time < start_game_time:
            result["reason"] = "dragon_killed_before_task"
        elif kill_time - start_game_time > TIME_LIMIT_SECONDS:
            result["reason"] = "execution_budget_exhausted"
        elif first["KillerName"] not in {
                player.get("riotId"), player.get("riotIdGameName"), player.get("summonerName")}:
            result["reason"] = "first_dragon_not_killed_by_player"
        else:
            result.update(score=1.0, success=True, reason="target_reached")

        return add_target_results(result, self.evaluator or {})


LeeSinJungleTask = Task002
