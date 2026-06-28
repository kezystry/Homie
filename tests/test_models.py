"""ModelRegistry — switchable brains (general + fine-tuned dev), persisted.

Run: python3 -m unittest discover -s tests
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.models import ModelProfile, ModelRegistry


def reg(state=None):
    return ModelRegistry([
        ModelProfile("general", "http://x/8080", "homie", "general", "the everything brain"),
        ModelProfile("dev", "http://x/8081", "homie-dev", "dev", "fine-tuned for code"),
    ], state_path=state)


class RegistryTests(unittest.TestCase):
    def test_first_is_active_by_default(self) -> None:
        self.assertEqual(reg().active().name, "general")

    def test_switch(self) -> None:
        r = reg()
        self.assertTrue(r.switch("dev"))
        self.assertEqual(r.active().name, "dev")
        self.assertFalse(r.switch("nope"))               # unknown → no change
        self.assertEqual(r.active().name, "dev")

    def test_for_role_prefers_matching(self) -> None:
        r = reg()
        self.assertEqual(r.for_role("dev").name, "dev")
        self.assertEqual(r.for_role("general").name, "general")
        self.assertEqual(r.for_role("unknown").name, "general")   # falls back to active

    def test_switch_persists_across_reload(self) -> None:
        with TemporaryDirectory() as d:
            sp = Path(d) / "model.active"
            reg(sp).switch("dev")
            self.assertEqual(reg(sp).active().name, "dev")        # a new registry reads the choice

    def test_load_from_toml(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "models.toml"
            p.write_text('[model.general]\nurl="http://a"\nrole="general"\n'
                         '[model.dev]\nurl="http://b"\nmodel="dev"\n', "utf-8")
            r = ModelRegistry.load(p)
            self.assertEqual(set(r.names()), {"general", "dev"})
            self.assertEqual(r.get("dev").role, "dev")            # role inferred from the name

    def test_missing_toml_is_empty_registry(self) -> None:
        r = ModelRegistry.load("/no/such/models.toml")
        self.assertEqual(r.names(), [])
        self.assertIsNone(r.active())


if __name__ == "__main__":
    unittest.main()
