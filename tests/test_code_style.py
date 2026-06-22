import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODE_SUFFIXES = {".py", ".bat", ".sh"}
EMOJI_RANGES = (
    (0x2600, 0x27BF),
    (0x1F000, 0x1FAFF),
)


OUTPUT_MARKERS = (
    "print(",
    "ArgumentParser",
    "add_parser(",
    "add_argument(",
    "parser.error",
    "raise ValueError",
    "raise Exception",
    "raise RuntimeError",
    "raise PermissionError",
    "status_callback(",
    "echo ",
    "printf ",
    "info \"",
    "warn \"",
    "error \"",
    "success \"",
)


def contains_cjk(text):
    return any("\u4e00" <= char <= "\u9fff" for char in text)


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

    def test_runtime_output_text_is_short_english(self):
        offenders = []
        for path in ROOT.rglob("*"):
            if ".git" in path.parts or "tmp_test_output" in path.parts or path.suffix.lower() not in CODE_SUFFIXES:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith(("#", "REM ", "//")):
                    continue
                if contains_cjk(line) and any(marker in line for marker in OUTPUT_MARKERS):
                    offenders.append(f"{path.relative_to(ROOT)}:{lineno}:{stripped}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()