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


class Reason:
    async def decide(self, now, normal):
        # Build supervisor.tool_catalog(), weigh `now` vs `normal`, call the local
        # OpenAI-compatible endpoint with the catalog as tools, validate the
        # returned tool_call with validate_tool_call(), then call_function / speak.
        ...
