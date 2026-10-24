# Prompt agents

**English** | [简体中文](README.zh-CN.md)

`PromptAgent` and `StreamingPromptAgent` turn screenshots and task instructions into Python code or `computer_13` JSON actions. They use the shared desktop environment and task evaluators.

## Usage

Run from the project root with credentials in `.env`:

```powershell
python -m pip install -e ".[responses]"
python run.py --agent prompt --task task001 --check
python run.py --agent prompt --task task001
python run.py --agent prompt-stream --action-space computer_13 --task task001
```

| Option | Default | Purpose |
| --- | --- | --- |
| `--action-space` | `pydirectinput` | Python code, or `computer_13` JSON |
| `--max-trajectory-length` | `3` | Recent screenshot/reply pairs; `0` sends only the current screenshot |
| `--wait-seconds` | `1.0` | Duration of a WAIT action |
| `--request-timeout` | `120` | Timeout in seconds per network attempt |
| `--max-tokens` | Unset | Output token cap; OpenAI uses its API default, Anthropic defaults to 4096 |
| `--reasoning-effort` | `medium` | Provider-specific reasoning effort; an empty string omits it |

Task instructions are sent every round. The default model is `gpt-6.1-sol`; choose a model available at your endpoint. Setup and execution limits are described in the [project guide](../../README.md).

## Providers and credentials

Model names beginning with `claude-` select `providers/anthropic.py`; other names select `providers/openai.py`. The shared workflow in `agent.py` handles history, action parsing, and execution.

| Provider | Install extra | Credentials | Endpoint priority |
| --- | --- | --- | --- |
| OpenAI Responses | `.[responses]` | `OPENAI_API_KEY` or `OPENAI_OAUTH_CREDENTIALS` | `--base-url`, then `OPENAI_BASE_URL`, then SDK default |
| Anthropic Messages | `.[anthropic]` | `ANTHROPIC_AUTH_TOKEN`, then `CLAUDE_CODE_OAUTH_TOKEN` | `--base-url`, then `ANTHROPIC_BASE_URL`, then provider default |

OpenAI prompt mode sends text and images without computer tool calls; the endpoint needs image input and text output. OAuth file refresh follows the [Responses credential guide](../openai_responses/README.md).

The Anthropic adapter uses SDK Messages with an OAuth auth token, a billing header in the system message, and a beta query option. This is the adapter's experimental protocol; endpoint compatibility must be checked for your account. It does not use the OpenAI credential refresh helper. Update an expired Anthropic token locally and restart the process. Effort accepts `low`, `medium`, `high`, `xhigh`, `max`, or an empty string. Only replies with `stop_reason=end_turn` are accepted.

## Python actions

The default action space accepts Python code blocks:

```python
import pyautogui
import pydirectinput
pyautogui.click(960, 540, button="right")
pydirectinput.press("q", duration=0.08)
```

Use PyAutoGUI for mouse actions and pydirectinput-rgx for keyboard input. Multiple blocks execute in order, each in a fresh namespace. Coordinates refer to the unscaled desktop screenshot. The parser validates the whole batch's syntax before execution; this is not a Python sandbox.

`WAIT` waits and captures a new screenshot. `DONE` ends agent execution, while `FAIL` marks it infeasible; both still lead to task evaluation. DONE/FAIL must be the last action in a batch.

## computer_13 actions

Choose `--action-space computer_13` for JSON actions:

```json
{"action_type": "CLICK", "parameters": {"x": 960, "y": 540, "button": "right"}}
```

| Action | Parameters |
| --- | --- |
| `MOVE_TO` | `x`, `y`; optional `duration` |
| `CLICK` | Optional `x`/`y`, `button`, `num_clicks` (1–3) |
| `MOUSE_DOWN`, `MOUSE_UP` | Optional `button` |
| `RIGHT_CLICK`, `DOUBLE_CLICK` | Optional `x`/`y` |
| `DRAG_TO` | `x`, `y`; optional `duration` |
| `SCROLL` | Integer `dx` and/or `dy` |
| `TYPING` | `text`; optional `interval`, `duration` |
| `PRESS` | `key`; optional `duration` |
| `KEY_DOWN`, `KEY_UP` | `key` |
| `HOTKEY` | Nonempty `keys` list |

Coordinates must be supplied as a pair. A response may contain a JSON object or multiple object code blocks; JSON arrays are not accepted. Flat parameters are also supported. WAIT/DONE/FAIL can be text, code-block markers, or action dictionaries. The fixed mappings are in [computer_13.py](computer_13.py).

## Observation-to-action delay

![The environment continues changing during model reasoning](../../assets/realtime-interaction.png)

Actions are selected from an earlier screenshot while the game keeps advancing. The top row is an unchanged-scene schematic; the bottom row is a Lee Sin interaction. Command overlays come from logs and do not isolate individual action effects.

## Streaming and output

`prompt-stream` changes response transport and waits for a completed response before executing any code. OpenAI stream connection/read failures or a missing completion event can be retried twice with 1- and 2-second waits; explicit failed/incomplete/error events are rejected. SDK request retries and one expired-OAuth refresh are separate mechanisms. Incomplete attempts do not commit history or execute actions.

Stream attempt diagnostics are stored as `request_diagnostic` events in `trajectory.jsonl`, including timing, attempt count, available request/response IDs, recent event types, outcome, and retry delay. Diagnostics omit credentials, screenshots, and partial model text. Retries can add latency and model usage.

Results use `results/experiment-<agent>_<model>_<reasoning-effort>/<task.id>/run-*`. See the [result guide](../../README.md) and [task catalog](../../task/README.md).

The screenshot/history/action design is adapted from [OSWorld-V2](https://github.com/xlang-ai/OSWorld-V2).
