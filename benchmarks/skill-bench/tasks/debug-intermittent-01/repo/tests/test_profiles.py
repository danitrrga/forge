import unittest

from prefs.profiles import mute_notifications, new_profile, set_digest


class ProfileTest(unittest.TestCase):
    def test_defaults(self):
        prefs = new_profile("ana")["prefs"]
        self.assertEqual(prefs["theme"], "light")
        self.assertEqual(prefs["language"], "en")
        self.assertTrue(prefs["notifications"]["email"])

    def test_override_theme(self):
        profile = new_profile("ben", theme="dark")
        self.assertEqual(profile["prefs"]["theme"], "dark")

    def test_mute(self):
        profile = mute_notifications(new_profile("cleo"))
        self.assertFalse(profile["prefs"]["notifications"]["email"])
        self.assertFalse(profile["prefs"]["notifications"]["push"])

    def test_set_digest(self):
        profile = set_digest(new_profile("eve"), "daily")
        self.assertEqual(profile["prefs"]["notifications"]["digest"], "daily")


if __name__ == "__main__":
    unittest.main()
