"""Control Darius final-state task."""

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
    add_custom_bot,
    validate_custom_bot_lobby,
    is_valid_live_data,
    is_valid_scores_and_time,
    get_player,
    get_champion,
    get_creep_score,
    get_game_time,
    valid_number,
    valid_count,
    item_counts,
    player_identity,
    validate_roster,
    champion_kill_events,
    player_names,
)

from .base_task import BaseTask
from .subgoals import add_target_results


CHAMPION_ID = 122
CHAMPION_NAME = "Darius"
POSITION = "TOP"
SPELL_D_ID = 6  # Ghost
SPELL_F_ID = 4  # Flash
RUNE_PAGE = {
    "primaryStyleId": 8000,  # Precision
    "subStyleId": 8400,  # Resolve
    "selectedPerkIds": [
        8010,  # Conqueror
        9111,  # Triumph
        9104,  # Legend: Alacrity
        8299,  # Last Stand
        8473,  # Bone Plating
        8242,  # Unflinching
        5005,  # Attack speed
        5008,  # Adaptive force
        5001,  # Scaling health
    ],
}
MAX_DEATHS = 1
TARGET_KILLS = 1
ENEMY_BOT_IDS = (16,)
ENEMY_BOT_NAMES = ("Soraka",)
BOT_DIFFICULTY = "RSBEGINNER"
TIME_LIMIT_SECONDS = 540
SETUP_TIMEOUT_SECONDS = 600
LOBBY_NAME = "Darius: Hemorrhage Duel"


class Task022(BaseTask):
    id = "task_022"
    trajectory = "results"

    instruction = (
        "Control Darius and personally kill the enemy Soraka bot at least once within "
        "9 minutes, with no more than one death. Build Hemorrhage stacks and use Q's "
        "outer edge to sustain, then finish."
    )

    source = "lolworld_env"
    execution_time_limit_seconds = TIME_LIMIT_SECONDS

    evaluator = {
        "type": "live_client_data",
        "champion": CHAMPION_NAME,
        "max_deaths": MAX_DEATHS,
        "min_kills": TARGET_KILLS,
        "enemy_bots": ENEMY_BOT_NAMES,
        "time_limit_seconds": TIME_LIMIT_SECONDS,
        "timing": "game_time",
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

        for champion_id in ENEMY_BOT_IDS:
            add_custom_bot(client, champion_id, difficulty=BOT_DIFFICULTY, position="BOTTOM" if position == "UTILITY" else position)

        for champion_id in ():
            add_custom_bot(client, champion_id, ally=True, difficulty=BOT_DIFFICULTY, position="BOTTOM" if position == "UTILITY" else position)

        validate_custom_bot_lobby(get_lobby(client), enemy_champion_ids=ENEMY_BOT_IDS, ally_champion_ids=(), difficulty=BOT_DIFFICULTY)

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

        validate_live_game(data, champion_name=CHAMPION_NAME, player_count=1 + len(ENEMY_BOT_IDS) + 0, game_mode="CLASSIC")

        if not is_valid_live_data(data) or not isinstance(data.get("activePlayer"), dict) or (not isinstance(data.get("gameData"), dict)):
            raise RuntimeError("Expected valid fresh Live Client Data")

        player = get_player(data)

        if player is None:
            raise RuntimeError("Active player not found")

        if get_champion(player).lower() != CHAMPION_NAME.lower() or data.get("gameData", {}).get("gameMode") != "CLASSIC" or data.get("gameData", {}).get("mapNumber") != 11 or (not validate_roster(data, player, enemy_champions=ENEMY_BOT_NAMES, ally_champions=())):
            raise RuntimeError("Fresh game roster does not match the task configuration")

        cs, game_time = (get_creep_score(player), get_game_time(data))
        deaths = player.get("scores", {}).get("deaths")

        if not is_valid_scores_and_time(cs, game_time) or cs != 0 or (not valid_count(player.get("level"))) or (player["level"] != 1) or (not valid_count(deaths)) or (deaths != 0):
            raise RuntimeError("Expected level 1, zero CS, and zero deaths at setup")

        counts = item_counts(player.get("items"))

        if counts is None:
            raise RuntimeError("Initial inventory was not confirmed")

        events = champion_kill_events(data, start_game_time=0, game_time=game_time)

        if events is None or events:
            raise RuntimeError("Expected valid history without champion kills at setup")

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
            "timing": "game_time",
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

        if game.get("gameMode") != "CLASSIC" or game.get("mapNumber") != 11 or (not validate_roster(data, player, enemy_champions=ENEMY_BOT_NAMES, ally_champions=())):
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

        level, items = (player.get("level"), player.get("items"))
        scores = player.get("scores", {})
        deaths = scores.get("deaths") if isinstance(scores, dict) else None
        active = data.get("activePlayer", {})
        gold = active.get("currentGold") if isinstance(active, dict) else None
        result.update(level=level if valid_count(level) and 1 <= level <= 18 else None, deaths=deaths if valid_count(deaths) else None, items=copy.deepcopy(items), current_gold=gold if valid_number(gold) else None)

        if not valid_count(level) or not 1 <= level <= 18:
            result["reason"] = "invalid_level"
            return add_target_results(result, self.evaluator or {})

        if MAX_DEATHS is not None and (not valid_count(deaths)):
            result["reason"] = "invalid_deaths"
            return add_target_results(result, self.evaluator or {})

        qualifying = []

        events = champion_kill_events(data, start_game_time=start_game_time, game_time=game_time)

        if events is None:
            result["reason"] = "invalid_events"
            return add_target_results(result, self.evaluator or {})

        enemies = [p for p in data["allPlayers"] if p["team"] != player["team"]]
        allies = [p for p in data["allPlayers"] if p["team"] == player["team"] and p is not player]
        local_names = player_names(player)
        enemy_names = set().union(*(player_names(p) for p in enemies))
        ally_names = set().union(*(player_names(p) for p in allies))

        if local_names & enemy_names or local_names & ally_names or enemy_names & ally_names:
            result["reason"] = "ambiguous_event_identity"
            return add_target_results(result, self.evaluator or {})

        for event in events:
            if event["EventTime"] - start_game_time > TIME_LIMIT_SECONDS:
                continue

            if event["VictimName"] not in enemy_names:
                continue

            if TARGET_KILLS and event["KillerName"] in local_names:
                qualifying.append(event)

        result["qualifying_events"] = copy.deepcopy(qualifying)

        if deaths > MAX_DEATHS or len(qualifying) < TARGET_KILLS:
            result["reason"] = "target_not_reached"
        else:
            result.update(score=1.0, success=True, reason="target_reached")

        return add_target_results(result, self.evaluator or {})


DariusKillTask = Task022
