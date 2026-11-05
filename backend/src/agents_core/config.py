"""Static configuration from config.yaml (providers, models, sandbox).

Runtime toggles (agent on/off, approval, chosen model) live in the settings
table so the UI can change them; see store/settings.py.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[3]


class ProviderConfig(BaseModel):
    type: Literal["anthropic", "openai_compat"]
    base_url: str | None = None
    api_key_env: str | None = None  # env var holding the key, if the endpoint needs one
    fallbacks: bool = True  # anthropic only: server-side refusal fallbacks


class AgentModelConfig(BaseModel):
    provider: str
    model: str
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    search: Literal["native", "searxng"] = "native"  # research only
    max_searches: int = 8


class SearchConfig(BaseModel):
    searxng_url: str = "http://localhost:8888"
    max_results: int = 8
    fetch_max_chars: int = 20_000


class SandboxConfig(BaseModel):
    image: str = "agents-sandbox:latest"
    network: bool = True
    cpus: float = 2.0
    memory: str = "2g"
    step_timeout_s: int = 120
    allowed_step_types: list[str] = Field(default_factory=lambda: ["shell", "write_file", "read_file", "llm_task"])


class Defaults(BaseModel):
    require_approval: bool = True
    enabled: dict[str, bool] = Field(default_factory=lambda: {"research": True, "plan": True, "execute": True})


class AppConfig(BaseModel):
    providers: dict[str, ProviderConfig]
    agents: dict[str, AgentModelConfig]
    search: SearchConfig = SearchConfig()
    sandbox: SandboxConfig = SandboxConfig()
    defaults: Defaults = Defaults()
    data_dir: Path = REPO_ROOT / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "agents.db"

    @property
    def workspaces_dir(self) -> Path:
        return self.data_dir / "workspaces"


def config_path() -> Path:
    return Path(os.environ.get("AGENTS_CONFIG", REPO_ROOT / "config.yaml"))


@lru_cache
def get_config() -> AppConfig:
    raw = yaml.safe_load(config_path().read_text())
    cfg = AppConfig.model_validate(raw)
    if not cfg.data_dir.is_absolute():
        cfg.data_dir = (REPO_ROOT / cfg.data_dir).resolve()
    cfg.workspaces_dir.mkdir(parents=True, exist_ok=True)
    return cfg
