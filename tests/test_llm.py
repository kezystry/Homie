"""deploy.llm — pure request building + response parsing, against a faked transport.

No GPU, no model, no socket: a Transport stub returns canned `/v1/chat/completions`
bodies, so the brittle vendor-shape handling in `parse_completion` is exercised
deterministically. The async `propose()` path is covered with the same stub.

Run: python3 -m unittest discover -s tests
"""
import json
import unittest

from core.reason import Proposal, ToolCall
from deploy.llm import LLMClient, build_payload, parse_completion, render_context


def _resp(message: dict) -> dict:
    """Wrap a chat `message` in the OpenAI choices envelope."""
    return {"choices": [{"message": message}]}


class ParseCompletionTests(unittest.TestCase):
    def test_tool_call_with_string_arguments(self) -> None:
        # llama-server / OpenAI emit `arguments` as a JSON STRING.
        body = _resp({"tool_calls": [{"function": {"name": "add_reminder",
                                                   "arguments": '{"text": "milk"}'}}]})
        self.assertEqual(parse_completion(body),
                         Proposal(tool_call=ToolCall("add_reminder", {"text": "milk"})))

    def test_tool_call_with_dict_arguments(self) -> None:
        # Some servers hand back an already-parsed dict — accept that too.
        body = _resp({"tool_calls": [{"function": {"name": "agenda", "arguments": {}}}]})
        self.assertEqual(parse_completion(body), Proposal(tool_call=ToolCall("agenda", {})))

    def test_say_only(self) -> None:
        self.assertEqual(parse_completion(_resp({"content": "Welcome home."})),
                         Proposal(say="Welcome home."))

    def test_say_and_tool_call_both_present(self) -> None:
        body = _resp({"content": "On it.",
                      "tool_calls": [{"function": {"name": "agenda", "arguments": "{}"}}]})
        self.assertEqual(parse_completion(body),
                         Proposal(tool_call=ToolCall("agenda", {}), say="On it."))

    def test_blank_content_is_do_nothing(self) -> None:
        self.assertEqual(parse_completion(_resp({"content": "   "})), Proposal())

    def test_no_tool_call_no_content(self) -> None:
        self.assertEqual(parse_completion(_resp({"content": None, "tool_calls": []})), Proposal())

    def test_malformed_json_string(self) -> None:
        self.assertEqual(parse_completion("not json {{"), Proposal())

    def test_accepts_raw_str_body(self) -> None:
        self.assertEqual(parse_completion(json.dumps(_resp({"content": "hi"}))),
                         Proposal(say="hi"))

    def test_empty_choices(self) -> None:
        self.assertEqual(parse_completion({"choices": []}), Proposal())

    def test_missing_choices_key(self) -> None:
        self.assertEqual(parse_completion({"object": "chat.completion"}), Proposal())

    def test_unparseable_tool_arguments_distrusts_whole_call(self) -> None:
        # Bad arg JSON => we don't execute a half-understood call, and we don't fall
        # back to the say either — the safe default is to do nothing.
        body = _resp({"content": "ignored",
                      "tool_calls": [{"function": {"name": "x", "arguments": "{bad"}}]})
        self.assertEqual(parse_completion(body), Proposal())

    def test_tool_call_missing_name(self) -> None:
        self.assertEqual(parse_completion(_resp({"tool_calls": [{"function": {"arguments": "{}"}}]})),
                         Proposal())


class BuildPayloadTests(unittest.TestCase):
    def test_payload_shape(self) -> None:
        p = build_payload(system="SYS", context={"topic": "presence.arrived", "zone": "living"},
                          tools=[{"type": "function", "function": {"name": "agenda"}}],
                          model="homie", temperature=0.4)
        self.assertEqual(p["model"], "homie")
        self.assertEqual(p["messages"][0], {"role": "system", "content": "SYS"})
        self.assertEqual(p["messages"][1]["role"], "user")
        self.assertIn("presence.arrived", p["messages"][1]["content"])  # context rendered in
        self.assertEqual(p["tool_choice"], "auto")
        self.assertFalse(p["parallel_tool_calls"])  # one tool only (M6)
        self.assertFalse(p["stream"])

    def test_no_tools_omits_tool_keys(self) -> None:
        p = build_payload(system="S", context={}, tools=[], model="m", temperature=0.0)
        self.assertNotIn("tools", p)
        self.assertNotIn("tool_choice", p)
        self.assertNotIn("parallel_tool_calls", p)

    def test_grammar_passthrough(self) -> None:
        p = build_payload(system="S", context={}, tools=[], model="m", temperature=0.0,
                          grammar="root ::= \"yes\" | \"no\"")
        self.assertEqual(p["grammar"], "root ::= \"yes\" | \"no\"")
        self.assertNotIn("grammar",
                         build_payload(system="S", context={}, tools=[], model="m", temperature=0.0))

    def test_render_context_is_deterministic(self) -> None:
        ctx = {"b": 2, "a": 1}
        self.assertEqual(render_context(ctx), render_context(dict(ctx)))  # sort_keys => stable


class ProposeWithFakeTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_propose_routes_through_transport_and_parses(self) -> None:
        seen = {}

        def fake(url, payload, timeout):
            seen["url"], seen["payload"], seen["timeout"] = url, payload, timeout
            return json.dumps(_resp({"content": "Noted."}))

        client = LLMClient("http://127.0.0.1:9/v1/chat/completions", transport=fake, timeout=7)
        out = await client.propose(system="SYS", context={"topic": "x"}, tools=[])
        self.assertEqual(out, Proposal(say="Noted."))
        self.assertEqual(seen["url"], "http://127.0.0.1:9/v1/chat/completions")
        self.assertEqual(seen["timeout"], 7)
        self.assertEqual(seen["payload"]["messages"][0]["content"], "SYS")

    async def test_transport_failure_stands_down(self) -> None:
        def boom(url, payload, timeout):
            raise OSError("connection refused")

        client = LLMClient("http://127.0.0.1:9/v1/chat/completions", transport=boom)
        self.assertEqual(await client.propose(system="S", context={}, tools=[]), Proposal())


if __name__ == "__main__":
    unittest.main()
