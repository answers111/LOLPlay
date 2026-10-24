"""OSWorld-style PromptAgent using Responses or Anthropic Messages."""

import ast
from copy import deepcopy
import logging
import json
import math
import re
import time

from .providers import create_provider
from .computer_13 import action_parts, action_to_code, normalize_key
from .prompts import SYSTEM_PROMPT, COMPUTER_13_SYSTEM_PROMPT


logger = logging.getLogger("desktopenv.prompt_agent")
MARKERS = {"WAIT", "DONE", "FAIL"}


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def parse_code_from_string(response):
    """Extract Python blocks/markers without altering indentation or semicolons.

    Validate the entire batch before returning anything for execution. This is
    format/backend validation, not a security sandbox for generated Python.
    """
    if not isinstance(response, str) or not response.strip():
        raise ValueError("PromptAgent received an empty text response")
    if response.strip() in MARKERS:
        return [response.strip()]

    actions = []
    for match in re.finditer(r"```(.*?)```", response, flags=re.DOTALL):
        block = match.group(1).strip()
        if block in MARKERS:
            actions.append(block)
            continue
        if block.lower() in {"python", "py"}:
            raise ValueError("PromptAgent received an empty code block")

        # Accept Python fences and unlabelled fences, including ```python DONE```.
        label = re.match(r"^(python|py)\s+", block, flags=re.IGNORECASE)
        if label:
            block = block[label.end():].strip()
        elif "\n" in block and re.fullmatch(r"[\w+-]+", block.split("\n", 1)[0]):
            raise ValueError("PromptAgent expects Python code blocks, not another language")
        if not block:
            raise ValueError("PromptAgent received an empty code block")

        # OSWorld also permits a special marker on the last line of a code block.
        lines = block.splitlines()
        marker = lines[-1].strip() if lines[-1] == lines[-1].lstrip() else None
        if marker in MARKERS:
            code = "\n".join(lines[:-1]).strip()
            if code:
                actions.append(code)
            actions.append(marker)
        else:
            actions.append(block)

    if not actions:
        raise ValueError("PromptAgent expects a fenced Python block or WAIT/DONE/FAIL")

    for index, action in enumerate(actions):
        if action in {"DONE", "FAIL"} and index != len(actions) - 1:
            raise ValueError("DONE/FAIL must be the last action")
        if action in MARKERS:
            continue
        try:
            tree = ast.parse(action, filename="<prompt-action>")
            compile(tree, "<prompt-action>", "exec")
        except SyntaxError as exc:
            raise ValueError(f"Invalid Python action: {exc.msg} (line {exc.lineno})") from exc

    return actions


def parse_actions_from_string(response):
    """Parse OSWorld JSON fences or a plain JSON action, validating the whole batch."""
    if not isinstance(response, str) or not response.strip():
        raise ValueError("PromptAgent received an empty text response")
    if response.strip() in MARKERS:
        return [response.strip()]

    blocks = re.findall(r"```(.*?)```", response, flags=re.DOTALL)
    actions = []
    for block in blocks or [response]:
        block = block.strip()
        if block in MARKERS:
            actions.append(block)
            continue
        block = re.sub(r"^json\s+", "", block, flags=re.IGNORECASE)
        try:
            action = json.loads(block)
        except json.JSONDecodeError as exc:
            raise ValueError("PromptAgent expects a JSON action or WAIT/DONE/FAIL") from exc
        actions.append(action)

    for index, action in enumerate(actions):
        kind, _ = action_parts(action)
        if kind in {"DONE", "FAIL"} and index != len(actions) - 1:
            raise ValueError("DONE/FAIL must be the last action")

    return actions


