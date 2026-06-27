"""The real LLMClient — the deploy-side seam to the local model.

`core/reason.py` defines the `LLMClient` Protocol (one method: `propose(*, system,
context, tools) -> Proposal`) and keeps the testable cortex loop free of any chat
template, quant, or serving detail. THIS file is where those details live. It POSTs
to a local OpenAI-compatible endpoint — `llama-server` (the decided choice) or Ollama
on `127.0.0.1` — at `/v1/chat/completions`, then turns the response into a `Proposal`.

Design constraints honoured here:
  * STDLIB ONLY (`urllib.request` + `json`) so importing this never drags a dependency
    into the in-process daemon path. The Pi anchor that never sets `HOMIE_LLM_URL`
    never even imports the network code path at runtime.
  * The single HTTP round-trip is isolated behind a `Transport` seam, so the response
    PARSING (`parse_completion`) is a pure function testable with a fake transport and
    no socket. That is where all the brittle vendor-shape handling is concentrated.
  * Failure is always SILENT-SAFE: a serving error, an HTTP error, malformed JSON, an
    untrustworthy tool call, or an empty answer all collapse to `Proposal()` — "do
    nothing". `Reason.decide` additionally wraps `propose()` in try/except, but we keep
    the client itself defensive so a flaky model can never crash or mis-drive the home.

Nothing here decides safety. Reason validates every proposed tool call STRUCTURALLY
against the live catalog (`validate_tool_call`) and routes it through the owning tile's
declared actuators; the bus arbitrates. The model is untrusted by construction, so this
client only needs to be HONEST about what the model said — never to police it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Callable

from core.reason import Proposal, ToolCall

log = logging.getLogger("homie.deploy.llm")

# Endpoint + decoding knobs. All overridable by env so the GGUF/quant/serving choice
# stays in deploy/ and out of the code. Defaults match the decided setup: an 8B
# abliterated model at Q5_K_M served by llama-server on loopback (docs/PLAN.md "Reason").
DEFAULT_URL = "http://127.0.0.1:8080/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("HOMIE_LLM_MODEL", "homie")  # llama-server ignores; Ollama needs it
DEFAULT_TEMPERATURE = float(os.environ.get("HOMIE_LLM_TEMPERATURE", "0.4"))
DEFAULT_TIMEOUT = float(os.environ.get("HOMIE_LLM_TIMEOUT", "30"))  # seconds; the GPU is on-box


# --------------------------------------------------------------------------- #
# Pure request building + response parsing (no I/O — unit-testable)
# --------------------------------------------------------------------------- #
def render_context(context: dict) -> str:
    """Render Reason's context dict into the user-turn text. Deterministic and
    compact: the model gets the topic, zone, time, payload, and what Remember
    expected here. Pretty-printed JSON keeps it legible to an instruct model
    without us hand-templating prose (and stays stable for golden tests)."""
    body = json.dumps(context, indent=2, sort_keys=True, default=str)
    return (
        "A situation just occurred in the home. Here is the structured context:\n\n"
        f"{body}\n\n"
        "Decide what to do. Call exactly one tool if action is warranted, or reply "
        "with one short sentence to speak, or do nothing."
    )


def build_payload(*, system: str, context: dict, tools: list[dict], model: str,
                  temperature: float) -> dict:
    """Assemble the OpenAI-compatible chat-completions request body. `tool_choice`
    stays "auto" — the model may legitimately choose to say nothing or just speak,
    which the two-tier gate expects (do-nothing is the common case even on wake)."""
    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": render_context(context)},
        ],
        "temperature": temperature,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


def parse_completion(body: object) -> Proposal:
    """Pure: an OpenAI `/v1/chat/completions` response (raw str/bytes or an
    already-parsed dict) -> Proposal. The single place that knows the response
    shape, so all the vendor-quirk handling is here and unit-tested.

    Rules (all roads lead to a safe default):
      * Unparseable JSON / missing `choices` / empty `choices`  -> Proposal()  (do nothing)
      * `tool_calls[0].function` with a non-empty name + dict args -> ToolCall
          - `arguments` may be a JSON STRING (OpenAI/llama-server) or already a dict;
            a string that won't parse, or a missing name, means an UNTRUSTWORTHY call
            -> Proposal() rather than executing something half-understood.
      * `content` (trimmed, non-empty)                          -> say
      * both present                                            -> both on the Proposal
      * neither                                                 -> Proposal()
    """
    try:
        data = json.loads(body) if isinstance(body, (str, bytes, bytearray)) else body
        message = data["choices"][0].get("message") or {}
    except (ValueError, KeyError, TypeError, IndexError):
        return Proposal()
    if not isinstance(message, dict):
        return Proposal()

    call: ToolCall | None = None
    tool_calls = message.get("tool_calls") or []
    if isinstance(tool_calls, list) and tool_calls:
        fn = (tool_calls[0] or {}).get("function") or {}
        name = fn.get("name")
        raw_args = fn.get("arguments", {})
        if isinstance(raw_args, str):
            try:
                raw_args = json.loads(raw_args) if raw_args.strip() else {}
            except ValueError:
                raw_args = None  # the model emitted bad arg JSON -> distrust the whole call
        if isinstance(name, str) and name and isinstance(raw_args, dict):
            call = ToolCall(name=name, arguments=raw_args)
        else:
            return Proposal()  # a tool call we can't trust -> do nothing, don't fall through to say

    content = message.get("content")
    say = content.strip() if isinstance(content, str) and content.strip() else None

    if call is None and say is None:
        return Proposal()
    return Proposal(tool_call=call, say=say)


# --------------------------------------------------------------------------- #
# The HTTP seam (the ONLY I/O — swap it out in tests)
# --------------------------------------------------------------------------- #
# A Transport takes the request URL + body dict + timeout and returns the raw response
# text. urllib is blocking, so the default transport is run in a thread by the async
# client; tests inject a synchronous fake and never touch a socket.
Transport = Callable[[str, dict, float], str]


def urllib_post(url: str, payload: dict, timeout: float) -> str:
    """Default transport: one blocking POST of JSON, returning the response body text.
    Raises on transport/HTTP error so the caller can stand down (-> Proposal())."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    # Loopback only; no proxy, no auth — the server is on the same box (the 3060).
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (loopback, our own server)
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


class LLMClient:
    """The real `core.reason.LLMClient`. Wraps the loopback OpenAI-compatible endpoint;
    builds the request, runs the one blocking HTTP call off the event loop, and parses
    the response into a Proposal. Defensive end-to-end: any failure -> Proposal()."""

    def __init__(
        self,
        url: str | None = None,
        *,
        model: str = DEFAULT_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Transport = urllib_post,
    ) -> None:
        self.url = url or os.environ.get("HOMIE_LLM_URL", DEFAULT_URL)
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self._transport = transport

    async def propose(self, *, system: str, context: dict, tools: list[dict]) -> Proposal:
        payload = build_payload(
            system=system, context=context, tools=tools,
            model=self.model, temperature=self.temperature,
        )
        try:
            # Off-load the blocking urllib call so the bus loop is never stalled by the GPU.
            raw = await asyncio.to_thread(self._transport, self.url, payload, self.timeout)
        except (urllib.error.URLError, OSError, TimeoutError) as ex:
            log.warning("llm: request to %s failed (%r); standing down", self.url, ex)
            return Proposal()
        return parse_completion(raw)


def client_from_env() -> LLMClient:
    """Construct the client from the environment. Called by the daemon ONLY when
    HOMIE_LLM_URL is set, so the Pi anchor (no GPU, no model) never builds it."""
    return LLMClient(os.environ["HOMIE_LLM_URL"])
