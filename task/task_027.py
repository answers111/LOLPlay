"""Independent Yorick task with API-only scoring."""

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
    event_player_names,
    objective_events,
    turret_identity,
)

from .base_task import BaseTask
from .subgoals import add_target_results


CHAMPION_ID = 83
CHAMPION_NAME = 'Yorick'
POSITION = 'TOP'
SPELL_D_ID = 12  # Teleport
SPELL_F_ID = 4  # Flash
RUNE_PAGE = {
    "primaryStyleId": 8000,  # Precision
    "subStyleId": 8400,  # Resolve
    "selectedPerkIds": [
        8010,  # Conqueror
        9111,  # Triumph
        9104,  # Legend: Alacrity
        8299,  # Last Stand
        8444,  # Second Wind
        8451,  # Overgrowth
        5005,  # Attack speed
        5008,  # Adaptive force
        5001,  # Scaling health
    ],
}
ENEMY_BOT_IDS = ()
ENEMY_BOT_NAMES = ()
ALLY_BOT_IDS = ()
ALLY_BOT_NAMES = ()
BOT_POSITION = 'TOP'
BOT_DIFFICULTY = "RSBEGINNER"
TIME_LIMIT_SECONDS = 1200
SETUP_TIMEOUT_SECONDS = 600
LOBBY_NAME = 'Yorick: Relentless Siege'
TARGET_TURRETS = (('TOP', 'OUTER'), ('TOP', 'INNER'))