class PromptAgent:
    stream = False

    def __init__(
        self,
        env,
        *,
        model="gpt-6.1-sol",
        platform="windows",
        action_space="pydirectinput",
        observation_type="screenshot",
        max_tokens=None,
        max_trajectory_length=3,
        reasoning_effort="medium",
        base_url=None,
        wait_seconds=1.0,
        sleep_after_execution=0.0,
        request_timeout=120.0,
    ):
        if action_space not in {"pydirectinput", "computer_13"} or observation_type != "screenshot":
            raise ValueError("PromptAgent supports pydirectinput/computer_13 with screenshot observations only")
        if (
            isinstance(max_trajectory_length, bool)
            or not isinstance(max_trajectory_length, int)
            or max_trajectory_length < 0
        ):
            raise ValueError("max_trajectory_length must be a non-negative integer")
        if max_tokens is not None and (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or max_tokens <= 0
        ):
            raise ValueError("max_tokens must be a positive integer")
        for name, value, minimum in (
            ("wait_seconds", wait_seconds, 0),
            ("sleep_after_execution", sleep_after_execution, 0),
            ("request_timeout", request_timeout, 0),
        ):
            if (
                not math.isfinite(value)
                or value < minimum
                or name == "request_timeout" and value == 0
            ):
                raise ValueError(f"Invalid {name}")

        self.env = env
        self.model, self.platform = model, platform
        self.action_space, self.observation_type = action_space, observation_type
        self.max_tokens = max_tokens
        self.max_trajectory_length = max_trajectory_length
        self.reasoning_effort, self.base_url = reasoning_effort, base_url
        self.provider = create_provider(model, stream=self.stream)
        self.provider.validate_effort(reasoning_effort)
        self.wait_seconds = wait_seconds
        self.sleep_after_execution = sleep_after_execution
        self.request_timeout = request_timeout
        self.system_message = COMPUTER_13_SYSTEM_PROMPT if action_space == "computer_13" else SYSTEM_PROMPT
        self.reset()

    def drain_request_diagnostics(self):
        drain = getattr(self.provider, "drain_request_diagnostics", None)
        return drain() if callable(drain) else []

    def reset(self, _logger=None):
        self.observations = []
        self.thoughts = []
        self.actions = []

    def _observation_message(self, obs):
        screenshot = obs.get("screenshot")
        if not isinstance(screenshot, bytes) or not screenshot:
            raise ValueError("PromptAgent expects non-empty screenshot bytes")

        text = "Inspect this screenshot and return the next Python action or special marker."
        if self.action_space == "computer_13":
            text = "Inspect this screenshot and return the next computer_13 JSON action or special marker."
        if obs.get("user_response"):
            text += "\nUser response: " + str(obs["user_response"])

        return self.provider.observation_message(text, screenshot)

    def _build_response_request(self, instruction, observation):
        inputs = []
        for previous_obs, previous_thought in zip(self.observations, self.thoughts):
            inputs.extend([
                previous_obs,
                {"role": "assistant", "content": previous_thought},
            ])
        inputs.append(observation)

        return self.provider.build_request(
            model=self.model,
            instructions=self.system_message + "\nTask instruction:\n" + instruction,
            messages=deepcopy(inputs),
            effort=self.reasoning_effort,
            max_tokens=self.max_tokens,
        )

    def _create_response(self, request):
        return self.provider.create(request, base_url=self.base_url, timeout=self.request_timeout)

    def predict(self, instruction, obs):
        observation = self._observation_message(obs)
        request = self._build_response_request(instruction, observation)
        started = time.monotonic()
        response = self._create_response(request)

        response_text = _field(response, "output_text")
        actions = self.parse_actions(response_text)

        # Commit only a complete, valid turn; failed requests/parses preserve history.
        if self.max_trajectory_length:
            self.observations.append(observation)
            self.thoughts.append(response_text)
            self.actions.append(actions[:])
            for history in (self.observations, self.thoughts, self.actions):
                del history[:-self.max_trajectory_length]

        usage = _field(response, "usage")
        info = {
            "response": response_text,
            "model_output": _field(response, "model_output", [{"type": "output_text", "text": response_text}]),
            "state_correct": True,
            "model_usage": {
                "model_time": time.monotonic() - started,
                "prompt_tokens": _field(usage, "input_tokens", 0),
                "completion_tokens": _field(usage, "output_tokens", 0),
            },
        }
        logger.info("PromptAgent returned %d %s action(s)", len(actions), self.action_space)
        return info, actions

    def parse_actions(self, response):
        if self.action_space == "computer_13":
            return parse_actions_from_string(response)
        return parse_code_from_string(response)

    def step(self, action):
        if self.action_space == "computer_13":
            kind, parameters = action_parts(action)

            # pydirectinput silently skips unknown keys; reject them before input.
            keyboard = getattr(self.env, "keyboard", None)
            mapping = getattr(keyboard, "KEYBOARD_MAPPING", None)

            if isinstance(mapping, dict):
                keys = []

                if "key" in parameters:
                    keys = [normalize_key(parameters["key"])]
                elif kind == "HOTKEY":
                    keys = [normalize_key(key) for key in parameters["keys"]]
                elif kind == "TYPING":
                    text = parameters["text"]

                    # Unicode uses clipboard paste; ASCII newlines become Enter.
                    if text and not text.isascii():
                        keys = ["ctrl", "v"]
                    else:
                        keys = ["enter" if key == "\n" else key for key in text]

                if any(key not in mapping for key in keys):
                    raise ValueError("Action contains keys unsupported by pydirectinput")

            action = action_to_code(action)

        if action == "WAIT":
            action = f"time.sleep({self.wait_seconds!r})"

        return self.env.step(action, sleep_after_execution=self.sleep_after_execution)


class StreamingPromptAgent(PromptAgent):
    """Wait for a complete streaming response before parsing or committing actions."""

    stream = True
