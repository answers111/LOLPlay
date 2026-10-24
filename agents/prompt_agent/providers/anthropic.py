"""Anthropic Messages requests, OAuth credentials and streaming."""

import base64
import os

from anthropic import Anthropic
from agents.output_text import output_text_blocks
from ..agent import _field


class AnthropicProvider:
    def validate_effort(self, effort):
        if effort and effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Invalid Claude effort level")

    def observation_message(self, text, screenshot):
        return {"role": "user", "content": [
            {"type": "text", "text": text},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
             "data": base64.b64encode(screenshot).decode("ascii")}},
        ]}

    def build_request(self, *, model, instructions, messages, effort, max_tokens):
        request = {
            "model": model,
            "max_tokens": max_tokens if max_tokens is not None else 4096,
            "system": [
                {"type": "text", "text": "x-anthropic-billing-header: cc_version=2.1.292.969; cc_entrypoint=sdk-cli;"},
                {"type": "text", "text": instructions},
            ],
            "messages": messages,
            "extra_query": {"beta": "true"},
        }
        if effort:
            request["output_config"] = {"effort": effort}
        return request

    def send(self, client, request):
        return client.messages.create(**request)

    def create(self, request, *, base_url, timeout):
        token = os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
        if not token:
            raise RuntimeError("Missing ANTHROPIC_AUTH_TOKEN or CLAUDE_CODE_OAUTH_TOKEN; set it locally or use --env-file")
        with Anthropic(
            api_key=None, auth_token=token,
            base_url=base_url or os.getenv("ANTHROPIC_BASE_URL") or "https://api.anthropic.com",
            timeout=timeout, max_retries=2,
        ) as client:
            message = self.send(client, request)
        if _field(message, "stop_reason") != "end_turn":
            raise RuntimeError("PromptAgent received a failed or incomplete Claude response")
        return {
            "output_text": "\n".join(
                _field(block, "text", "") for block in _field(message, "content", [])
                if _field(block, "type") == "text"
            ),
            "usage": _field(message, "usage"),
            "model_output": output_text_blocks(_field(message, "content", []) or []),
        }


class AnthropicStreamingProvider(AnthropicProvider):
    def send(self, client, request):
        with client.messages.stream(**request) as stream:
            return stream.get_final_message()
