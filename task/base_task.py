"""Task metadata, serialization and lifecycle interface."""
import copy
from typing import Any, Dict, List, Optional, Union


class BaseTask(dict):
    id: str = ""
    snapshot: str = ""
    instruction: str = ""
    source: str = ""
    config: List[Dict[str, Any]] = []
    trajectory: str = ""  # Output root containing experiment / task / run directories.
    evaluator: Optional[Dict[str, Any]] = None
    platform: str = "windows11"
    user_simulator: Optional[Dict[str, Any]] = None
    
    def __init__(self, **overrides: Any) -> None:
        fields = self._fields()
        data = {name: copy.deepcopy(getattr(self.__class__, name)) for name in fields}
        data.update(overrides)
        super().__init__(data)
        extra = {key: value for key, value in overrides.items() if key not in fields}
        super().__setattr__("_extra", extra)

    @classmethod
    def _fields(cls) -> List[str]:
        return [
            "id",
            "snapshot",
            "instruction",
            "source",
            "config",
            "trajectory",
            "evaluator",
            "platform",
            "user_simulator",
        ]

    def __getattribute__(self, key: str) -> Any:
        # Class defaults must not shadow the per-instance copies in the dict.
        if key in BaseTask._fields() and dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        return super().__getattribute__(key)

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key: str, value: Any) -> None:
        if key.startswith("_"):
            super().__setattr__(key, value)
            return
        self[key] = value

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(dict(self))

    def setup(self, setup_controller) -> None:
        raise NotImplementedError("Task must implement setup().")

    def evaluate(self, env) -> Union[float, Dict[str, Any]]:
        """Evaluate task completion.

        Execution expiry stops actions; it does not by itself fail a task.
        Score goals from the final state even when evaluation is delayed by an
        in-flight model request. For timestamped event goals, validate the event
        time against the task deadline rather than the time of evaluation.

        Returns either a ``float`` score in ``[0.0, 1.0]`` (legacy) or a
        ``dict`` whose ``score`` field holds the float score. When a dict is
        returned, the runner persists the payload to ``evaluation.json`` and
        includes it with the agent outcome in ``result.json``, alongside the
        legacy ``result.txt``.
        """
        raise NotImplementedError("Task must implement evaluate() or provide an evaluator config.")
