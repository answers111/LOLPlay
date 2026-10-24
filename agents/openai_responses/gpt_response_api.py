import base64
import logging
import os
import time
from copy import deepcopy
from io import BytesIO
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from openai import OpenAI
from agents.output_text import output_text_blocks

from .oauth import OAuthRefreshError, get_access_token, is_token_expired


logger = logging.getLogger("desktopenv.agent")

OPERATOR_PROMPT = """

Here are some helpful tips:
- You are operating a local {PLATFORM} desktop.
- The current date is {CURRENT_DATE}.
- Stay in the application already prepared for the task.
- You can act without asking for confirmation.
- If you need information only the user can provide, ask the question in plain text and do not perform a computer action in the same turn.
- If content may be off-screen, scroll or zoom out before deciding it is unavailable.
- When possible, bundle multiple GUI actions into one computer-use turn.
- If the task is infeasible because of missing apps, permissions, contradictory requirements, or other hard blockers, output exactly "[INFEASIBLE]".
- When you think you have completed the task, output exactly "[DONE]".
"""


class Action:
    """Minimal wrapper matching the existing OpenAI CUA agent contract."""

    def __init__(self, raw_action: Union[Dict[str, Any], str], action_space: str):
        self._action_space = None
        self._action = None
        self.action_space = action_space
        self.action = raw_action

    @property
    def action(self) -> Any:
        return self._action

    @property
    def action_space(self) -> str:
        return self._action_space

    @action_space.setter
    def action_space(self, value: str) -> None:
        if value != "pyautogui":
            raise ValueError("OpenAIResponseAgent only supports pyautogui actions")
        self._action_space = value

    @action.setter
    def action(self, value: Union[Dict[str, Any], str]) -> None:
        if value in (None, ""):
            raise ValueError("action cannot be empty")
        self._action = value

    def get_action(self) -> Any:
        return self._action


class Timer:
    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        self.duration = time.time() - self.start


class StepError(Exception):
    pass


def encode_image(image_content: bytes) -> str:
    return base64.b64encode(image_content).decode("utf-8")


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_model_dump(item) for item in value]
    if isinstance(value, dict):
        return {key: _model_dump(item) for key, item in value.items()}
    return value


def _preview_text(text: str, limit: int = 120) -> str:
    sanitized = text.replace("\n", "\\n")
    if len(sanitized) <= limit:
        return sanitized
    return sanitized[:limit] + "..."


def _get_field(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def _format_prompt_date(value: Any = None) -> str:
    if value is None:
        return datetime.today().strftime("%A, %B %d, %Y")
    if isinstance(value, datetime):
        return value.strftime("%A, %B %d, %Y")
    if isinstance(value, date):
        return value.strftime("%A, %B %d, %Y")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return datetime.today().strftime("%A, %B %d, %Y")
        for parser in (datetime.fromisoformat,):
            try:
                return parser(text).strftime("%A, %B %d, %Y")
            except ValueError:
                pass
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).strftime("%A, %B %d, %Y")
            except ValueError:
                pass
        return text
    return str(value)


def _sanitize_for_log(value: Any) -> Any:
    """Strip oversized payloads like base64 screenshots before logging."""
    value = _model_dump(value)
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if key == "image_url" and isinstance(item, str) and item.startswith("data:image/"):
                sanitized[key] = "<image>"
            else:
                sanitized[key] = _sanitize_for_log(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_for_log(item) for item in value]
    return value


