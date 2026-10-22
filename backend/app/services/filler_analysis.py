
import re
from collections import Counter

# Keep this list explicit so filler counting is predictable.
FILLER_TERMS = (
    "you know",
    "i mean",
    "um",
    "umm",
    "uh",
    "uhm",
    "er",
    "ah",
    "like",
)

# Count technical expressions such as O(log n) as one token.
TOKEN_PATTERN = re.compile(
    r"O\s*\([^)]*\)|[A-Za-z]+(?:['’-][A-Za-z]+)*|\d+(?:\.\d+)?",
    re.IGNORECASE,
)

def analyze_fillers(transcript: str) -> dict:
    """
    Count recognized filler words and calculate their percentage
    of transcript tokens.

    This analyzes transcript text, not acoustic pauses or tone.
    """
    if not transcript or not transcript.strip():
        return {
            "counts": [],
            "repeated_phrases": [],
            "filler_percentage": 0.0,
            "suggested_pauses": [],
        }

    # Match longer phrases first, using word boundaries.
    alternatives = sorted(FILLER_TERMS, key=len, reverse=True)
    filler_pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(term) for term in alternatives)
        + r")(?!\w)",
        re.IGNORECASE,
    )

    matches = [match.group(0).lower() for match in filler_pattern.finditer(transcript)]
    counts = Counter(matches)

    # A phrase like "you know" counts as one filler occurrence,
    # but its two words still count as two transcript tokens.
    total_tokens = len(TOKEN_PATTERN.findall(transcript))
    filler_percentage = (
        (len(matches) / total_tokens) * 100 if total_tokens else 0.0
    )

    return {
        "counts": [
            {"word": word, "count": count}
            for word, count in sorted(counts.items())
        ],
        "repeated_phrases": [],
        "filler_percentage": round(filler_percentage, 2),
        "suggested_pauses": (
            ["Pause briefly instead of using filler words."]
            if matches
            else []
        ),
    }
