# Responses computer agents

**English** | [简体中文](README.zh-CN.md)

This package provides three agents that consume screenshots and use Responses computer tool calls to operate the game. The shared runner handles task setup, execution limits, logs, evaluation, and game cleanup.

## Agent modes

| CLI name | Class | History and transport |
| --- | --- | --- |
| `responses` | `OpenAIResponseAgent` | Server history through `previous_response_id` |
| `responses-stateless` | `OpenAIResponseStatelessAgent` | Full in-memory history with `store=False` |
| `responses-stream` | `OpenAIResponseStreamingAgent` | Stateless history with streaming responses |

Stateless history includes model outputs and matching tool screenshot feedback, and is cleared by `reset()`. Its request size grows with the conversation. Streaming waits for a completed response before parsing and executing actions; partial output is not executed.

## Configuration and usage

From the project root:

```powershell
python -m pip install -e ".[responses]"
python run.py --agent responses --task task001 --check
python run.py --agent responses --task task001
python run.py --agent responses-stateless --task task001
python run.py --agent responses-stream --task task001
```

Set `OPENAI_API_KEY` in the local `.env`; optionally set `OPENAI_BASE_URL` or pass `--base-url`. The endpoint and selected model must support the Responses computer tool protocol. The code defaults to `gpt-6.1-sol` with reasoning effort `medium`; choose values supported by your endpoint. `--check` checks local construction without starting gameplay or verifying remote access.

### OAuth credentials

`OPENAI_OAUTH_CREDENTIALS` can point to an externally provisioned credential JSON file. It takes precedence over the API key. The file must provide `access_token`, `refresh_token`, `client_id`, `saved_at`, and `expires_in` as expected by [oauth.py](oauth.py).

The helper checks expiry before requests, refreshes with less than 60 seconds remaining, and refreshes/retries once for an expired-token 401. Credential updates are saved atomically and refreshes are serialized across processes sharing a file. Rejected refreshes require reauthorization; the helper does not fall back to API-key billing. Keep credentials outside the repository. This project consumes credentials; it does not provide an interactive login flow.

## Observation-to-action delay

![The environment continues changing during model reasoning](../../assets/realtime-interaction.png)

Actions are selected from an earlier screenshot while the game keeps advancing. The top row is an unchanged-scene schematic; the bottom row is a Lee Sin interaction. Command overlays come from logs and do not isolate individual action effects.

## Execution and results

The agent converts structured mouse and keyboard actions into desktop code. PyAutoGUI handles movement, dragging, and scrolling; pydirectinput-rgx handles clicks and scan-code keys. The [desktop environment](../../desktop_env/README.md) executes actions and returns screenshots.

The task defines its execution deadline. The runner checks stopping conditions before requests and actions; a request already in progress may delay stopping. All modes use the common output structure:

```text
results/experiment-<agent>_<model>_<reasoning-effort>/<task.id>/run-*/
```

Execution status and gameplay success are recorded separately. See the [project guide](../../README.md) for result files and the [task catalog](../../task/README.md) for scoring.

The interaction design is adapted from [OSWorld-V2](https://github.com/xlang-ai/OSWorld-V2). The implementation is in [gpt_response_api.py](gpt_response_api.py).
