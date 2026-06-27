"""Cockpit launcher tests — the security-critical allowlist.

The launcher must only ever run an allowlisted (label -> fixed argv) entry, with
no shell and no user-supplied command string. These tests pin that contract.

Run: python3 -m unittest discover -s tests
"""
import unittest

from cockpit.launcher import App, DEFAULT_APPS, Launcher, LaunchError


class LauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spawned: list = []
        self.launcher = Launcher(spawn=lambda argv: self.spawned.append(argv) or argv)

    def test_default_apps_present(self) -> None:
        labels = self.launcher.labels()
        self.assertIn("stremio", labels)
        self.assertIn("steam", labels)
        self.assertIn("camera", labels)

    def test_launch_runs_fixed_argv(self) -> None:
        self.launcher.launch("stremio")
        self.assertEqual(len(self.spawned), 1)
        argv = self.spawned[0]
        # gamescope owns the display; the app is the nested client. A LIST, never
        # a shell string.
        self.assertEqual(argv[0], "gamescope")
        self.assertIn("stremio", argv)
        self.assertTrue(all(isinstance(a, str) for a in argv))

    def test_unknown_label_is_refused(self) -> None:
        with self.assertRaises(LaunchError):
            self.launcher.launch("rm -rf /")  # not a label; cannot be a command
        self.assertEqual(self.spawned, [])

    def test_get_unknown_raises(self) -> None:
        with self.assertRaises(LaunchError):
            self.launcher.get("definitely-not-an-app")

    def test_no_shell_metachars_in_any_argv(self) -> None:
        # argv lists are passed to Popen without a shell, so even if a value
        # contained a metachar it would be inert — but assert the allowlist is
        # clean anyway as a tripwire against someone adding `sh -c '...'`.
        for app in self.launcher.apps():
            self.assertNotIn("sh", app.argv[:1], f"{app.label} must not invoke a shell")
            for token in app.argv:
                self.assertNotIn(";", token)
                self.assertNotIn("|", token)
                self.assertNotIn("&", token)

    def test_camera_reads_local_device_not_bus(self) -> None:
        # the camera path is a local device read — never an event/bus topic
        cam = self.launcher.get("camera")
        joined = " ".join(cam.argv)
        self.assertIn("/dev/video0", joined)
        self.assertIn("v4l2", joined)

    def test_custom_allowlist_is_respected(self) -> None:
        only = (App("mpvtest", ("mpv", "x.mkv")),)
        l = Launcher(only, spawn=lambda argv: argv)
        self.assertEqual(l.labels(), ["mpvtest"])
        with self.assertRaises(LaunchError):
            l.launch("stremio")  # not in this allowlist

    def test_default_apps_are_frozen_dataclasses(self) -> None:
        for app in DEFAULT_APPS:
            self.assertIsInstance(app, App)
            with self.assertRaises(Exception):
                app.label = "mutated"  # frozen


if __name__ == "__main__":
    unittest.main()
