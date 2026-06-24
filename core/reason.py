"""Reason — the local LLM decision.

Weighs the current moment against Remember's notion of normal and decides what,
if anything, to do. Runs entirely on the reasoning node; nothing leaves the network.

Reason proposes; the bus disposes. It calls tile functions (which act only through
their declared actuators, arbitrated by the bus) or speaks — it never drives the
home directly. Because the model is abliterated/uncensored, every tool call is
validated STRUCTURALLY against the live tool catalog before execution: safety is a
property of the architecture (validation + per-tile permissions + arbitration),
not of the model's manners.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import NamedTuple, Protocol

from core.tile import Event

log = logging.getLogger("homie.reason")


def validate_tool_call(catalog: list[dict], name: str, arguments: dict) -> list[str]:
    """Structural gate for a model-proposed tool call against the tool catalog
    (the OpenAI-style list from Supervisor.tool_catalog()). Returns a list of
    errors — empty means the call is safe to execute. Rejects hallucinated names,
    missing required args, unexpected args, and type mismatches."""
    fn = next((t["function"] for t in catalog if t.get("function", {}).get("name") == name), None)
    if fn is None:
        return [f"unknown function '{name}'"]
    if not isinstance(arguments, dict):
        return [f"arguments for '{name}' must be an object"]
    params = fn.get("parameters", {})
    props = params.get("properties", {})
    required = set(params.get("required", []))
    errors = []
    for missing in sorted(required - arguments.keys()):
        errors.append(f"missing required arg '{missing}'")
    for key, val in arguments.items():
        if key not in props:
            errors.append(f"unexpected arg '{key}'")  # also catches an injected 'ctx'
        elif not _json_type_ok(val, props[key].get("type", "string")):
            errors.append(f"arg '{key}' must be {props[key].get('type')}")
    return errors


def _json_type_ok(value, json_type: str) -> bool:
    if json_type == "string":
        return isinstance(value, str)
    if json_type == "boolean":
        return isinstance(value, bool)
    if json_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if json_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if json_type == "array":
        return isinstance(value, list)
    if json_type == "object":
        return isinstance(value, dict)
    return True  # unknown declared type — don't block


# --------------------------------------------------------------------------- #
# The reasoning cortex
# --------------------------------------------------------------------------- #
# Perception topics the cortex may wake on — the same family Remember learns from.
PERCEPTION = ("presence.**", "motion.**", "occupancy.**")
# Events/day below which a (topic, zone, hour) is rare enough to be worth reasoning
# about. The cheap predicate that keeps the GPU asleep for the ~95% routine case.
WAKE_RATE = 0.1

SYSTEM_PROMPT = (
    "You are Homie, a private, local home intelligence. Given a situation, you may "
    "call exactly one of the provided tools, say one short sentence, or do nothing. "
    "Prefer doing nothing unless the moment is genuinely unusual or useful. You have "
    "no way to control locks, heating, or anything safety-critical, and must not try."
)


class ToolCall(NamedTuple):
    name: str
    arguments: dict


@dataclass(frozen=True)
class Proposal:
    """What the model proposes: a tool call, a spoken line, both, or neither
    (the do-nothing default)."""

    tool_call: ToolCall | None = None
    say: str | None = None


class LLMClient(Protocol):
    """The single seam to the local model. The real impl wraps the OpenAI-compatible
    llama.cpp/Ollama endpoint on the 3060 (grammar-constrained tool decoding); tests
    fake it. Keeping the seam at the Proposal level means the chat template, quant,
    and serving choice all live in deploy/ and never touch the testable loop."""

    async def propose(self, *, system: str, context: dict, tools: list[dict]) -> Proposal: ...


def should_wake(exp) -> bool:
    """The novelty gate: a pure, cheap predicate over Remember's Expectation. True
    only when the moment is novel or rare — so the LLM is the exception path, not
    the rule. Shares Security's `novel or rate < threshold` notion of unusual."""
    return bool(getattr(exp, "novel", False)) or getattr(exp, "rate", 0.0) < WAKE_RATE


def build_context(event: Event, exp) -> dict:
    """Assemble the prompt context for the model from the event and what Remember
    expects here. A plain dict — the deploy-side client renders it into a prompt."""
    return {
        "topic": event.topic,
        "zone": event.payload.get("zone"),
        "ts": event.ts,
        "payload": dict(event.payload),
        "expectation": {"rate": getattr(exp, "rate", None), "novel": getattr(exp, "novel", None)},
    }


class Reason:
    """The reasoning cortex. Subscribes to perception, wakes the local LLM only on
    novelty, and turns a *validated* proposal into a tile-function call or a spoken
    line. It PROPOSES — it never publishes `actuator.requested` and never drives the
    home directly. That is the structural guarantee that makes the abliterated model
    safe: every effect is mediated by a tile's declared permissions and the bus's
    priority arbitration, regardless of what the model says.
    """

    def __init__(self, bus, llm: LLMClient, supervisor, remember, *, system_prompt: str = SYSTEM_PROMPT) -> None:
        self.bus = bus
        self.llm = llm
        self.sup = supervisor
        self.remember = remember
        self.system = system_prompt
        self._subs: list = []
        self._inflight: set = set()  # zones with a decision in progress (drop-coalesce bursts)

    async def start(self) -> None:
        self._subs = [self.bus.subscribe(p, self._on_event, owner="reason") for p in PERCEPTION]

    async def stop(self) -> None:
        for s in self._subs:
            self.bus.unsubscribe(s)
        self._subs = []

    async def _on_event(self, event: Event) -> None:
        zone = event.payload.get("zone")
        exp = await self.remember.normal(event.topic, zone, event.ts)
        if not should_wake(exp):
            return  # an established pattern — the cheap path; the GPU stays asleep
        key = zone or event.topic
        if key in self._inflight:
            return  # a decision for this zone is already running — coalesce the burst
        self._inflight.add(key)
        try:
            await self.decide(event, exp)
        finally:
            self._inflight.discard(key)

    async def decide(self, event: Event, exp) -> None:
        """Wake the model, validate what it proposes, and route it — never drive."""
        tools = self.sup.tool_catalog()
        try:
            proposal = await self.llm.propose(system=self.system, context=build_context(event, exp), tools=tools)
        except Exception as ex:  # a model/serving failure must never crash the bus
            log.warning("reason: LLM propose failed (%r); standing down", ex)
            return
        if proposal is None:
            return
        if proposal.say:
            await self.bus.publish(Event("interface.say", event.ts, {"text": proposal.say}, source="reason"))
        call = proposal.tool_call
        if call is None:
            return
        errors = validate_tool_call(tools, call.name, call.arguments)
        if errors:  # hallucinated / malformed — rejected, never executed
            log.warning("reason: rejected tool call %s%r: %s", call.name, call.arguments, "; ".join(errors))
            return
        try:
            # the tile runs the function and acts only through ITS declared actuators,
            # arbitrated by the bus — Reason holds no actuator path of its own.
            await self.sup.call_function(call.name, **call.arguments)
        except Exception as ex:
            log.warning("reason: tool call %s failed (%r)", call.name, ex)
