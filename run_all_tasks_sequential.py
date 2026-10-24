"""Run all registered tasks in numeric order with PromptAgent.

Example: python run_all_tasks.py --model gpt-6.1-sol --reasoning-effort medium
Task subset: python run_all_tasks.py --start-id 5 --end-id 10
Each task runs through run_single_task() in the current Python process. Gameplay failures
continue to the next task. Setup failures also continue after verified cleanup;
cleanup errors trigger batch-only recovery before the next task.
"""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time

from run import AGENTS, TASKS, require_agent_credentials
from run_single_task import run_single_task
from runner import _validate_limits, experiment_directory


def execute_task(name, args):
    """Construct fresh task/agent/environment objects and call the Python runner."""
    from desktop_env import DesktopEnv
    from dotenv import load_dotenv
    from lolworld_env import LoLWorldClient

    _validate_limits(args.setup_timeout, args.max_steps)
    if args.execution_timeout is not None:
        _validate_limits(args.execution_timeout, args.max_steps)
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    require_agent_credentials(args.agent, args.model)
    env = DesktopEnv()
    agent_options = argparse.Namespace(**vars(args), base_url=None)
    agent = AGENTS[args.agent](agent_options, env)
    task = TASKS[name]()
    if args.check:
        print(f"Configuration ready: agent={args.agent}, task={name}", flush=True)
        return None

    def cleanup_game():
        client = LoLWorldClient()
        return cleanup_batch_game(env, client)

    return run_single_task(
        task, agent, env, result_dir=args.output_dir, agent_name=args.agent,
        setup_timeout=args.setup_timeout, execution_timeout=args.execution_timeout,
        max_steps=args.max_steps, window_title="League of Legends (TM) Client",
        exit_game=cleanup_game, prepare_game=cleanup_game,
    )


def cleanup_batch_game(env, client):
    """Close game windows, recover the client, then clean up residual processes."""
    from lolworld_env import exit_custom_game

    def validate_custom_game():
        phase = client.phase()
        if phase not in {"None", "Lobby", "EndOfGame", "PreEndOfGame", "WaitingForStats"}:
            session = client.request("GET", "/lol-gameflow/v1/session")
            if session.get("gameData", {}).get("isCustomGame") is not True:
                raise RuntimeError("Batch recovery requires a custom game")
        return phase

    def wait_for_window_exit():
        deadline = time.monotonic() + 5
        while env.game_windows():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.5, remaining))
        return True

    phase_before = validate_custom_game()
    ids = env.game_process_ids()
    windows_before = env.game_windows()
    print(f"Game exit check: window_count={len(windows_before)}, "
          f"windows={windows_before}, process_ids={ids}", flush=True)
    forced = []
    if windows_before:
        print("Closing game: attempting Alt+F4", flush=True)
        try:
            env.exit_game()
        except Exception as exc:
            print(f"Alt+F4 attempt failed; checking remaining windows: {exc}", flush=True)
        if not wait_for_window_exit():
            validate_custom_game()
            forced = env.game_process_ids()
            if not set(forced).issubset(set(ids)):
                raise RuntimeError("Game process close failed: a new game process appeared")
            if forced:
                print(f"Game windows remain after 5 seconds: {env.game_windows()}; "
                      f"force closing PIDs {forced}", flush=True)
                pid_list = ",".join(str(int(pid)) for pid in forced)
                try:
                    subprocess.run(
                        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                         f"Get-Process -Id {pid_list} -ErrorAction SilentlyContinue | "
                         "Where-Object { $_.ProcessName -eq 'League of Legends' } | "
                         "Stop-Process -Force -ErrorAction Stop"],
                        capture_output=True, text=True, check=True, timeout=10,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    raise RuntimeError(f"Game process close failed: {exc}") from exc
            if not wait_for_window_exit():
                raise RuntimeError(f"Game window close failed: windows remain after force termination: "
                                   f"{env.game_windows()}")
    print(f"Game windows absent; returning client to home; "
          f"residual process_ids={env.game_process_ids()}", flush=True)
    deadline = time.monotonic() + 120
    attempt = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Client return home failed: recovery deadline exceeded")
        attempt += 1
        print(f"Client return home: attempt {attempt}, "
              f"elapsed {120 - remaining:.1f}/120 seconds, remaining {remaining:.1f} seconds",
              flush=True)
        try:
            result = exit_custom_game(client, timeout=remaining)
            break
        except (RuntimeError, TimeoutError) as exc:
            # A recently disconnected client may temporarily refuse request-lobby.
            if not isinstance(exc, TimeoutError) and not str(exc).startswith("Client refused"):
                raise RuntimeError(f"Client return home failed: {exc}") from exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"Client return home failed: {exc}") from exc
            delay = min(10, remaining)
            print(f"Client not ready ({exc}); elapsed {120 - remaining:.1f}/120 seconds, "
                  f"remaining {remaining:.1f} seconds; retrying in {delay:g} seconds", flush=True)
            time.sleep(delay)
    remaining = env.game_process_ids()
    if not set(remaining).issubset(set(ids)):
        raise RuntimeError("Game process close failed: a new game process appeared")
    print(f"Client returned home; cleaning residual process_ids={remaining}", flush=True)
    result["residual_cleanup"] = env.clear_stale_game(client)
    result.update(process_ids=ids, phase_before=phase_before, windows_before=windows_before)
    if forced:
        result["method"] = "batch_force_exit_recovery"
    elif windows_before:
        result["method"] = "double_alt_f4"
    return result


