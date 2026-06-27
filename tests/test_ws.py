"""WebSocket codec tests — the pure, server-free half of core/ws.py.

The live connect path needs a real socket, but the parts that MUST be exactly right
(the handshake-accept hash and the frame masking/length encoding) are pure functions
and are pinned here against RFC 6455's own worked example.

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.ws import OP_PING, OP_TEXT, accept_key, encode_frame, parse_frame


class AcceptKeyTests(unittest.TestCase):
    def test_rfc6455_vector(self):
        # The example from RFC 6455 §1.3.
        self.assertEqual(accept_key("dGhlIHNhbXBsZSBub25jZQ=="),
                         "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")


class FrameCodecTests(unittest.TestCase):
    def test_roundtrip_short(self):
        payload = b"hello home"
        fin, opcode, body = parse_frame(encode_frame(payload, mask_key=b"\x01\x02\x03\x04"))
        self.assertTrue(fin)
        self.assertEqual(opcode, OP_TEXT)
        self.assertEqual(body, payload)

    def test_client_frame_is_masked(self):
        # Client->server frames MUST set the mask bit (RFC 6455 §5.3).
        frame = encode_frame(b"x", mask_key=b"\x00\x00\x00\x00")
        self.assertTrue(frame[1] & 0x80)

    def test_roundtrip_medium_126_length(self):
        payload = b"A" * 200  # forces the 16-bit extended length path
        fin, opcode, body = parse_frame(encode_frame(payload, mask_key=b"\x09\x08\x07\x06"))
        self.assertTrue(fin)
        self.assertEqual(body, payload)

    def test_roundtrip_unicode_text(self):
        payload = "Küche → Flur".encode("utf-8")
        _, _, body = parse_frame(encode_frame(payload))
        self.assertEqual(body, payload)

    def test_random_mask_still_roundtrips(self):
        # No injected key -> os.urandom mask; parse must still recover the payload.
        payload = b'{"type":"auth_ok"}'
        _, _, body = parse_frame(encode_frame(payload))
        self.assertEqual(body, payload)

    def test_partial_frame_returns_none(self):
        full = encode_frame(b"A" * 300, mask_key=b"\x01\x01\x01\x01")
        self.assertIsNone(parse_frame(full[:3]))  # header says 300 bytes; we have 3

    def test_opcode_preserved(self):
        _, opcode, _ = parse_frame(encode_frame(b"ping?", opcode=OP_PING, mask_key=b"\x02\x02\x02\x02"))
        self.assertEqual(opcode, OP_PING)


if __name__ == "__main__":
    unittest.main()
