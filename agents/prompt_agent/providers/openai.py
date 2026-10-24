"""OpenAI Responses requests, credentials, retries and streaming."""

import base64
from collections import deque
from copy import copy
from datetime import datetime, timezone
import logging
import os
import time

from openai import APIConnectionError, OpenAI
try:
    import httpx2 as httpx
except ImportError:
    import httpx
from agents.output_text import output_text_blocks
from agents.openai_responses.oauth import get_access_token, is_token_expired
from ..agent import _field


logger = logging.getLogger(__name__)


class InterruptedPromptStream(RuntimeError):
    """The transport ended before a response.completed event arrived."""


class OpenAIProvider:
    def validate_effort(self, effort):
        pass

    def observation_message(self, text, screenshot):
        return {"role": "user", "content": [
            {"type": "input_text", "text": text},
            {"type": "input_image", "image_url": "data:image/png;base64," +
             base64.b64encode(screenshot).decode("ascii"), "detail": "original"},
        ]}

    def build_request(self, *, model, instructions, messages, effort, max_tokens):
        request = {"model": model, "instructions": instructions, "input": messages, "store": False}
        if effort:
            request["reasoning"] = {"effort": effort}
        if max_tokens is not None:
            request["max_output_tokens"] = max_tokens
        return request

    def send(self, client, request):
        return client.responses.create(**request)

    @staticmethod
    def normalize(response):
        text = _field(response, "output_text")
        if not isinstance(text, str) or not text.strip():
            text = "\n".join(
                _field(part, "text", "")
                for item in _field(response, "output", []) or []
                if _field(item, "type") == "message"
                for part in _field(item, "content", []) or []
                if _field(part, "type") == "output_text"
            )
        blocks = output_text_blocks(_field(response, "output", []) or [])
        if not blocks and text:
            blocks = [{"type": "output_text", "text": text}]
        return {"output_text": text, "usage": _field(response, "usage"), "model_output": blocks}

    def create(self, request, *, base_url, timeout):
        # The SDK handles transient failures; refresh an expired OAuth token once.
        for attempt in range(2):
            token = get_access_token(base_url)
            try:
                with OpenAI(
                    api_key=token,
                    base_url=base_url or os.getenv("OPENAI_BASE_URL") or None,
                    timeout=timeout,
                    max_retries=2,
                ) as client:
                    response = self.send(client, request)

                if _field(response, "error") or _field(response, "status") in {"failed", "incomplete"}:
                    raise RuntimeError("PromptAgent received a failed or incomplete model response")
                return self.normalize(response)
            except Exception as exc:
                if attempt == 0 and os.getenv("OPENAI_OAUTH_CREDENTIALS") and is_token_expired(exc):
                    get_access_token(base_url, failed_token=token)
                    continue
                raise


class OpenAIStreamingProvider(OpenAIProvider):
    stream_max_retries = 2

    def __init__(self):
        self._diagnostics = []

    def drain_request_diagnostics(self):
        diagnostics, self._diagnostics = self._diagnostics, []
        return diagnostics

    def build_request(self, **options):
        request = super().build_request(**options)
        request["stream"] = True
        return request

    def send(self, client, request):
        for attempt in range(self.stream_max_retries + 1):
            diagnostic = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "attempt": attempt + 1, "max_attempts": self.stream_max_retries + 1,
                "request_id": None, "response_id": None, "event_count": 0,
                "last_event_types": [], "stream_started": False,
            }
            started = time.monotonic()
            try:
                response = self._send_once(client, request, diagnostic)
            except Exception as exc:
                retryable = diagnostic["stream_started"] and isinstance(
                    exc, (InterruptedPromptStream, APIConnectionError, httpx.TransportError))
                retry = retryable and attempt < self.stream_max_retries
                delay = 2 ** attempt if retry else 0
                diagnostic.update(
                    outcome="retry" if retry else "failed", error_type=type(exc).__name__,
                    retry_delay_seconds=delay, duration_seconds=time.monotonic() - started)
                # Record metadata only: never persist or reuse partial model text.
                self._diagnostics.append(diagnostic)
                logger.warning("Prompt stream %s: %s", diagnostic["outcome"], diagnostic)
                if not retry:
                    raise
                time.sleep(delay)
            else:
                diagnostic.update(outcome="completed", duration_seconds=time.monotonic() - started)
                self._diagnostics.append(diagnostic)
                return response

    def _send_once(self, client, request, diagnostic):
        # Like OpenAIResponseStreamingAgent, use only the completed response.
        # A delta or output_text.done may precede a failure or truncated response.
        completed_items = {}
        recent_events = deque(maxlen=8)

        with client.responses.create(**request) as stream:
            diagnostic["stream_started"] = True
            headers = getattr(getattr(stream, "response", None), "headers", {})
            request_id = headers.get("x-request-id")
            if isinstance(request_id, str):
                diagnostic["request_id"] = request_id
            for event in stream:
                event_type = _field(event, "type")
                recent_events.append(event_type if isinstance(event_type, str) else "unknown")
                diagnostic["event_count"] += 1
                diagnostic["last_event_types"] = list(recent_events)
                response_id = _field(_field(event, "response"), "id")
                if isinstance(response_id, str):
                    diagnostic["response_id"] = response_id

                if event_type == "response.output_item.done":
                    item = _field(event, "item")
                    if item is not None:
                        index = _field(event, "output_index")
                        if not isinstance(index, int):
                            index = len(completed_items)
                        completed_items[index] = item

                if event_type == "response.completed":
                    response = _field(event, "response")
                    if response is None or _field(response, "status") != "completed":
                        raise RuntimeError("Prompt stream completed event has no completed response")
                    if _field(response, "error"):
                        raise RuntimeError("PromptAgent received a failed or incomplete model response")

                    # Some endpoints omit output in the terminal event. Recover
                    # fully finished items only after the whole response succeeds.
                    if not _field(response, "output") and completed_items:
                        output = [completed_items[index] for index in sorted(completed_items)]
                        if isinstance(response, dict):
                            response = {**response, "output": output}
                            response.pop("output_text", None)
                        else:
                            response = copy(response)
                            response.output = output

                    return response

                if event_type in {"response.failed", "response.incomplete", "error"}:
                    response = _field(event, "response")
                    details = (
                        _field(response, "error")
                        or _field(response, "incomplete_details")
                        or event
                    )
                    message = (
                        _field(details, "message")
                        or _field(details, "reason")
                        or _field(details, "code")
                        or event_type
                    )
                    raise RuntimeError(f"Prompt stream {event_type}: {message}")

        raise InterruptedPromptStream("Prompt stream ended without response.completed")
