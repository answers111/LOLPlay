"""Independent Talon task with API-only scoring."""

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
)

from .base_task import BaseTask
from .subgoals import add_target_results


CHAMPION_ID = 91
CHAMPION_NAME = 'Talon'
POSITION = 'MIDDLE'
SPELL_D_ID = 14  # Ignite
SPELL_F_ID = 4  # Flash
RUNE_PAGE = {
    "primaryStyleId": 8100,  # Domination
    "subStyleId": 8200,  # Sorcery
    "selectedPerkIds": [
        8112,  # Electrocute
        8143,  # Sudden Impact
        8140,  # Grisly Mementos
        8135,  # Treasure Hunter
        8275,  # Nimbus Cloak
        8237,  # Scorch
        5008,  # Adaptive force
        5008,  # Adaptive force
        5001,  # Scaling health
    ],
}
ENEMY_BOT_IDS = (22,)
ENEMY_BOT_NAMES = ('Ashe',)
ALLY_BOT_IDS = ()
ALLY_BOT_NAMES = ()
BOT_POSITION = 'MIDDLE'
BOT_DIFFICULTY = "RSBEGINNER"
TIME_LIMIT_SECONDS = 300
SETUP_TIMEOUT_SECONDS = 600
LOBBY_NAME = 'Talon: Early Opportunity'
MAX_DEATHS = 0
TARGET_KILLS = 1


class Task030(BaseTask):
    id = "task_030"
    trajectory = "results"

    instruction = (
        'Control Talon against Ashe and personally secure one kill within 5 minutes without '
        'dying. Stack your passive through a short ability sequence and choose an early '
        'opening, then finish.'
    )

    source = "lolworld_env"
    execution_time_limit_seconds = TIME_LIMIT_SECONDS

    evaluator = {
        'type': 'live_client_data',
        'champion': 'Talon',
        'enemy_bots': ('Ashe',),
        'ally_bots': (),
        'time_limit_seconds': 300,
        'timing': 'game_time',
        'min_kills': 1,
        'max_deaths': 0,
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

        if not valid_count(deaths):
            result["reason"] = "invalid_deaths"
            return add_target_results(result, self.evaluator or {})

        events = champion_kill_events(data, start_game_time=start, game_time=game_time)
        names = event_player_names(data["allPlayers"])

        if events is None:
            result["reason"] = "invalid_events"
            return add_target_results(result, self.evaluator or {})

        if names is None:
            result["reason"] = "ambiguous_event_identity"
            return add_target_results(result, self.evaluator or {})

        personal, assisted, victims = [], [], set()

        for event in events:
            if event["EventTime"] - start > TIME_LIMIT_SECONDS:
                continue

            killer = names.get(event["KillerName"])
            victim = names.get(event["VictimName"])
            assisters = [names.get(name) for name in event["Assisters"]]

            if (victim is None or any(p is None for p in assisters)
                    or killer is victim or any(p is killer or p is victim for p in assisters)
                    or (killer is not None and killer["team"] == victim["team"])
                    or len({id(p) for p in assisters}) != len(assisters)):
                result["reason"] = "invalid_event_attribution"
                return add_target_results(result, self.evaluator or {})

            if victim["team"] == player["team"]:
                continue

            if killer is player:
                personal.append(event)
                victims.add(player_identity(victim))
            elif (killer is not None and killer["team"] == player["team"]
                  and any(p is player for p in assisters)):
                assisted.append(event)

        qualifying = personal + assisted
        result.update(personal_kills=len(personal), ally_assists=len(assisted),
                      participations=len(qualifying), killed_enemies=sorted(victims),
                      qualifying_events=copy.deepcopy(qualifying))
        reached = len(personal) >= TARGET_KILLS and deaths <= MAX_DEATHS
        result.update(score=1.0 if reached else 0.0, success=reached,
                      reason="target_reached" if reached else "target_not_reached")
        return add_target_results(result, self.evaluator or {})


TalonEarlyKillTask = Task030
