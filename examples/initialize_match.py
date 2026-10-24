"""Caller-owned workflow. Install the package, then run with --champion-id 103."""
import argparse
from lolworld_env import (
    LoLWorldClient, create_practice_lobby, start_champion_select, wait_for_phase,
    wait_for_pick_action, select_champion, lock_champion,
    wait_for_live_game, validate_live_game,
)


def initialize_match(champion_id, *, lobby_name="External Practice", timeout=180):
    import time
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if isinstance(champion_id, bool) or not isinstance(champion_id, int) or champion_id <= 0:
        raise ValueError("champion_id must be a positive integer")
    deadline = time.monotonic() + timeout
    client = LoLWorldClient()
    create_practice_lobby(client, lobby_name=lobby_name)
    wait_for_phase(client, "Lobby", timeout=deadline - time.monotonic())
    start_champion_select(client)
    wait_for_phase(client, "ChampSelect", timeout=deadline - time.monotonic())
    root, action = wait_for_pick_action(client, timeout=deadline - time.monotonic())
    select_champion(client, champion_id, action_id=action["id"], api_root=root)
    lock_champion(client, champion_id, action_id=action["id"], api_root=root)
    wait_for_phase(client, "InProgress", timeout=deadline - time.monotonic())
    data = wait_for_live_game(client, timeout=deadline - time.monotonic())
    return validate_live_game(data, player_count=1, game_mode="PRACTICETOOL")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--champion-id", type=int, required=True)
    parser.add_argument("--lobby-name", default="External Practice")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    print(initialize_match(args.champion_id, lobby_name=args.lobby_name, timeout=args.timeout))
