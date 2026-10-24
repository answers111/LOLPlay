"""Control Caitlyn and reach 30 CS within ten game minutes after setup."""

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
)

from .base_task import BaseTask
from .subgoals import add_target_results


CHAMPION_ID = 51
CHAMPION_NAME = "Caitlyn"
POSITION = "BOTTOM"
SPELL_D_ID = 21  # Barrier
SPELL_F_ID = 4  # Flash
RUNE_PAGE = {
    "primaryStyleId": 8000,  # Precision
    "subStyleId": 8200,  # Sorcery
    "selectedPerkIds": [
        8021,  # Fleet Footwork
        9111,  # Triumph
        9104,  # Legend: Alacrity
        8014,  # Coup de Grace
        8233,  # Absolute Focus
        8236,  # Gathering Storm
        5005,  # Attack speed
        5008,  # Adaptive force
        5001,  # Scaling health
    ],
}
TARGET_CS = 30
TIME_LIMIT_SECONDS = 600
SETUP_TIMEOUT_SECONDS = 600
LOBBY_NAME = f"{CHAMPION_NAME}: {TARGET_CS} CS in {TIME_LIMIT_SECONDS / 60:g} minutes"


class Task001(BaseTask):
    id = "task_001"
    trajectory = "results"

    instruction = (
        f"Control {CHAMPION_NAME} and achieve the highest possible creep score "
        "(last hits on enemy minions) "
        f"within {TIME_LIMIT_SECONDS / 60:g} minutes."
    )

    source = "lolworld_env"

    evaluator = {
        "type": "live_client_data",
        "champion": CHAMPION_NAME,
        "target_cs": TARGET_CS,
        "time_limit_seconds": TIME_LIMIT_SECONDS,
    }

    def setup(self, setup_controller=None, *, timeout=SETUP_TIMEOUT_SECONDS,
              position=POSITION):
        """Measure preparation separately and start the task clock when ready.

        timeout limits preparation wall time. Both stage durations use wall time.
        """
        self._setup_time_seconds = None
        self._task_started_at = None
        self._task_start_game_time = None
        setup_started = time.monotonic()
        client = getattr(setup_controller, "client", None)

        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")

        setup_deadline = setup_started + timeout

        if client is None:
            client = LoLWorldClient()

        create_custom_lobby(
            client,
            lobby_name=LOBBY_NAME,
            position=position,
        )
        set_normal_skill_cast(client)
        wait_for_phase(client, "Lobby", timeout=setup_deadline - time.monotonic())
        validate_custom_lobby(get_lobby(client))

        start_champion_select(client)
        wait_for_phase(client, "ChampSelect", timeout=setup_deadline - time.monotonic())

        root, action = wait_for_pick_action(client, timeout=setup_deadline - time.monotonic())
        select_champion(client, CHAMPION_ID, action_id=action["id"], api_root=root)

        set_summoner_spells(client, SPELL_D_ID, SPELL_F_ID, api_root=root)
        set_runes(client, primary_style_id=RUNE_PAGE["primaryStyleId"],
                  sub_style_id=RUNE_PAGE["subStyleId"],
                  selected_perk_ids=RUNE_PAGE["selectedPerkIds"])

        lock_champion(client, CHAMPION_ID, action_id=action["id"], api_root=root)
        set_default_skin(client, CHAMPION_ID, api_root=root)

        wait_for_phase(client, "InProgress", timeout=setup_deadline - time.monotonic())
        data = wait_for_live_game(client, timeout=setup_deadline - time.monotonic())

        validate_live_game(
            data,
            champion_name=CHAMPION_NAME,
            player_count=1,
            game_mode="CLASSIC",
        )
        if data.get("gameData", {}).get("mapNumber") != 11:
            raise RuntimeError("Expected Summoner's Rift (map 11)")

        player = data["allPlayers"][0]
        cs = get_creep_score(player)
        game_time = get_game_time(data)

        if not is_valid_scores_and_time(cs, game_time) or cs != 0:
            raise RuntimeError(f"Expected a fresh {CHAMPION_NAME} game with zero CS and valid game time")

        self._task_start_game_time = game_time
        setup_finished = time.monotonic()
        self._setup_time_seconds = setup_finished - setup_started
        self._task_started_at = setup_finished

    def evaluate(self, env=None):
        """Use env.get_live_data() when provided, otherwise read the local API.

        Execution wall time runs from setup completion to this evaluation call.
        Game time is tracked separately for gameplay rules. API failures
        propagate to the runner instead of being reported as gameplay failure.
        """
        evaluated_at = time.monotonic()
        task_started_at = getattr(self, "_task_started_at", None)
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
            "creep_score": None,
            "game_time": None,
            "setup_time_seconds": getattr(self, "_setup_time_seconds", None),
            "execution_time_seconds": (
                evaluated_at - task_started_at if task_started_at is not None else None
            ),
            "execution_game_time_seconds": None,
            "target_cs": TARGET_CS,
            "time_limit_seconds": TIME_LIMIT_SECONDS,
        }

        capture_evaluation_state(
            result, data, targets=self.evaluator,
            start_game_time=getattr(self, "_task_start_game_time", None),
            initial_stats=getattr(self, "_initial_stats", None),
        )

        if not is_valid_live_data(data):
            return add_target_results(result, self.evaluator or {})

        players = data.get("allPlayers")
        game = data.get("gameData", {})

        player = get_player(data)
        if player is None:
            result["reason"] = "active_player_not_found"
            return add_target_results(result, self.evaluator or {})

        champion = get_champion(player)
        cs = get_creep_score(player)
        game_time = get_game_time(data)

        result.update(champion=champion or None, creep_score=cs, game_time=game_time)

        start_game_time = getattr(self, "_task_start_game_time", None)
        if start_game_time is None:
            start_game_time = 0
            
        if is_valid_scores_and_time(cs, game_time):
            result["execution_game_time_seconds"] = game_time - start_game_time

        if champion.lower() != CHAMPION_NAME.lower():
            result["reason"] = "wrong_champion"
        elif (game.get("gameMode") != "CLASSIC"
              or game.get("mapNumber") != 11 or len(players) != 1):
            result["reason"] = "wrong_game_environment"
        elif not is_valid_scores_and_time(cs, game_time):
            result["reason"] = "invalid_scores_or_time"
        elif result["execution_game_time_seconds"] < 0:
            result["reason"] = "invalid_scores_or_time"
        elif cs < TARGET_CS:
            result["reason"] = "target_not_reached"
        else:
            result.update(score=1.0, success=True, reason="target_reached")

        return add_target_results(result, self.evaluator or {})


CaitlynFarmingTask = Task001
