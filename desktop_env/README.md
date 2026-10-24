# Desktop execution environment

**English** | [简体中文](README.zh-CN.md)

`DesktopEnv` captures screenshots and executes local desktop actions for LOL-Play agents. It is independent of model providers and task scoring. Gameplay input and window management target Windows.

## Usage

Install a project extra such as `.[responses]` from the project root, then run:

```python
from desktop_env import DesktopEnv

env = DesktopEnv()
env.bind_window("League of Legends (TM) Client")
obs = env.get_obs()  # {"screenshot": PNG bytes}
obs, reward, terminated, info = env.step(
    "pydirectinput.press('p', duration=0.08)"
)
```

`bind_window(title)` requires exactly one matching game window and checks foreground focus before input. `get_obs()` captures the desktop using PyAutoGUI. Coordinates are absolute screenshot pixels.

## Screenshot observation

![Full screenshot from Task009 with Ahri](../assets/task-009-ahri.png)

The agent observes the full frame, including the champion, minions, ability bar, and minimap, and acts using absolute screenshot pixels. This Task009 scene illustrates interaction, not task completion.

## Action interface

`step(action, sleep_after_execution=0.0)` accepts Python strings and `WAIT` / `DONE` / `FAIL` markers. The execution namespace provides `pyautogui`, `pydirectinput`, and `time`. Each Python block has a fresh namespace. Python runs directly in the local process; the environment is not a code sandbox.

The environment requires `pydirectinput-rgx`, imported as `pydirectinput`, for scan-code keyboard support. Prompt Python actions use PyAutoGUI for the mouse and pydirectinput for the keyboard. Responses and `computer_13` actions use PyAutoGUI for movement, dragging, and scrolling, and pydirectinput for clicks and keyboard input. Unicode text uses clipboard paste through pyperclip.

`computer_13` JSON dictionaries are validated and converted by the prompt agent before reaching this environment:

```python
from agents.prompt_agent import PromptAgent

agent = PromptAgent(env, action_space="computer_13")
agent.step({"action_type": "PRESS", "parameters": {"key": "q", "duration": 0.08}})
```

The returned reward defaults to zero. Gameplay success is determined by the task evaluator, not by desktop execution.

## Window lifecycle

`game_windows()` and `game_process_ids()` inspect game windows and processes. `exit_game()` uses the bound game window to leave a match. `clear_stale_game(client)` checks client state before cleaning up residual game processes. The runner coordinates preparation and cleanup around each task.

This module implements the screenshot/step surface needed by the bundled agents. It does not provide OSWorld VM management or the full OSWorld environment API.

See the [project guide](../README.md), [prompt agents](../agents/prompt_agent/README.md), and [tasks](../task/README.md).