def _compress_replay_screenshots(value):
    """Keep original pixel coordinates while reducing stateless image payloads."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "image_url" and isinstance(item, str) and item.startswith("data:image/png;base64,"):
                from PIL import Image, UnidentifiedImageError
                try:
                    with Image.open(BytesIO(base64.b64decode(item.split(",", 1)[1]))) as screenshot:
                        encoded = BytesIO()
                        screenshot.convert("RGB").save(encoded, "JPEG", quality=45, optimize=True)
                    value[key] = "data:image/jpeg;base64," + encode_image(encoded.getvalue())
                except (UnidentifiedImageError, OSError, ValueError):
                    # Leave unsupported image data unchanged; useful for test doubles.
                    pass
            else:
                _compress_replay_screenshots(item)
    elif isinstance(value, list):
        for item in value:
            _compress_replay_screenshots(item)


class OpenAIResponseAgent:
    def __init__(
        self,
        env,
        platform: str = "windows11",
        model: str = "gpt-6.1-sol",
        max_tokens: Optional[int] = None,
        action_space: str = "pyautogui",
        observation_type: str = "screenshot",
        sleep_after_execution: float = 0.0,
        reasoning_effort: str = "medium",
        base_url: Optional[str] = None,
    ):
        if action_space != "pyautogui":
            raise ValueError("OpenAIResponseAgent only supports pyautogui action space")
        if observation_type != "screenshot":
            raise ValueError("OpenAIResponseAgent currently supports screenshot observation only")

        self.env = env
        self.platform = platform
        self.model = model
        self.max_tokens = max_tokens
        self.action_space = action_space
        self.observation_type = observation_type
        self.sleep_after_execution = sleep_after_execution
        self.reasoning_effort = reasoning_effort
        self.base_url = base_url

        # Responses computer-use uses the plain "computer" tool shape.
        self.tools = [{"type": "computer"}]

        self.previous_response_id: Optional[str] = None
        self.pending_input_items: List[Dict[str, Any]] = []
        self.pending_computer_outputs: List[Dict[str, Any]] = []

    def _build_response_request(self, request_input, instructions):
        request = {
            "model": self.model,
            "instructions": instructions,
            "input": request_input,
            "tools": self.tools,
            "parallel_tool_calls": False,
            "reasoning": {"effort": self.reasoning_effort, "summary": "concise"},
            "truncation": "auto",
        }
        if self.max_tokens is not None:
            request["max_output_tokens"] = self.max_tokens
        if self.previous_response_id:
            request["previous_response_id"] = self.previous_response_id
        return request

    def _send_response(self, client, request):
        return client.responses.create(**request)

    def _create_response(self, request_input: List[Dict[str, Any]], instructions: str):
        retry_count = 0
        last_error = None
        refreshed_after_401 = False
        while retry_count < 5:
            try:
                api_key = get_access_token(self.base_url)
                client = OpenAI(
                    api_key=api_key,
                    base_url=self.base_url or os.getenv("OPENAI_BASE_URL") or None,
                )
                logger.info(
                    "Sending %s request with previous_response_id=%s and %d input item(s)",
                    self.model,
                    self.previous_response_id,
                    len(request_input),
                )
                logger.debug("Request input items: %s", _sanitize_for_log(request_input))
                request = self._build_response_request(request_input, instructions)
                response = self._send_response(client, request)
                response_error = _get_field(_get_field(response, "error", {}), "message")
                if response_error:
                    raise RuntimeError(response_error)
                if _get_field(response, "status") == "failed":
                    raise RuntimeError("Responses API request failed.")
                logger.info("Received %s computer-use response", self.model)
                logger.debug("Raw response output: %s", _sanitize_for_log(_get_field(response, "output", [])))
                return response
            except Exception as exc:
                if isinstance(exc, OAuthRefreshError):
                    raise
                if (os.getenv("OPENAI_OAUTH_CREDENTIALS") and is_token_expired(exc)
                        and not refreshed_after_401):
                    get_access_token(self.base_url, failed_token=api_key)
                    refreshed_after_401 = True
                    logger.info("Renewed expired OAuth credentials; retrying Responses request once.")
                    continue
                if os.getenv("OPENAI_OAUTH_CREDENTIALS") and is_token_expired(exc):
                    raise
                last_error = exc
                retry_count += 1
                logger.error("OpenAI API error on OpenAIResponseAgent call: %s", exc)
                time.sleep(min(5, retry_count * 2))
        raise RuntimeError(f"OpenAI API failed too many times: {last_error}")

    def _action_to_dict(self, action: Any) -> Dict[str, Any]:
        if isinstance(action, dict):
            action_type = action.get("type")
            action_args = {k: _model_dump(v) for k, v in action.items() if k != "type"}
            return {"type": action_type, "args": action_args}

        if hasattr(action, "model_dump"):
            raw = action.model_dump()
            action_type = raw.get("type")
            action_args = {k: _model_dump(v) for k, v in raw.items() if k != "type"}
            return {"type": action_type, "args": action_args}

        if hasattr(action, "to_dict"):
            raw = action.to_dict()
            action_type = raw.get("type")
            action_args = {k: _model_dump(v) for k, v in raw.items() if k != "type"}
            return {"type": action_type, "args": action_args}

        action_type = getattr(action, "type", None)
        action_args: Dict[str, Any] = {}
        for attr in dir(action):
            if attr.startswith("_") or attr == "type":
                continue
            try:
                action_args[attr] = _model_dump(getattr(action, attr))
            except Exception:
                continue
        return {"type": action_type, "args": action_args}

    def _convert_drag_path(self, args: Dict[str, Any]) -> Optional[str]:
        path = args.get("path")
        if not path and args.get("from") and args.get("to"):
            path = [args["from"], args["to"]]
        if not path or len(path) < 2:
            return None

        def point_xy(point: Any) -> Tuple[Any, Any]:
            if isinstance(point, (list, tuple)) and len(point) == 2:
                return point[0], point[1]
            if isinstance(point, dict):
                return point.get("x"), point.get("y")
            return getattr(point, "x", None), getattr(point, "y", None)

        first_x, first_y = point_xy(path[0])
        if first_x is None or first_y is None:
            return None

        commands = [f"import pyautogui\npyautogui.moveTo({first_x}, {first_y})"]
        for point in path[1:]:
            x, y = point_xy(point)
            if x is None or y is None:
                return None
            commands.append(f"pyautogui.dragTo({x}, {y}, duration=0.2, button='left')")
        return "\n".join(commands)

    def _typing_strategy(self, text: str) -> str:
        if text == "":
            return "empty"
        if not text.isascii():
            return "clipboard"
        if "\n" in text:
            return "multiline_ascii"
        if text.isascii():
            return "single_line_ascii"
        return "clipboard"

    def _summarize_type_payload(self, text: str) -> Dict[str, Any]:
        return {
            "strategy": self._typing_strategy(text),
            "chars": len(text),
            "lines": len(text.split("\n")) if text else 0,
            "ascii": text.isascii(),
            "trailing_newline": text.endswith("\n"),
            "preview": _preview_text(text),
        }

    def _build_multiline_ascii_type_command(self, text: str) -> str:
        commands = ["import pydirectinput"]
        lines = text.split("\n")
        for index, line in enumerate(lines):
            if line:
                commands.append(f"pydirectinput.typewrite({repr(line)}, interval=0.03, auto_shift=True, duration=0.08)")
            if index < len(lines) - 1:
                commands.append("pydirectinput.press('enter', duration=0.08)")
        return "\n".join(commands)

    def _build_clipboard_paste_command(self, text: str, paste_keys: Tuple[str, ...] = ("ctrl", "v")) -> str:
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        keys = ", ".join(repr(key) for key in paste_keys)
        return (
            "import base64, time, pydirectinput, pyperclip\n"
            f"_text = base64.b64decode('{encoded}').decode('utf-8')\n"
            "pyperclip.copy(_text)\n"
            "time.sleep(0.1)\n"
            f"pydirectinput.hotkey({keys}, wait=0.08)\n"
            "time.sleep(0.1)"
        )

    def _convert_action_to_pyautogui(self, action_type: str, args: Dict[str, Any]) -> Optional[str]:
        if not action_type:
            return None

        key_mapping = {
            "alt": "alt",
            "arrowdown": "down",
            "arrowleft": "left",
            "arrowright": "right",
            "arrowup": "up",
            "backspace": "backspace",
            "capslock": "capslock",
            "cmd": "command",
            "command": "command",
            "ctrl": "ctrl",
            "delete": "delete",
            "end": "end",
            "enter": "enter",
            "esc": "esc",
            "home": "home",
            "insert": "insert",
            "option": "option",
            "pagedown": "pagedown",
            "pageup": "pageup",
            "shift": "shift",
            "space": "space",
            "super": "super",
            "tab": "tab",
            "win": "win",
        }

        try:
            if action_type == "click":
                x = args.get("x")
                y = args.get("y")
                button = args.get("button", "left")
                if x is None or y is None:
                    return None
                if button not in ["left", "middle", "right"]:
                    button = "left"
                return (
                    f"import pydirectinput, time\n"
                    f"pydirectinput.moveTo({x}, {y})\n"
                    f"pydirectinput.mouseDown(button='{button}')\n"
                    f"try:\n    time.sleep(0.08)\n"
                    f"finally:\n    pydirectinput.mouseUp(button='{button}')"
                )

            if action_type == "double_click":
                x = args.get("x")
                y = args.get("y")
                if x is None or y is None:
                    return None
                return (
                    f"import pydirectinput, time\n"
                    f"pydirectinput.moveTo({x}, {y})\n"
                    f"for _ in range(2):\n"
                    f"    pydirectinput.mouseDown(button='left')\n"
                    f"    try:\n        time.sleep(0.08)\n"
                    f"    finally:\n        pydirectinput.mouseUp(button='left')\n"
                    f"    time.sleep(0.12)"
                )

            if action_type == "move":
                x = args.get("x")
                y = args.get("y")
                if x is None or y is None:
                    return None
                return f"import pyautogui\npyautogui.moveTo({x}, {y})"

            if action_type == "drag":
                return self._convert_drag_path(args)

            if action_type == "type":
                text = args.get("text", "")
                summary = self._summarize_type_payload(text)
                logger.info("Type action payload: %s", summary)
                if text == "":
                    return "import time\ntime.sleep(0.1)"
                strategy = summary["strategy"]
                if strategy == "multiline_ascii":
                    return self._build_multiline_ascii_type_command(text)
                if strategy == "clipboard":
                    return self._build_clipboard_paste_command(text)
                return f"import pydirectinput\npydirectinput.typewrite({repr(text)}, interval=0.03, auto_shift=True, duration=0.08)"

            if action_type == "keypress":
                keys = args.get("keys")
                if not keys and args.get("key"):
                    keys = [args.get("key")]
                if not keys:
                    return None
                if not isinstance(keys, (list, tuple)):
                    keys = [keys]
                mapped_keys = []
                for key in keys:
                    normalized = key_mapping.get(str(key).lower(), str(key).lower())
                    mapped_keys.append(normalized)
                keys_str = ", ".join([repr(key) for key in mapped_keys])
                return f"import pydirectinput\npydirectinput.hotkey({keys_str}, wait=0.08)"

            if action_type == "scroll":
                x = args.get("x")
                y = args.get("y")
                scroll_x = int(
                    args.get("scroll_x")
                    or args.get("delta_x")
                    or args.get("deltaX")
                    or 0
                )
                scroll_y = int(
                    args.get("scroll_y")
                    or args.get("delta_y")
                    or args.get("deltaY")
                    or 0
                )
                position = f", x={x}, y={y}" if x is not None and y is not None else ""
                if scroll_y:
                    return f"import pyautogui\npyautogui.scroll({scroll_y * -1}{position})"
                if scroll_x:
                    return f"import pyautogui\npyautogui.hscroll({scroll_x * -1}{position})"
                return None

            if action_type == "wait":
                secs = max(0.1, float(args.get("ms", 1000)) / 1000.0)
                return f"import time\ntime.sleep({secs})"

            if action_type == "screenshot":
                return "import time\ntime.sleep(0.1)"
        except Exception:
            logger.exception("Failed to convert computer action: %s", action_type)
            return None

        logger.warning("Unsupported computer action: %s", action_type)
        return None

    def _message_text(self, item: Any) -> str:
        content = _get_field(item, "content", [])
        if not content:
            return ""
        if isinstance(content, list):
            parts = []
            for part in content:
                part_type = _get_field(part, "type")
                if part_type == "output_text":
                    parts.append(_get_field(part, "text", ""))
            return "\n".join([part for part in parts if part])
        return str(content)

    def _reasoning_text(self, item: Any) -> str:
        summary = _get_field(item, "summary", [])
        if not summary:
            return ""
        if isinstance(summary, list):
            parts = []
            for part in summary:
                text = _get_field(part, "text", "")
                if text:
                    parts.append(text)
            return "\n".join(parts)
        return str(summary)

    def _computer_call_output_item(
        self,
        call_id: str,
        pending_checks: List[Dict[str, Any]],
        screenshot_b64: str,
    ) -> Dict[str, Any]:
        output_item = {
            "type": "computer_call_output",
            "call_id": call_id,
            "output": {
                "type": "computer_screenshot",
                "image_url": f"data:image/png;base64,{screenshot_b64}",
                "detail": "original",
            },
        }
        if pending_checks:
            output_item["acknowledged_safety_checks"] = pending_checks
        return output_item

    def _build_followup_input(
        self,
        screenshot_b64: str,
        user_response: Optional[str],
    ) -> List[Dict[str, Any]]:
        if self.pending_input_items:
            request_input = list(self.pending_input_items)
            self.pending_input_items = []
            self.pending_computer_outputs = []
            return request_input

        if self.pending_computer_outputs:
            request_input = [
                self._computer_call_output_item(
                    item.get("call_id", ""),
                    item.get("pending_checks", []),
                    screenshot_b64,
                )
                for item in self.pending_computer_outputs
            ]
            self.pending_computer_outputs = []
            return request_input

        if user_response:
            return [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"User response: {user_response}",
                        }
                    ],
                }
            ]

        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Continue from the latest screenshot.",
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{screenshot_b64}",
                        "detail": "original",
                    },
                ],
            }
        ]

    def predict(self, instruction: str, obs: Dict[str, Any]) -> List[Any]:
        user_response = obs.pop("user_response", None) if obs else None
        instructions = OPERATOR_PROMPT.format(
            CURRENT_DATE=_format_prompt_date(getattr(self, "task_current_date", None)),
            PLATFORM=self.platform,
        )
        screenshot_b64 = encode_image(obs["screenshot"])

        if not self.previous_response_id:
            request_input = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": instruction,
                        },
                        {
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{screenshot_b64}",
                            "detail": "original",
                        },
                    ],
                }
            ]
        else:
            request_input = self._build_followup_input(screenshot_b64, user_response)

        with Timer() as model_timer:
            response = self._create_response(request_input, instructions)

        self.previous_response_id = _get_field(response, "id")
        self.pending_input_items = []

        raw_output = _get_field(response, "output", []) or []
        actions: List[Dict[str, Any]] = []
        responses: List[str] = []
        unsupported_action = False
        infeasible_message = False
        done_message = False
        next_pending_outputs: List[Dict[str, Any]] = []

        for item in raw_output:
            item_type = _get_field(item, "type")
            if item_type == "message":
                message_text = self._message_text(item)
                if message_text:
                    responses.append(message_text)
                    lower = message_text.lower()
                    if "[infeasible]" in lower or any(
                        token in lower
                        for token in ["infeasible", "unfeasible", "impossible", "cannot be done", "not feasible"]
                    ):
                        infeasible_message = True
                    if "[done]" in lower:
                        done_message = True
            elif item_type == "reasoning":
                reasoning_text = self._reasoning_text(item)
                if reasoning_text:
                    responses.append(reasoning_text)
            elif item_type == "computer_call":
                logger.info("Raw computer_call item: %s", _sanitize_for_log(item))
                raw_actions = _get_field(item, "actions")
                if raw_actions is None:
                    single_action = _get_field(item, "action")
                    raw_actions = [single_action] if single_action is not None else []

                call_id = _get_field(item, "call_id", "")
                pending_checks = _model_dump(_get_field(item, "pending_safety_checks", []))
                raw_actions = list(raw_actions)
                batch_size = len(raw_actions)
                call_has_supported_action = False

                for index, raw_action in enumerate(raw_actions):
                    action_info = self._action_to_dict(raw_action)
                    logger.info(
                        "Raw tool action %d/%d for call_id=%s: %s",
                        index + 1,
                        batch_size,
                        call_id,
                        _sanitize_for_log(action_info),
                    )
                    pyautogui_code = self._convert_action_to_pyautogui(
                        action_info["type"],
                        action_info["args"],
                    )
                    if not pyautogui_code:
                        unsupported_action = True
                        responses.append(
                            f"Unsupported computer action from model: {action_info['type']}"
                        )
                        continue
                    call_has_supported_action = True
                    actions.append(
                        {
                            "action_space": "pyautogui",
                            "action_type": "computer_call",
                            "action": pyautogui_code,
                            "command": pyautogui_code,
                            "pending_checks": pending_checks,
                            "call_id": call_id,
                            "batch_index": index,
                            "batch_size": batch_size,
                            "batch_last": index == batch_size - 1,
                        }
                    )
                if call_has_supported_action:
                    next_pending_outputs.append(
                        {
                            "call_id": call_id,
                            "pending_checks": pending_checks,
                        }
                    )

        response_text = "\n".join([item for item in responses if item])
        if done_message:
            actions = [{"action_type": "DONE", "raw_response": response_text}]
            unsupported_action = False
            next_pending_outputs = []
        elif infeasible_message:
            actions = [{"action_type": "FAIL", "raw_response": response_text}]
            unsupported_action = False
            next_pending_outputs = []

        state_correct = bool(actions) and not unsupported_action
        if unsupported_action:
            actions = [{"action_type": "FAIL", "raw_response": response_text}]
            next_pending_outputs = []
        self.pending_computer_outputs = next_pending_outputs

        predict_info = {
            "model_usage": {
                "model_time": model_timer.duration,
                "prompt_tokens": _get_field(_get_field(response, "usage", {}), "input_tokens", 0),
                "completion_tokens": _get_field(_get_field(response, "usage", {}), "output_tokens", 0),
            },
            "messages": _model_dump(raw_output),
            "model_output": output_text_blocks(raw_output),
            "response": response_text,
            "state_correct": state_correct,
            "infeasible_message": infeasible_message,
            "done_message": done_message,
        }

        logger.info("Model response text: %s", predict_info["response"])
        logger.info("Model returned %d action(s)", len(actions))
        logger.debug("Model raw output messages: %s", _sanitize_for_log(predict_info["messages"]))

        if not actions:
            return predict_info["response"], actions
        return predict_info, actions

    def reset(self, _logger=None):
        global logger
        logger = _logger if _logger is not None else logging.getLogger("desktopenv.agent")
        self.previous_response_id = None
        self.pending_input_items = []
        self.pending_computer_outputs = []

    def step(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        try:
            if not action:
                raise StepError("Empty action received")

            with Timer() as step_timer:
                step_action = Action(action["action"], self.action_space)
                obs, reward, terminated, info = self.env.step(
                    step_action.get_action(),
                    self.sleep_after_execution,
                )

                if action.get("batch_last"):
                    screenshot_base64 = encode_image(obs["screenshot"])
                    output_item = {
                        "type": "computer_call_output",
                        "call_id": action.get("call_id", ""),
                        "output": {
                            "type": "computer_screenshot",
                            "image_url": f"data:image/png;base64,{screenshot_base64}",
                            "detail": "original",
                        },
                    }
                    pending_checks = action.get("pending_checks") or []
                    if pending_checks:
                        output_item["acknowledged_safety_checks"] = pending_checks
                    self.pending_input_items.append(output_item)
                    self.pending_computer_outputs = []

            return obs, reward, terminated, info, {
                "step_time": step_timer.duration,
                "action": action,
            }
        except Exception as exc:
            logger.exception("OpenAIResponseAgent step failed: %s", exc)
            raise StepError(f"Failed to execute step: {exc}")


class OpenAIResponseStatelessAgent(OpenAIResponseAgent):
    """Reuse desktop actions and retry handling, with client-managed context."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.history = []

    def _build_response_request(self, request_input, instructions):
        request = super()._build_response_request(request_input, instructions)
        request.pop("previous_response_id", None)
        # Response output metadata is not accepted as replay input by some gateways.
        request["input"] = deepcopy(request["input"])
        _compress_replay_screenshots(request["input"])
        for item in request["input"]:
            if isinstance(item, dict):
                item.pop("status", None)
                if item.get("type") == "computer_call":
                    for key in ("action", "actions"):
                        if item.get(key) is None:
                            item.pop(key, None)
        request["store"] = False
        # Explicit inclusion also supports endpoints using the older API behavior.
        request["include"] = ["reasoning.encrypted_content"]
        return request

    def _create_response(self, request_input, instructions):
        request_history = deepcopy(self.history + request_input)
        response = super()._create_response(request_history, instructions)
        # Commit only after a successful request; retries must not duplicate input.
        # Replay every output item, retaining encrypted reasoning and message phase.
        self.history = request_history + deepcopy(
            _model_dump(_get_field(response, "output", []) or [])
        )
        return response

    def predict(self, instruction, obs):
        pending_input = deepcopy(self.pending_input_items)
        pending_outputs = deepcopy(self.pending_computer_outputs)
        history = deepcopy(self.history)
        previous_id = self.previous_response_id
        # The inherited parser uses this field solely to distinguish follow-up turns.
        # It is never sent to the API by this agent.
        if self.history and not self.previous_response_id:
            self.previous_response_id = "local-history"
        try:
            return super().predict(instruction, dict(obs))
        except Exception:
            self.pending_input_items = pending_input
            self.pending_computer_outputs = pending_outputs
            self.history = history
            self.previous_response_id = previous_id
            raise

    def reset(self, _logger=None):
        super().reset(_logger)
        self.history = []


