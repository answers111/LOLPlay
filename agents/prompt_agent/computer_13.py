"""OSWorld actions aligned with the Responses agent input backend."""

import base64
import math


MARKERS = {"WAIT", "DONE", "FAIL"}

# Required and optional parameters. Coordinates are absolute screenshot pixels.
ACTION_PARAMETERS = {
    "MOVE_TO": ({"x", "y"}, {"duration"}),
    "CLICK": (set(), {"x", "y", "button", "num_clicks"}),
    "MOUSE_DOWN": (set(), {"button"}),
    "MOUSE_UP": (set(), {"button"}),
    "RIGHT_CLICK": (set(), {"x", "y"}),
    "DOUBLE_CLICK": (set(), {"x", "y"}),
    "DRAG_TO": ({"x", "y"}, {"duration"}),
    "SCROLL": (set(), {"dx", "dy"}),
    "TYPING": ({"text"}, {"interval", "duration"}),
    "PRESS": ({"key"}, {"duration"}),
    "KEY_DOWN": ({"key"}, set()),
    "KEY_UP": ({"key"}, set()),
    "HOTKEY": ({"keys"}, set()),
    **{marker: (set(), set()) for marker in MARKERS},
}


def action_parts(action):
    """Validate both nested and OSWorld's legacy flat parameter dictionaries."""
    if isinstance(action, str):
        if action in MARKERS:
            return action, {}
        raise ValueError("Expected a computer_13 action dictionary or WAIT/DONE/FAIL")

    if not isinstance(action, dict):
        raise ValueError("Expected a computer_13 action dictionary")

    kind = action.get("action_type")
    if not isinstance(kind, str) or kind not in ACTION_PARAMETERS:
        raise ValueError(f"Unknown computer_13 action type: {kind!r}")

    if "parameters" in action:
        if set(action) - {"action_type", "parameters"}:
            raise ValueError("Do not mix nested and flat action parameters")

        parameters = action["parameters"]
        if parameters is None:
            parameters = {}
    else:
        parameters = {key: value for key, value in action.items() if key != "action_type"}

    if not isinstance(parameters, dict):
        raise ValueError("Action parameters must be a dictionary")

    required, optional = ACTION_PARAMETERS[kind]
    if required - parameters.keys() or parameters.keys() - required - optional:
        raise ValueError(f"Invalid parameters for {kind}: {parameters!r}")

    if ("x" in parameters) != ("y" in parameters):
        raise ValueError("Coordinates x and y must be provided together")

    if kind == "SCROLL" and not ({"dx", "dy"} & parameters.keys()):
        raise ValueError("SCROLL requires dx or dy")

    for name in ("x", "y", "dx", "dy", "duration", "interval"):
        if name not in parameters:
            continue

        value = parameters[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"{name} must be a finite number")
        if name in {"x", "y", "duration", "interval"} and value < 0:
            raise ValueError(f"{name} must be non-negative")
        if name in {"dx", "dy"} and not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")

    if "button" in parameters and parameters["button"] not in ("left", "right", "middle"):
        raise ValueError("button must be left, right or middle")

    if "num_clicks" in parameters:
        clicks = parameters["num_clicks"]
        if isinstance(clicks, bool) or not isinstance(clicks, int) or not 1 <= clicks <= 3:
            raise ValueError("num_clicks must be 1, 2 or 3")

    if "text" in parameters and not isinstance(parameters["text"], str):
        raise ValueError("text must be a string")

    if "key" in parameters and (
        not isinstance(parameters["key"], str) or not parameters["key"].strip()
    ):
        raise ValueError("key must be a non-empty string")

    if "keys" in parameters and (
        not isinstance(parameters["keys"], list)
        or not parameters["keys"]
        or any(not isinstance(key, str) or not key.strip() for key in parameters["keys"])
    ):
        raise ValueError("keys must be a non-empty list of key names")

    return kind, parameters


def normalize_key(key):
    """Use the same key aliases as OpenAIResponseAgent."""
    key_mapping = {
        "arrowdown": "down",
        "arrowleft": "left",
        "arrowright": "right",
        "arrowup": "up",
        "cmd": "command",
    }

    normalized = key.lower()
    return key_mapping.get(normalized, normalized)


