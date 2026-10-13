"""Regression tests for OTR display, matching, and sorting article rules."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from title_articles import canonical_title, title_match_key, title_sort_key

class TitleArticleTests(unittest.TestCase):
    def test_canonical_examples(self):
        cases = {
            "The Shrunken Head": "Shrunken Head [The]",
            "A Case for Mr. Carrington": "Case for Mr. Carrington [A]",
            "An Eye for an Eye": "Eye for an Eye [An]",
            "the Secret": "Secret [The]",
            "AN HOUR": "HOUR [An]",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(canonical_title(source), expected)

    def test_idempotent(self):
        for title in ("Shrunken Head [The]", "Eye for an Eye [An]",
                      "Death Has a Thirst", "Theatre", "", None):
            self.assertEqual(canonical_title(canonical_title(title)), canonical_title(title))

    def test_article_aware_keys(self):
        for first, second in (
            ("The Shrunken Head", "Shrunken Head [The]"),
            ("AN EYE FOR AN EYE", "Eye for an Eye [An]"),
            ("A Case", "Case [A]"),
        ):
            with self.subTest(first=first):
                self.assertEqual(title_match_key(first), title_match_key(second))
                self.assertEqual(title_sort_key(first), title_sort_key(second))

    def test_non_articles_are_untouched(self):
        self.assertEqual(canonical_title("Another Case"), "Another Case")
        self.assertNotEqual(title_match_key("A Case"), title_match_key("Another Case"))
        self.assertNotEqual(title_match_key("The Case"), title_match_key("The Other Case"))

if __name__ == "__main__":
    unittest.main()