class OpenAIResponseStreamingAgent(OpenAIResponseStatelessAgent):
    """Consume streaming Responses, then reuse stateless history and GUI actions."""

    def _build_response_request(self, request_input, instructions):
        request = super()._build_response_request(request_input, instructions)
        request["stream"] = True
        request.pop("truncation", None)
        return request

    def _send_response(self, client, request):
        # Deltas may contain partial tool actions. Only the final response is parsed
        # and committed, so a failed/retried stream never executes partial actions.
        with client.responses.create(**request) as stream:
            for event in stream:
                event_type = _get_field(event, "type")
                if event_type == "response.completed":
                    response = _get_field(event, "response")
                    if response is None or _get_field(response, "status") != "completed":
                        raise RuntimeError("Stream completed event has no completed response.")
                    return response
                if event_type in ("response.failed", "response.incomplete", "error"):
                    response = _get_field(event, "response", {})
                    details = (
                        _get_field(response, "error")
                        or _get_field(response, "incomplete_details")
                        or event
                    )
                    message = (
                        _get_field(details, "message")
                        or _get_field(details, "reason")
                        or _get_field(details, "code")
                        or event_type
                    )
                    raise RuntimeError(f"Responses stream {event_type}: {message}")
        raise RuntimeError("Responses stream ended without response.completed.")
