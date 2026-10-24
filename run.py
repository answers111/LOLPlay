"""Task and agent registration, construction, and single-task entry point."""

import os

from task import (
    Task001,
    Task002,
    Task003,
    Task004,
    Task005,
    Task006,
    Task007,
    Task008,
    Task009,
    Task010,
    Task011,
    Task012,
    Task013,
    Task014,
    Task015,
    Task016,
    Task017,
    Task018,
    Task019,
    Task020,
    Task021,
    Task022,
    Task023,
    Task024,
    Task025,
    Task026,
    Task027,
    Task028,
    Task029,
    Task030,
    Task031,
    Task032,
    Task033,
    Task034,
    Task035,
    Task036,
)


# Task classes are callable constructors; no per-task factory is needed.
TASKS = {
    "task001": Task001,
    "task002": Task002,
    "task003": Task003,
    "task004": Task004,
    "task005": Task005,
    "task006": Task006,
    "task007": Task007,
    "task008": Task008,
    "task009": Task009,
    "task010": Task010,
    "task011": Task011,
    "task012": Task012,
    "task013": Task013,
    "task014": Task014,
    "task015": Task015,
    "task016": Task016,
    "task017": Task017,
    "task018": Task018,
    "task019": Task019,
    "task020": Task020,
    "task021": Task021,
    "task022": Task022,
    "task023": Task023,
    "task024": Task024,
    "task025": Task025,
    "task026": Task026,
    "task027": Task027,
    "task028": Task028,
    "task029": Task029,
    "task030": Task030,
    "task031": Task031,
    "task032": Task032,
    "task033": Task033,
    "task034": Task034,
    "task035": Task035,
    "task036": Task036,
}


def require_agent_credentials(name, model=None):
    """Validate local credentials before a built-in agent calls the API."""
    if name in ("prompt", "prompt-stream") and (model or "").startswith("claude-"):
        if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")):
            raise RuntimeError("Missing ANTHROPIC_AUTH_TOKEN or CLAUDE_CODE_OAUTH_TOKEN; set it locally or use --env-file")
    elif name in ("prompt", "prompt-stream", "responses", "responses-stateless", "responses-stream"):
        if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_OAUTH_CREDENTIALS")):
            raise RuntimeError("Missing OPENAI_API_KEY; set it locally or use --env-file")


def _common_agent_options(args, env):
    """Constructor options shared by all built-in agents."""
    return {
        "env": env,
        "platform": "windows",
        "model": args.model or "gpt-6.1-sol",
        "reasoning_effort": args.reasoning_effort,
        "base_url": args.base_url,
    }


def _prompt_agent_options(args, env):
    """Add history, token, wait, and timeout options for prompt agents."""
    options = _common_agent_options(args, env)
    options.update(
        action_space=getattr(args, "action_space", "pydirectinput"),
        max_tokens=getattr(args, "max_tokens", None),
        max_trajectory_length=getattr(args, "max_trajectory_length", 3),
        wait_seconds=getattr(args, "wait_seconds", 1.0),
        request_timeout=getattr(args, "request_timeout", 120.0),
    )
    return options


# Import the selected agent only when creating it, keeping CLI help lightweight.
def create_prompt_agent(args, env):
    require_agent_credentials("prompt", args.model)
    from agents.prompt_agent import PromptAgent

    return PromptAgent(**_prompt_agent_options(args, env))


def create_streaming_prompt_agent(args, env):
    require_agent_credentials("prompt-stream", args.model)
    from agents.prompt_agent import StreamingPromptAgent

    return StreamingPromptAgent(**_prompt_agent_options(args, env))


def create_responses_agent(args, env):
    require_agent_credentials("responses")
    from agents.openai_responses import OpenAIResponseAgent

    return OpenAIResponseAgent(**_common_agent_options(args, env))


def create_stateless_responses_agent(args, env):
    require_agent_credentials("responses-stateless")
    from agents.openai_responses import OpenAIResponseStatelessAgent

    return OpenAIResponseStatelessAgent(**_common_agent_options(args, env))


def create_streaming_responses_agent(args, env):
    require_agent_credentials("responses-stream")
    from agents.openai_responses import OpenAIResponseStreamingAgent

    return OpenAIResponseStreamingAgent(**_common_agent_options(args, env))


AGENTS = {
    "prompt": create_prompt_agent,
    "prompt-stream": create_streaming_prompt_agent,
    "responses": create_responses_agent,
    "responses-stateless": create_stateless_responses_agent,
    "responses-stream": create_streaming_responses_agent,
}


def main(argv=None):
    """Delegate argument parsing and execution to run_single_task.py."""
    from run_single_task import main as single_task_main

    return single_task_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