def action_to_code(action):
    """Convert each action using the Responses agent's input conventions."""
    action_type, parameters = action_parts(action)

    if action_type == "MOVE_TO":
        x = parameters["x"]
        y = parameters["y"]

        if "duration" in parameters:
            duration = parameters["duration"]
            return f"pyautogui.moveTo({x!r}, {y!r}, duration={duration!r})"
        return f"pyautogui.moveTo({x!r}, {y!r})"

    elif action_type in {"CLICK", "RIGHT_CLICK", "DOUBLE_CLICK"}:
        button = "right" if action_type == "RIGHT_CLICK" else parameters.get("button", "left")
        num_clicks = 2 if action_type == "DOUBLE_CLICK" else parameters.get("num_clicks", 1)
        commands = []

        if "x" in parameters:
            x = parameters["x"]
            y = parameters["y"]
            commands.append(f"pyautogui.moveTo({x!r}, {y!r})")

        # Match Responses click hold/release and double-click timing.
        if num_clicks == 1:
            commands.append(
                f"pydirectinput.mouseDown(button={button!r})\n"
                "try:\n    time.sleep(0.08)\n"
                f"finally:\n    pydirectinput.mouseUp(button={button!r})"
            )
        else:
            commands.append(
                f"for _ in range({num_clicks}):\n"
                f"    pydirectinput.mouseDown(button={button!r})\n"
                "    try:\n        time.sleep(0.08)\n"
                f"    finally:\n        pydirectinput.mouseUp(button={button!r})\n"
                "    time.sleep(0.12)"
            )

        return "\n".join(commands)

    elif action_type == "MOUSE_DOWN":
        button = parameters.get("button", "left")
        return f"pydirectinput.mouseDown(button={button!r})"

    elif action_type == "MOUSE_UP":
        button = parameters.get("button", "left")
        return f"pydirectinput.mouseUp(button={button!r})"

    elif action_type == "DRAG_TO":
        x = parameters["x"]
        y = parameters["y"]
        duration = parameters.get("duration", 0.2)
        return f"pyautogui.dragTo({x!r}, {y!r}, duration={duration!r}, button='left')"

    elif action_type == "SCROLL":
        # computer_13 uses positive dy for up (CUA's scroll_y uses down).
        commands = []

        if "dx" in parameters:
            dx = parameters["dx"]
            commands.append(f"pyautogui.hscroll({dx!r})")

        if "dy" in parameters:
            dy = parameters["dy"]
            commands.append(f"pyautogui.scroll({dy!r})")

        return "\n".join(commands)

    elif action_type == "TYPING":
        text = parameters["text"]

        if text == "":
            return "time.sleep(0.1)"

        if not text.isascii():
            encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
            return (
                "import base64, pyperclip\n"
                f"_text = base64.b64decode({encoded!r}).decode('utf-8')\n"
                "pyperclip.copy(_text)\n"
                "time.sleep(0.1)\n"
                "pydirectinput.hotkey('ctrl', 'v', wait=0.08)\n"
                "time.sleep(0.1)"
            )

        interval = parameters.get("interval", 0.03)
        duration = parameters.get("duration", 0.08)
        commands = []
        lines = text.split("\n")

        for index, line in enumerate(lines):
            if line:
                commands.append(
                    f"pydirectinput.typewrite({line!r}, interval={interval!r}, "
                    f"auto_shift=True, duration={duration!r})"
                )

            if index < len(lines) - 1:
                commands.append("pydirectinput.press('enter', duration=0.08)")

        return "\n".join(commands)

    elif action_type == "PRESS":
        key = normalize_key(parameters["key"])
        duration = parameters.get("duration", 0.08)
        return f"pydirectinput.press({key!r}, duration={duration!r})"

    elif action_type == "KEY_DOWN":
        key = normalize_key(parameters["key"])
        return f"pydirectinput.keyDown({key!r})"

    elif action_type == "KEY_UP":
        key = normalize_key(parameters["key"])
        return f"pydirectinput.keyUp({key!r})"

    elif action_type == "HOTKEY":
        keys = [normalize_key(key) for key in parameters["keys"]]
        arguments = ", ".join(repr(key) for key in keys)
        return f"pydirectinput.hotkey({arguments}, wait=0.08)"

    elif action_type in MARKERS:
        return action_type

    else:
        raise ValueError(f"Unknown action type: {action_type!r}")
