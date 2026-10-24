"""Free, offline duplicate detection for interview questions.

No network calls, no AI and no embeddings. A question is normalised, reduced
to its meaningful words, and compared against known questions in three ways:

* exact       - identical after normalisation
* equivalent  - same meaningful words, different wording or order
* near        - heavy word overlap plus high text similarity

This catches rewordings that share vocabulary. It cannot detect a paraphrase
that uses completely different words; that is an accepted trade-off for
keeping duplicate checks free.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

DEFAULT_JACCARD_THRESHOLD = 0.8
DEFAULT_SEQUENCE_THRESHOLD = 0.9

# Fuzzy matching on very short questions causes false positives, so
# questions with fewer meaningful words are compared by exact/equivalent only.
MIN_TOKENS_FOR_FUZZY = 3

# Skip the slower string comparison unless word overlap is at least this high.
FUZZY_PREFILTER = 0.5

MatchKind = Literal["exact", "equivalent", "near"]

_NUMBERING = re.compile(r"^\s*(?:q(?:uestion)?\s*)?\d+\s*[.):]\s+", re.IGNORECASE)

# Keep technical names intact before punctuation is stripped.
_SYMBOLS = (
    (re.compile(r"\bc\+\+"), "cpp"),
    (re.compile(r"\bc#"), "csharp"),
    (re.compile(r"\bf#"), "fsharp"),
    (re.compile(r"\bnode\.js\b"), "nodejs"),
    (re.compile(r"\.net\b"), " dotnet"),
)

_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for",
        "from", "with", "by", "as", "is", "are", "was", "were", "be", "been",
        "being", "do", "does", "did", "can", "could", "should", "would",
        "will", "shall", "may", "might", "what", "which", "who", "whom",
        "whose", "when", "where", "why", "how", "you", "your", "yours", "i",
        "me", "my", "we", "our", "us", "they", "their", "it", "its", "this",
        "that", "these", "those", "explain", "describe", "tell", "about",
        "give", "define", "discuss", "mention", "please", "briefly",
        "difference", "differences", "differ", "differs", "between",
        "versus", "vs", "compare", "interview", "question", "questions",
    }
)


def normalize_question(text: str) -> str:
    """Lowercase, strip numbering and punctuation, collapse whitespace."""
    value = unicodedata.normalize("NFKC", text or "")
    value = _NUMBERING.sub("", value).lower()
    for pattern, replacement in _SYMBOLS:
        value = pattern.sub(replacement, value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return value.strip()


def _stem(token: str) -> str:
    """Very light plural stripping so 'lists' and 'list' match."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 5 and token.endswith("sses"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def significant_tokens(text: str) -> frozenset[str]:
    """The meaningful words of a question, without filler and plurals."""
    return frozenset(
        _stem(token)
        for token in normalize_question(text).split()
        if token not in _STOPWORDS
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def exact_key(text: str) -> str:
    """Stable hash of the normalised text. Suitable for a unique DB column."""
    return _sha256(normalize_question(text))


def token_key(text: str) -> str:
    """Stable hash of the meaningful words, ignoring order and filler.

    Only meaningful when significant_tokens(text) is not empty.
    """
    return _sha256("|".join(sorted(significant_tokens(text))))


@dataclass(frozen=True)
class DuplicateMatch:
    kind: MatchKind
    score: float
    ref: Hashable | None


@dataclass
class _Entry:
    ref: Hashable | None
    normalized: str
    tokens: frozenset[str]


class QuestionDeduplicator:
    """In-memory index of known questions.

    Load existing database questions once with add(), then check each
    candidate with find_duplicate() or add_if_new(). Candidates accepted
    earlier in the same batch are indexed too, so a batch can't duplicate
    itself.
    """

    def __init__(
        self,
        jaccard_threshold: float = DEFAULT_JACCARD_THRESHOLD,
        sequence_threshold: float = DEFAULT_SEQUENCE_THRESHOLD,
    ) -> None:
        if not 0 < jaccard_threshold <= 1:
            raise ValueError("jaccard_threshold must be between 0 and 1")
        if not 0 < sequence_threshold <= 1:
            raise ValueError("sequence_threshold must be between 0 and 1")

        self._jaccard = jaccard_threshold
        self._sequence = sequence_threshold
        self._entries: list[_Entry] = []
        self._exact: dict[str, _Entry] = {}
        self._equivalent: dict[str, _Entry] = {}
        self._postings: dict[str, list[int]] = defaultdict(list)

    def __len__(self) -> int:
        return len(self._entries)

    def add(self, text: str, ref: Hashable | None = None) -> bool:
        """Index a question. Returns False if it has no usable text."""
        normalized = normalize_question(text)
        if not normalized:
            return False

        key = _sha256(normalized)
        if key in self._exact:
            return True  # already indexed

        tokens = significant_tokens(text)
        entry = _Entry(ref=ref, normalized=normalized, tokens=tokens)
        index = len(self._entries)
        self._entries.append(entry)
        self._exact[key] = entry

        if tokens:
            self._equivalent.setdefault(_sha256("|".join(sorted(tokens))), entry)
            for token in tokens:
                self._postings[token].append(index)
        return True

    def find_duplicate(self, text: str) -> DuplicateMatch | None:
        """Return the closest known duplicate, or None if the question is new."""
        normalized = normalize_question(text)
        if not normalized:
            return None

        entry = self._exact.get(_sha256(normalized))
        if entry is not None:
            return DuplicateMatch("exact", 1.0, entry.ref)

        tokens = significant_tokens(text)
        if not tokens:
            return None

        entry = self._equivalent.get(_sha256("|".join(sorted(tokens))))
        if entry is not None:
            return DuplicateMatch("equivalent", 1.0, entry.ref)

        if len(tokens) < MIN_TOKENS_FOR_FUZZY:
            return None

        # Only compare against questions that share at least one word.
        shared_counts: dict[int, int] = defaultdict(int)
        for token in tokens:
            for index in self._postings.get(token, ()):
                shared_counts[index] += 1

        best: DuplicateMatch | None = None
        for index, shared in shared_counts.items():
            candidate = self._entries[index]
            if len(candidate.tokens) < MIN_TOKENS_FOR_FUZZY:
                continue

            union = len(tokens) + len(candidate.tokens) - shared
            jaccard = shared / union

            score: float | None = None
            if jaccard >= self._jaccard:
                score = jaccard
            elif jaccard >= FUZZY_PREFILTER:
                ratio = SequenceMatcher(None, normalized, candidate.normalized).ratio()
                if ratio >= self._sequence:
                    score = ratio

            if score is not None and (best is None or score > best.score):
                best = DuplicateMatch("near", score, candidate.ref)

        return best

    def add_if_new(self, text: str, ref: Hashable | None = None) -> DuplicateMatch | None:
        """Index the question if it is new. Returns the match if it is a duplicate."""
        match = self.find_duplicate(text)
        if match is None:
            self.add(text, ref)
        return match


def build_deduplicator(
    existing: Iterable[tuple[Hashable, str]],
    jaccard_threshold: float = DEFAULT_JACCARD_THRESHOLD,
    sequence_threshold: float = DEFAULT_SEQUENCE_THRESHOLD,
) -> QuestionDeduplicator:
    """Build an index from (reference, question text) pairs."""
    deduplicator = QuestionDeduplicator(jaccard_threshold, sequence_threshold)
    for ref, text in existing:
        deduplicator.add(text, ref)
    return deduplicator