def recover_failed_exit():
    """Retry the same two-stage cleanup before launching another task."""
    from desktop_env import DesktopEnv
    from lolworld_env import LoLWorldClient

    return cleanup_batch_game(DesktopEnv(), LoLWorldClient())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    last_id = max(int(name.removeprefix("task")) for name in TASKS)
    parser.add_argument("--start-id", type=int, default=1,
                        help="First task number to run, inclusive (default: 1)")
    parser.add_argument("--end-id", type=int, default=last_id,
                        help=f"Last task number to run, inclusive (default: {last_id})")
    parser.add_argument("--agent", choices=["prompt", "prompt-stream"], default="prompt")
    parser.add_argument("--action-space", choices=["pydirectinput", "computer_13"], default="pydirectinput")
    parser.add_argument("--model", default="gpt-6.1-sol")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--max-steps", type=int, default=100)
    parser.add_argument("--setup-timeout", type=float, default=600)
    parser.add_argument("--execution-timeout", type=float,
                        help="Defaults to each task's own execution limit")
    parser.add_argument("--request-timeout", type=float, default=120)
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--check", action="store_true",
                        help="Check selected task configurations without starting games or requesting actions")
    args = parser.parse_args(argv)
    if not 1 <= args.start_id <= args.end_id <= last_id:
        parser.error(f"Task range must satisfy 1 <= start-id <= end-id <= {last_id}")

    task_names = [name for name in sorted(TASKS)
                  if args.start_id <= int(name.removeprefix("task")) <= args.end_id]
    args.output_dir = args.output_dir.resolve()
    experiment_dir = experiment_directory(args.output_dir, agent_name=args.agent,
                                          model=args.model, reasoning_effort=args.reasoning_effort)
    batches_dir = experiment_dir / "batches"
    batches_dir.mkdir(parents=True, exist_ok=True)
    batch_dir = Path(tempfile.mkdtemp(prefix="all-tasks-", dir=batches_dir))
    summary_path = batch_dir / "summary.json"
    summary = {"agent": args.agent, "action_space": args.action_space, "model": args.model,
               "reasoning_effort": args.reasoning_effort,
               "tasks": task_names, "status": "running", "results": []}
    print(f"Batch results: {batch_dir}", flush=True)

    def save_summary():
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    save_summary()
    for index, name in enumerate(task_names, start=1):
        print(f"[{index}/{len(task_names)}] Starting {name}", flush=True)
        record = {"task": name}
        error = None
        try:
            result = execute_task(name, args)
            if args.check:
                record["exit_code"] = 0
            else:
                evaluation = result["evaluation"]
                record.update(evaluation=evaluation, result_dir=result["agent"]["result_dir"],
                              exit_code=0 if evaluation["success"] else 1)
                print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
                print(f"Finished {name}: score={evaluation['score']}, success={evaluation['success']}", flush=True)
                error = evaluation.get("exit_error")
                # Client recovery already used its retry window; do not repeat it.
                if error and not error.startswith("Client return home failed:"):
                    print(f"Recovering failed game exit for {name}: {error}", flush=True)
                    try:
                        record["exit_recovery"] = recover_failed_exit()
                        error = None
                        print("Game exit recovered; continuing batch", flush=True)
                    except Exception as exc:
                        error = f"{error}; batch recovery failed: {exc}"
        except KeyboardInterrupt:
            summary.update(status="interrupted", current_task=name)
            save_summary()
            print("Batch interrupted", flush=True)
            return 130
        except Exception as exc:
            record["exit_code"] = 2
            error = f"{type(exc).__name__}: {exc}"
        if error:
            record["error"] = error
            summary["status"] = "blocked"
        summary["results"].append(record)
        save_summary()
        if error:
            print(f"Batch stopped at {name}: {error}", flush=True)
            return 2

    summary["status"] = "checked" if args.check else "completed"
    if not args.check:
        successes = sum(bool(record["evaluation"]["success"]) for record in summary["results"])
        summary.update(successes=successes, success_rate=successes / len(task_names))
        print(f"Successes: {successes}/{len(task_names)} ({summary['success_rate']:.1%})", flush=True)
    save_summary()
    print(f"Summary: {summary_path}", flush=True)
    return 0 if args.check or summary["successes"] == len(task_names) else 1


if __name__ == "__main__":
    raise SystemExit(main())
