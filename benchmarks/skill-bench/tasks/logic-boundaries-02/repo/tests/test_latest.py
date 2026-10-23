import os
import tempfile
import unittest

from logtools.latest import latest_log


class LatestLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def touch(self, name, mtime):
        path = os.path.join(self.dir, name)
        with open(path, "w") as fh:
            fh.write("x\n")
        os.utime(path, (mtime, mtime))

    def test_empty_directory(self):
        self.assertIsNone(latest_log(r'^access.log.[0-9]+$', self.dir))

    def test_no_file_matches(self):
        self.touch("error.log", 100)
        self.touch("access.log.old", 200)
        self.assertIsNone(latest_log(r'^access.log.[0-9]+$', self.dir))


if __name__ == '__main__':
    unittest.main()
