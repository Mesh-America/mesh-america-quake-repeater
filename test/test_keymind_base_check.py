import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import check_keymind_base as c  # noqa: E402

INI = "  -D KEYMIND_BASE_VERSION='\"1.18.0.1\"'\n"
TAGS = [
    "v1.17.1.9-halo-keymind-cascade-dev-88c85108",
    "v1.18.0.1-halo-keymind-cascade-dev-03214a16",
    "v1.9.0-halo-keymind-cascade-dev-abcdef12",
    "quake-v1.18.0.2",
    "companion-v1.0.0a",
]


class KeymindBaseCheck(unittest.TestCase):
    def test_matching_base_passes(self):
        self.assertEqual(c.check(INI, TAGS), [])

    def test_numeric_not_text_ordering(self):
        self.assertEqual(c.newest_keymind_tag(TAGS), "1.18.0.1")

    def test_stale_base_fails(self):
        errors = c.check(INI.replace("1.18.0.1", "1.17.1.9"), TAGS)
        self.assertEqual(len(errors), 1)
        self.assertIn("1.18.0.1", errors[0])

    def test_missing_or_duplicate_define_fails(self):
        self.assertEqual(len(c.check("", TAGS)), 1)
        self.assertEqual(len(c.check(INI + INI.replace("1.18.0.1", "1.17.1.9"), TAGS)), 1)

    def test_no_keymind_tags_fails(self):
        self.assertEqual(len(c.check(INI, ["quake-v1.18.0.2"])), 1)


if __name__ == "__main__":
    unittest.main()
