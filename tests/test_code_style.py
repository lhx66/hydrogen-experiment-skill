import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODE_SUFFIXES = {".py", ".bat", ".sh"}
EMOJI_RANGES = (
    (0x2600, 0x27BF),
    (0x1F000, 0x1FAFF),
)


def contains_emoji(text):
    for char in text:
        codepoint = ord(char)
        if any(start <= codepoint <= end for start, end in EMOJI_RANGES):
            return True
    return False


class CodeStyleTests(unittest.TestCase):
    def test_code_files_do_not_contain_emoji(self):
        offenders = []
        for path in ROOT.rglob("*"):
            if ".git" in path.parts or path.suffix.lower() not in CODE_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8")
            if contains_emoji(text):
                offenders.append(str(path.relative_to(ROOT)))

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
