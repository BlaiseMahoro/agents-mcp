from agents_core.config import get_config
from agents_core.providers.base import FinalText, Provider, ProviderError, Tool, ToolResult
from agents_core.store.settings import get_settings


def provider_for(agent: str) -> Provider:
    """Build the provider for an agent using the current runtime settings."""
    agent_cfg = get_settings().agents[agent]
    provider_cfg = get_config().providers[agent_cfg.provider]
    if provider_cfg.type == "anthropic":
        from agents_core.providers.anthropic import AnthropicProvider

        return AnthropicProvider(provider_cfg, agent_cfg)
    from agents_core.providers.openai_compat import OpenAICompatProvider

    return OpenAICompatProvider(provider_cfg, agent_cfg)


__all__ = ["FinalText", "Provider", "ProviderError", "Tool", "ToolResult", "provider_for"]
