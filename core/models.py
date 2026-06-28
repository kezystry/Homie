"""ModelRegistry — switchable brains (a general one + a fine-tuned dev one).

The owner's idea: keep the big GENERAL brain that does everything, AND a same-size brain
**fine-tuned for development** — a specialist beats a generalist on its niche — and SWITCH
between them. This is the registry that makes the switch real: named model profiles (each an
OpenAI-compatible endpoint + served model id + a role), one active at a time, persisted so the
choice survives a restart.

It decides nothing about safety — the model is untrusted by construction (Charter law 1); this
only picks WHICH endpoint the cortex talks to. Pure stdlib, `tomllib` for the profile file.
"""
from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("homie.models")

KNOWN_ROLES = ("general", "dev")


@dataclass(frozen=True)
class ModelProfile:
    name: str
    url: str
    model: str = "homie"
    role: str = "general"
    note: str = ""


class ModelRegistry:
    """Named model profiles with one active. `state_path` (a small file under the state dir)
    persists the active choice across restarts; switching writes it."""

    def __init__(self, profiles: list[ModelProfile], *, active: str | None = None,
                 state_path: Path | str | None = None) -> None:
        self._profiles = {p.name: p for p in profiles}
        self._state_path = Path(state_path) if state_path else None
        self._active = (self._load_active() or active
                        or (next(iter(self._profiles), None)))

    @classmethod
    def load(cls, toml_path: Path | str, *, state_path: Path | str | None = None) -> "ModelRegistry":
        """Load profiles from a `[model.<name>]` TOML. Missing/unreadable → an empty registry
        (the cortex then falls back to its single HOMIE_LLM_URL, exactly as before)."""
        profiles: list[ModelProfile] = []
        try:
            raw = tomllib.loads(Path(toml_path).read_text("utf-8"))
        except FileNotFoundError:
            raw = {}
        except Exception as ex:
            log.warning("models: %s unreadable (%r); no profiles", toml_path, ex)
            raw = {}
        for name, body in (raw.get("model") or {}).items():
            url = body.get("url")
            if not url:
                continue
            role = body.get("role") or (name if name in KNOWN_ROLES else "general")
            profiles.append(ModelProfile(name=name, url=url, model=body.get("model", "homie"),
                                         role=role, note=body.get("note", "")))
        return cls(profiles, state_path=state_path)

    # -- reads ---------------------------------------------------------------- #
    def names(self) -> list[str]:
        return list(self._profiles)

    def profiles(self) -> list[ModelProfile]:
        return list(self._profiles.values())

    def get(self, name: str) -> ModelProfile | None:
        return self._profiles.get(name)

    def active(self) -> ModelProfile | None:
        return self._profiles.get(self._active) if self._active else None

    def for_role(self, role: str) -> ModelProfile | None:
        """The brain to use for a role: the active one if it matches, else the first profile of
        that role, else the active one (a graceful fallback, never None when any profile exists)."""
        a = self.active()
        if a and a.role == role:
            return a
        for p in self._profiles.values():
            if p.role == role:
                return p
        return a

    # -- switch (persisted) --------------------------------------------------- #
    def switch(self, name: str) -> bool:
        if name not in self._profiles:
            return False
        self._active = name
        self._save_active()
        return True

    def _load_active(self) -> str | None:
        if self._state_path is None:
            return None
        try:
            name = self._state_path.read_text("utf-8").strip()
            return name if name in self._profiles else None
        except OSError:
            return None

    def _save_active(self) -> None:
        if self._state_path is None or self._active is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(self._active, "utf-8")
        except OSError as ex:
            log.warning("models: could not persist active model (%r)", ex)
