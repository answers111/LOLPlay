"""Model-independent task lifecycle, agent loop, trajectory and evaluation."""

import json
import math
import re
from datetime import datetime
from pathlib import Path
import tempfile
import threading
import time


def _directory_component(value):
    """Make a model/configuration label safe as one Windows directory name."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).strip(" .")[:100]
    name = name.rstrip(" .") or "unknown"
    if name.split(".")[0].upper() in {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        name = "_" + name
    return name


def _validate_limits(timeout, max_steps):
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
        raise ValueError("max_steps must be a positive integer")


def experiment_directory(output_dir, *, agent_name=None, model=None, reasoning_effort=None):
    """Return the shared parent directory for one experiment configuration."""
    labels = [label for label in (agent_name, model, reasoning_effort)
              if isinstance(label, str) and label]
    experiment = "experiment-" + ("_".join(_directory_component(label) for label in labels)
                                  or "default")
    return Path(output_dir) / experiment


def _save_task_result(root, agent_result, evaluation):
    """Persist the same combined payload returned to callers and printed by CLI."""
    payload = {"agent": agent_result, "evaluation": evaluation}
    (root / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run_agent(agent, env, instruction, *, result_dir="results", timeout=600,
              max_steps=100, stop_when=None, window_title=None):
    """Run any predict(instruction, obs) agent against the shared environment.

    Agents can execute through their own step(action), returning four or five
    fields, or return Python strings to be executed through env.step directly.
    No model request or model-specific action conversion lives in this loop.
    """
    _validate_limits(timeout, max_steps)
    parent = Path(result_dir).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"run-{datetime.now():%Y%m%d-%H%M%S}-", dir=parent))
    trace_path = root / "trajectory.jsonl"
    model_output_path = root / "model_output.jsonl"
    started = time.monotonic()
    reason, answer, stopped, response_count = "max_steps", "", False, 0

    def should_stop():
        return time.monotonic() - started >= timeout or bool(stop_when and stop_when())

    with trace_path.open("w", encoding="utf-8") as trace, model_output_path.open("w", encoding="utf-8") as model_output:
        def log(event):
            trace.write(json.dumps(event, ensure_ascii=False) + "\n")
            trace.flush()

        try:
            if window_title is not None:
                env.bind_window(window_title)
            if callable(getattr(env, "center_mouse", None)):
                env.center_mouse()
            if callable(getattr(agent, "reset", None)):
                agent.reset()
            obs = env.get_obs()
            for step in range(max_steps):
                if should_stop():
                    reason, stopped = "execution_budget_exhausted", True
                    break
                print(f"Step {step + 1}: requesting actions", flush=True)
                try:
                    predict_info, actions = agent.predict(instruction, obs)
                finally:
                    drain = getattr(type(agent), "drain_request_diagnostics", None)
                    if callable(drain):
                        for diagnostic in drain(agent):
                            log({"step": step + 1, "request_diagnostic": diagnostic})
                response_count += 1
                answer = (predict_info.get("response", "")
                          if isinstance(predict_info, dict) else str(predict_info))
                output = (predict_info.get("model_output", answer)
                          if isinstance(predict_info, dict) else answer)
                model_output.write(json.dumps({"turn": step + 1, "response": output},
                                              ensure_ascii=False) + "\n")
                model_output.flush()
                log({"step": step + 1, "response": answer,
                     "model_usage": predict_info.get("model_usage", {})
                     if isinstance(predict_info, dict) else {}})
                if not actions:
                    reason = "no_actions"
                    break
                terminal = False
                for index, action in enumerate(actions):
                    if should_stop():
                        reason, stopped = "execution_budget_exhausted", True
                        break
                    kind = action.get("action_type") if isinstance(action, dict) else action
                    log({"step": step + 1, "action": action})
                    if kind in {"DONE", "FAIL"}:
                        reason = "done" if kind == "DONE" else "infeasible"
                        terminal = True
                        break
                    if isinstance(action, dict) and action.get("pending_checks"):
                        raise RuntimeError("Computer call requires additional safety acknowledgement")
                    if callable(getattr(agent, "step", None)):
                        outcome = agent.step(action)
                    else:
                        code = action.get("action") if isinstance(action, dict) else action
                        outcome = env.step(code)
                    obs, reward, terminated, info = outcome[:4]
                    screenshot_name = None
                    next_action = actions[index + 1] if index + 1 < len(actions) else None
                    next_kind = (next_action.get("action_type")
                                 if isinstance(next_action, dict) else next_action)
                    # Save the final observation of the turn, including a terminal
                    # marker that stops the loop without executing another action.
                    if index == len(actions) - 1 or terminated or next_kind in ("DONE", "FAIL"):
                        screenshot_name = f"step-{step + 1:03d}-{index:02d}.png"
                        (root / screenshot_name).write_bytes(obs["screenshot"])
                    log({"step": step + 1, "reward": reward, "terminated": terminated,
                         "info": info, "screenshot_file": screenshot_name})
                    if terminated:
                        reason, terminal = "environment_terminated", True
                        break
                if stopped or terminal:
                    break
        except Exception as exc:
            reason = "execution_error"
            answer = f"{type(exc).__name__}: {exc}"
            log({"error": answer})
    result = {"ok": reason == "done", "reason": reason, "answer": answer,
              "stopped_by_task": stopped, "response_count": response_count,
              "duration_seconds": time.monotonic() - started,
              "result_dir": str(root), "trace_log": str(trace_path),
              "model_output_log": str(model_output_path)}
    (root / "agent_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    return result


def run_task(task, agent, env, *, result_dir=None, setup_timeout=600,
             execution_timeout=None, max_steps=100, position=None,
              window_title=None, exit_game=None, agent_name=None, prepare_game=None):
    """Save runs under output root / experiment configuration / task ID."""
    _validate_limits(setup_timeout, max_steps)
    capture_at_deadline = getattr(task, "capture_evaluation_at_deadline", False) is True
    task_limit = getattr(task, "execution_time_limit_seconds", None)
    if execution_timeout is None:
        execution_timeout = (task_limit if isinstance(task_limit, (int, float))
                             and not isinstance(task_limit, bool) else 600)
    _validate_limits(execution_timeout, max_steps)
    if isinstance(task_limit, (int, float)) and not isinstance(task_limit, bool):
        _validate_limits(task_limit, max_steps)
        execution_timeout = min(execution_timeout, task_limit)
    if capture_at_deadline:
        deadline_limit = task.execution_time_limit_seconds
        _validate_limits(deadline_limit, max_steps)
        execution_timeout = min(execution_timeout, deadline_limit)
    if result_dir is None:
        result_dir = getattr(task, "trajectory", "") or "results"
    experiment = experiment_directory(result_dir, agent_name=agent_name,
                                      model=getattr(agent, "model", None),
                                      reasoning_effort=getattr(agent, "reasoning_effort", None))
    task_id = getattr(task, "id", "")
    task_id = task_id if isinstance(task_id, str) and task_id else "task"
    result_dir = experiment / _directory_component(task_id)
    setup_options = {"timeout": setup_timeout}
    if position is not None:
        setup_options["position"] = position
    try:
        if prepare_game is not None:
            prepare_game()
        task.setup(**setup_options)
    except Exception as exc:
        parent = Path(result_dir).resolve()
        parent.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix=f"run-{datetime.now():%Y%m%d-%H%M%S}-", dir=parent))
        result = {"ok": False, "reason": "setup_error", "error": str(exc),
                  "response_count": 0, "result_dir": str(root)}
        evaluation = {"success": False, "score": 0.0, "reason": "setup_error",
                      "setup_error": str(exc)}
        targets = getattr(task, "evaluator", None)
        if isinstance(targets, dict):
            from task.subgoals import add_target_results
            evaluation["targets"] = targets.copy()
            add_target_results(evaluation, targets)
        (root / "agent_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (root / "result.txt").write_text("0.0", encoding="utf-8")
        evaluation_path = root / "evaluation.json"
        evaluation_path.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")
        _save_task_result(root, result, evaluation)
        if exit_game is not None:
            try:
                exit_result = exit_game()
                if isinstance(exit_result, dict):
                    evaluation["exit_result"] = exit_result
            except Exception as cleanup_exc:
                evaluation["exit_error"] = str(cleanup_exc)
        else:
            evaluation["exit_error"] = "Setup failed without a cleanup callback"
        evaluation_path.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")
        return _save_task_result(root, result, evaluation)
    stopped = threading.Event()
    deadline_evaluation = {}

    def on_deadline():
        stopped.set()
        if capture_at_deadline:
            try:
                deadline_evaluation["result"] = task.evaluate()
            except Exception as exc:
                deadline_evaluation["error"] = exc

    timer = threading.Timer(execution_timeout, on_deadline)
    timer.daemon = True
    timer.start()
    try:
        result = run_agent(agent, env, task.instruction, result_dir=result_dir,
                           timeout=execution_timeout, max_steps=max_steps,
                           stop_when=stopped.is_set, window_title=window_title)
    finally:
        timer.cancel()
        if capture_at_deadline:
            timer.join()
    if "error" in deadline_evaluation:
        raise deadline_evaluation["error"]
    evaluation = (deadline_evaluation["result"] if "result" in deadline_evaluation
                  else task.evaluate())
    root = Path(result["result_dir"])
    evaluation_path = root / "evaluation.json"

    def save_evaluation():
        evaluation_path.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        _save_task_result(root, result, evaluation)

    save_evaluation()
    (root / "result.txt").write_text(str(evaluation["score"]), encoding="utf-8")
    if exit_game is not None:
        try:
            exit_result = exit_game()
            if isinstance(exit_result, dict):
                evaluation["exit_result"] = exit_result
                save_evaluation()
        except Exception as exc:
            evaluation["exit_error"] = str(exc)
            save_evaluation()
    return _save_task_result(root, result, evaluation)