class Task027(BaseTask):
    id = "task_027"
    trajectory = "results"

    instruction = (
        'Control Yorick and destroy the enemy top outer turret, then the top inner turret '
        'within 20 minutes. Use summons and pushing waves to maintain pressure, then finish.'
    )

    source = "lolworld_env"
    execution_time_limit_seconds = TIME_LIMIT_SECONDS

    evaluator = {
        'type': 'live_client_data',
        'champion': 'Yorick',
        'enemy_bots': (),
        'ally_bots': (),
        'time_limit_seconds': 1200,
        'timing': 'game_time',
        'turrets': (('TOP', 'OUTER'), ('TOP', 'INNER')),
        'ordered': True,
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
            add_custom_bot(client, champion_id, difficulty=BOT_DIFFICULTY, position=BOT_POSITION)

        for champion_id in ALLY_BOT_IDS:
            add_custom_bot(client, champion_id, ally=True, difficulty=BOT_DIFFICULTY, position=BOT_POSITION)

        validate_custom_bot_lobby(
            get_lobby(client), enemy_champion_ids=ENEMY_BOT_IDS,
            ally_champion_ids=ALLY_BOT_IDS, difficulty=BOT_DIFFICULTY,
        )

        start_champion_select(client)
        wait_for_phase(client, "ChampSelect", timeout=deadline - time.monotonic())

        root, action = wait_for_pick_action(client, timeout=deadline - time.monotonic())
        select_champion(client, CHAMPION_ID, action_id=action["id"], api_root=root)

        set_summoner_spells(client, SPELL_D_ID, SPELL_F_ID, api_root=root)
        set_runes(
            client, primary_style_id=RUNE_PAGE["primaryStyleId"],
            sub_style_id=RUNE_PAGE["subStyleId"],
            selected_perk_ids=RUNE_PAGE["selectedPerkIds"],
        )

        lock_champion(client, CHAMPION_ID, action_id=action["id"], api_root=root)
        set_default_skin(client, CHAMPION_ID, api_root=root)

        wait_for_phase(client, "InProgress", timeout=deadline - time.monotonic())
        data = wait_for_live_game(client, timeout=deadline - time.monotonic())

        validate_live_game(
            data, champion_name=CHAMPION_NAME,
            player_count=1 + len(ENEMY_BOT_IDS) + len(ALLY_BOT_IDS), game_mode="CLASSIC",
        )

        if not is_valid_live_data(data):
            raise RuntimeError("Expected valid fresh Live Client Data")

        player = get_player(data)

        if player is None:
            raise RuntimeError("Active player not found")

        game = data.get("gameData", {})

        if (get_champion(player).lower() != CHAMPION_NAME.lower()
                or game.get("gameMode") != "CLASSIC" or game.get("mapNumber") != 11
                or not validate_roster(data, player, enemy_champions=ENEMY_BOT_NAMES,
                                       ally_champions=ALLY_BOT_NAMES)):
            raise RuntimeError("Fresh game roster does not match the task configuration")

        cs, game_time = (get_creep_score(player), get_game_time(data))
        deaths = player.get("scores", {}).get("deaths")

        if (not is_valid_scores_and_time(cs, game_time) or cs != 0
                or not valid_count(player.get("level")) or player["level"] != 1
                or not valid_count(deaths) or deaths != 0):
            raise RuntimeError("Expected level 1, zero CS, and zero deaths at setup")

        counts = item_counts(player.get("items"))

        if counts is None:
            raise RuntimeError("Initial inventory was not confirmed")

        kills = champion_kill_events(data, start_game_time=0, game_time=game_time)
        objectives = objective_events(data, start_game_time=0, game_time=game_time)

        if kills is None or objectives is None or kills or objectives:
            raise RuntimeError("Expected valid fresh history without kills or destroyed towers")

        if event_player_names(data["allPlayers"]) is None:
            raise RuntimeError("Ambiguous event names in the roster")

        if time.monotonic() >= deadline:
            raise TimeoutError("Task preparation exceeded its deadline")

        self._initial_roster = sorted((player_identity(p) for p in data["allPlayers"]))
        self._task_start_game_time = game_time
        finished = time.monotonic()
        self._setup_time_seconds = finished - started
        self._task_started_at = finished

    def evaluate(self, env=None):
        """Score API evidence; connection errors propagate to the runner."""
        evaluated_at = time.monotonic()
        started = getattr(self, "_task_started_at", None)
        start = getattr(self, "_task_start_game_time", None)
        start = 0 if start is None else start
        data = (env.get_live_data() if env is not None
                and callable(getattr(env, "get_live_data", None)) else get_live_data())
        wall_time = evaluated_at - started if started is not None else None

        result = {
            "score": 0.0, "success": False, "reason": "invalid_live_data",
            "champion": None, "level": None, "creep_score": None, "deaths": None,
            "game_time": None, "current_gold": None, "qualifying_events": [],
            "setup_time_seconds": getattr(self, "_setup_time_seconds", None),
            "execution_time_seconds": wall_time, "execution_game_time_seconds": None,
            "time_limit_seconds": TIME_LIMIT_SECONDS,
            "targets": copy.deepcopy(self.evaluator), "timing": self.evaluator["timing"],
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
        result.update(champion=champion, creep_score=cs, game_time=game_time)

        if champion.lower() != CHAMPION_NAME.lower():
            result["reason"] = "wrong_champion"
            return add_target_results(result, self.evaluator or {})

        game = data.get("gameData", {})

        if (game.get("gameMode") != "CLASSIC" or game.get("mapNumber") != 11
                or not validate_roster(data, player, enemy_champions=ENEMY_BOT_NAMES,
                                       ally_champions=ALLY_BOT_NAMES)):
            result["reason"] = "wrong_game_environment"
            return add_target_results(result, self.evaluator or {})

        roster = sorted(player_identity(p) for p in data["allPlayers"])
        initial_roster = getattr(self, "_initial_roster", None)

        if initial_roster is not None and roster != initial_roster:
            result["reason"] = "wrong_game_environment"
            return add_target_results(result, self.evaluator or {})

        if (not valid_number(start) or not is_valid_scores_and_time(cs, game_time)
                or game_time < start):
            result["reason"] = "invalid_scores_or_time"
            return add_target_results(result, self.evaluator or {})

        elapsed = game_time - start
        result["execution_game_time_seconds"] = elapsed
        level = player.get("level")
        deaths = player.get("scores", {}).get("deaths")
        gold = data["activePlayer"].get("currentGold")
        result.update(level=level, deaths=deaths,
                      current_gold=gold if valid_number(gold) else None)

        if not valid_count(level) or not 1 <= level <= 18:
            result["reason"] = "invalid_level"
            return add_target_results(result, self.evaluator or {})

        events = objective_events(data, start_game_time=start, game_time=game_time)

        if events is None:
            result["reason"] = "invalid_events"
            return add_target_results(result, self.evaluator or {})

        enemy_team = "CHAOS" if player["team"] == "ORDER" else "ORDER"
        towers = {target: [] for target in TARGET_TURRETS}

        for event in events:
            if event["EventName"] != "TurretKilled":
                continue

            identity = turret_identity(event["TurretKilled"])

            if identity is not None and identity[0] == enemy_team and identity[1:] in towers:
                towers[identity[1:]].append(event)

        if any(len(matches) > 1 for matches in towers.values()):
            result["reason"] = "duplicate_turret_evidence"
            return add_target_results(result, self.evaluator or {})

        evidence = [matches[0] for matches in towers.values() if matches]
        result["turret_events"] = copy.deepcopy(evidence)
        result["qualifying_events"] = copy.deepcopy(evidence)
        reached = (len(evidence) == len(TARGET_TURRETS)
                   and all(e["EventTime"] - start <= TIME_LIMIT_SECONDS for e in evidence))

        if reached:
            reached = evidence[0]["EventTime"] < evidence[1]["EventTime"]

        result.update(score=1.0 if reached else 0.0, success=reached,
                      reason="target_reached" if reached else "target_not_reached")
        return add_target_results(result, self.evaluator or {})


YorickSiegeTask = Task027
