"""Run one registered LoL task using the OSWorld 2.0 episode lifecycle.

Reference: https://github.com/xlang-ai/OSWorld-V2/blob/main/lib_run_single.py
The shared runner resets the agent, gets observations, executes predict/step
batches, and saves trajectories, final screenshots and real task evaluation.
LoL task.setup() prepares the game in place of OSWorld's VM env.reset().
"""

import argparse
import json
from pathlib import Path

import run
from runner import _validate_limits, run_task


def run_single_task(task, agent, env, *, result_dir=None, setup_timeout=600,
                    execution_timeout=None, max_steps=100, position=None,
                    window_title=None, exit_game=None, agent_name=None, prepare_game=None):
    """Prepare, run and evaluate one task with an already constructed agent/env.

    Return {"agent": execution_result, "evaluation": task_evaluation}. DONE
    ends execution; success and score come from task.evaluate(). Outputs go to
    result_dir / experiment-<agent>_<model>_<effort> / <task.id> / run-*;
    result_dir defaults to task.trajectory or results. Evaluation is persisted
    before exit_game is called. Deadlines and step limits use the shared runner.
    """
    return run_task(
        task, agent, env, result_dir=result_dir, setup_timeout=setup_timeout,
        execution_timeout=execution_timeout, max_steps=max_steps, position=position,
        window_title=window_title, exit_game=exit_game, agent_name=agent_name,
        prepare_game=prepare_game,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=sorted(run.AGENTS), default="responses")
    parser.add_argument("--action-space", choices=["pydirectinput", "computer_13"], default="pydirectinput",
                        help="PromptAgent Python code or OSWorld computer_13 JSON actions")
    parser.add_argument("--task", choices=sorted(run.TASKS), default="task001")
    parser.add_argument("--model")
    parser.add_argument("--base-url", help="API endpoint; overrides OPENAI_BASE_URL or ANTHROPIC_BASE_URL for the selected provider")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--max-tokens", type=int, default=None,
                        help="PromptAgent output token cap (includes reasoning); API default if omitted")
    parser.add_argument("--max-trajectory-length", type=int, default=3,
                        help="PromptAgent recent screenshot/response pairs; 0 disables history")
    parser.add_argument("--wait-seconds", type=float, default=1.0,
                        help="PromptAgent WAIT duration")
    parser.add_argument("--request-timeout", type=float, default=120.0,
                        help="PromptAgent API timeout per request attempt in seconds")
    parser.add_argument("--env-file", type=Path, default=Path(__file__).with_name(".env"))
    parser.add_argument("--setup-timeout", type=float, default=600)
    parser.add_argument("--execution-timeout", type=float, default=None,
                        help="Execution cap in seconds; defaults to the selected task's limit")
    parser.add_argument("--max-steps", type=int, default=100)
    parser.add_argument("--output-dir")
    parser.add_argument("--position", choices=["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY", "FILL"])
    parser.add_argument("--defense", choices=["armor", "magic_resist"], default="armor",
                        help="Requested defense equipment for task008")
    parser.add_argument("--check", action="store_true", help="Validate local config without launching a game")
    args = parser.parse_args(argv)
    if args.action_space == "computer_13" and args.agent not in {"prompt", "prompt-stream"}:
        parser.error("--action-space computer_13 requires --agent prompt or prompt-stream")
    try:
        _validate_limits(args.setup_timeout, args.max_steps)
        if args.execution_timeout is not None:
            _validate_limits(args.execution_timeout, args.max_steps)
        from dotenv import load_dotenv
        from desktop_env import DesktopEnv

        load_dotenv(args.env_file, override=False)
        # Validate the Responses credentials before importing desktop backends.
        run.require_agent_credentials(args.agent, args.model)
        env = DesktopEnv()
        agent = run.AGENTS[args.agent](args, env)
        task_options = {"defense": args.defense} if args.task == "task008" else {}
        task = run.TASKS[args.task](**task_options)
    except (RuntimeError, ImportError, ValueError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}, ensure_ascii=False))
        return 2
    if args.check:
        print(f"Configuration ready: agent={args.agent}, task={args.task}")
        return 0
    from lolworld_env import LoLWorldClient, exit_custom_game

    def cleanup_game():
        client = LoLWorldClient()
        try:
            exit_result = exit_custom_game(client, leave_game=env.exit_game)
        except Exception:
            # A detached game can remain after the client already returned home.
            if client.phase() != "None":
                raise
            exit_result = {"method": "client_already_home", "phase": "None"}
        residual = env.clear_stale_game(client)
        if isinstance(residual, dict):
            exit_result["residual_cleanup"] = residual
        return exit_result

    print(f"Preparing {args.task} with {args.agent}", flush=True)
    result = run_single_task(
        task, agent, env, result_dir=args.output_dir, agent_name=args.agent,
        setup_timeout=args.setup_timeout, execution_timeout=args.execution_timeout,
        max_steps=args.max_steps, position=args.position,
        window_title="League of Legends (TM) Client",
        exit_game=cleanup_game, prepare_game=cleanup_game,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["evaluation"]["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
