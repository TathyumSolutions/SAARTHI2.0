"""
Settings read from a user's free-text Query Instructions (Settings page),
for behaviour users can tune in plain words instead of a dedicated form.

Each setting only reads a sentence that talks about that setting, so an
unrelated number elsewhere in the instructions can't change it.
"""
import re

# Minimum similarity for a past LIKED question to count as a match for the
# self-learning feedback shown in Chain of Thought / Related Queries.
DEFAULT_MATCH_THRESHOLD = 0.80

_MATCH_WORDS = re.compile(r"\b(match|matches|matching|matched|similar|similarity|threshold|related quer(y|ies))\b", re.I)
_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(%|percent\b)", re.I)
_FRACTION = re.compile(r"(?<![\d.])(0?\.\d+|1\.0+)(?![\d.%])")


def match_threshold_from_instructions(instructions: str, default: float = DEFAULT_MATCH_THRESHOLD) -> float:
    """e.g. "Query match threshold 90%" -> 0.90, "similarity threshold 0.85"
    -> 0.85. Falls back to `default` when no sentence about matching names
    a valid value (above 0, at most 100%)."""
    for sentence in re.split(r"[;\n]+|\.(?!\d)", instructions or ""):
        if not _MATCH_WORDS.search(sentence):
            continue
        percent = _PERCENT.search(sentence)
        if percent:
            value = float(percent.group(1)) / 100
        else:
            fraction = _FRACTION.search(sentence)
            if not fraction:
                continue
            value = float(fraction.group(1))
        if 0 < value <= 1:
            return value
    return default
