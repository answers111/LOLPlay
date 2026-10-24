"""Select a provider without importing the other provider's SDK."""


def create_provider(model, *, stream=False):
    if model.startswith("claude-"):
        from .anthropic import AnthropicProvider, AnthropicStreamingProvider
        provider = AnthropicStreamingProvider if stream else AnthropicProvider
    else:
        from .openai import OpenAIProvider, OpenAIStreamingProvider
        provider = OpenAIStreamingProvider if stream else OpenAIProvider
    return provider()
