"""Runtime settings the UI can change: agent toggles, approval, model choice.

config.yaml supplies the defaults; anything saved here overrides them.
"""

from __future__ import annotations

from pydantic import BaseModel

from agents_core.config import AgentModelConfig, get_config
from agents_core.store.db import Setting, session

_KEY = "runtime"


class RuntimeSettings(BaseModel):
    enabled: dict[str, bool]
    require_approval: bool
    agents: dict[str, AgentModelConfig]

    def is_enabled(self, agent: str) -> bool:
        return self.enabled.get(agent, False)


def _defaults() -> RuntimeSettings:
    cfg = get_config()
    return RuntimeSettings(
        enabled=dict(cfg.defaults.enabled),
        require_approval=cfg.defaults.require_approval,
        agents={k: v.model_copy() for k, v in cfg.agents.items()},
    )


def get_settings() -> RuntimeSettings:
    base = _defaults()
    with session() as s:
        row = s.get(Setting, _KEY)
    if not row:
        return _locked(base)
    saved = row.value or {}
    merged = base.model_dump()
    merged["enabled"].update(saved.get("enabled", {}))
    if "require_approval" in saved:
        merged["require_approval"] = saved["require_approval"]
    for name, override in saved.get("agents", {}).items():
        if name in merged["agents"]:
            merged["agents"][name].update(override)
    return _locked(RuntimeSettings.model_validate(merged))


def _locked(settings: RuntimeSettings) -> RuntimeSettings:
    """In a public demo, running plans is never allowed, whatever is saved."""
    if get_config().deployment.demo:
        settings.enabled["execute"] = False
    return settings


def update_settings(patch: dict) -> RuntimeSettings:
    """Merge a partial update ({enabled:{...}, require_approval, agents:{name:{...}}})."""
    cfg = get_config()
    for name, override in patch.get("agents", {}).items():
        provider = override.get("provider")
        if provider and provider not in cfg.providers:
            raise ValueError(f"unknown provider {provider!r}")
    with session() as s:
        row = s.get(Setting, _KEY) or Setting(key=_KEY, value={})
        value = dict(row.value or {})
        if "enabled" in patch:
            value["enabled"] = {**value.get("enabled", {}), **patch["enabled"]}
        if "require_approval" in patch:
            value["require_approval"] = bool(patch["require_approval"])
        if "agents" in patch:
            agents = dict(value.get("agents", {}))
            for name, override in patch["agents"].items():
                agents[name] = {**agents.get(name, {}), **override}
            value["agents"] = agents
        row.value = value
        s.merge(row)
        s.commit()
    return get_settings()
