import os
import unittest

import build


class BuildTests(unittest.TestCase):
    def test_tokens_come_first(self):
        self.assertEqual(os.path.basename(build.sources()[0]), "tokens.css")

    def test_every_stylesheet_is_bundled(self):
        names = sorted(os.path.basename(p) for p in build.sources())
        self.assertEqual(names, ["buttons.css", "cards.css", "forms.css", "tokens.css"])
        self.assertIn(".btn-primary", build.bundle())


if __name__ == "__main__":
    unittest.main()
