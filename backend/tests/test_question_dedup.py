import pytest

from app.services.question_dedup import (
    QuestionDeduplicator,
    build_deduplicator,
    exact_key,
    normalize_question,
    significant_tokens,
    token_key,
)

LIST_TUPLE = "What is the difference between a list and a tuple in Python?"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  3. What is a Stack?! ", "what is a stack"),
        ("Q2) Explain Big-O notation", "explain big o notation"),
        ("What is C++?", "what is cpp"),
        ("C# vs F#", "csharp vs fsharp"),
        ("Node.js event loop?", "nodejs event loop"),
        ("What is .NET?", "what is dotnet"),
        ("   ", ""),
        ("?!", ""),
        ("", ""),
    ],
)
def test_normalize_question(raw, expected):
    assert normalize_question(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("What are Python decorators?", {"python", "decorator"}),
        ("Explain the difference between processes and threads", {"process", "thread"}),
        (
            "Classes, status, analysis and queries",
            {"class", "status", "analysis", "query"},
        ),
    ],
)
def test_significant_tokens_drop_filler_words_and_plurals(raw, expected):
    assert significant_tokens(raw) == frozenset(expected)


def test_exact_key_ignores_case_and_punctuation():
    key = exact_key("What is X?")
    assert key == exact_key("  what is x ")
    assert len(key) == 64
    int(key, 16)  # a valid hex digest
    assert key != exact_key("What is Y?")


def test_token_key_ignores_order_and_filler_words():
    assert token_key("list vs tuple in Python") == token_key("Python tuple list")
    assert token_key("list vs tuple in Python") != token_key("list vs set in Python")


def test_exact_duplicate_returns_the_stored_reference():
    dedup = QuestionDeduplicator()
    dedup.add(LIST_TUPLE, ref=42)

    match = dedup.find_duplicate(
        "what is the DIFFERENCE between a list and a tuple in python"
    )

    assert match is not None
    assert match.kind == "exact"
    assert match.score == 1.0
    assert match.ref == 42


@pytest.mark.parametrize(
    "reworded",
    [
        "Difference between tuple and list in Python",
        "Python: list vs tuple?",
        "What are the differences between lists and tuples in Python?",
    ],
)
def test_reworded_questions_with_the_same_meaning_are_equivalent(reworded):
    dedup = QuestionDeduplicator()
    dedup.add(LIST_TUPLE, ref=1)

    match = dedup.find_duplicate(reworded)

    assert match is not None
    assert match.kind == "equivalent"
    assert match.ref == 1


def test_near_duplicate_is_detected():
    dedup = QuestionDeduplicator()
    dedup.add(LIST_TUPLE, ref=7)

    match = dedup.find_duplicate(
        "What is the difference between a list and a tuple in Python 3?"
    )

    assert match is not None
    assert match.kind == "near"
    assert match.ref == 7
    assert 0.9 <= match.score < 1.0


def test_near_duplicate_detection_respects_stricter_thresholds():
    dedup = QuestionDeduplicator(jaccard_threshold=0.99, sequence_threshold=0.99)
    dedup.add(LIST_TUPLE, ref=7)

    assert (
        dedup.find_duplicate("What is the difference between a list and a tuple in Python 3?")
        is None
    )


@pytest.mark.parametrize(
    "different",
    [
        "How do I reverse a linked list in Java?",
        "What is a Python decorator?",
        "What is the difference between a stack and a queue?",
        "Explain how a hash map handles collisions",
        "Compare lists and tuples in Python for performance",
    ],
)
def test_unrelated_or_only_related_questions_are_not_duplicates(different):
    dedup = QuestionDeduplicator()
    dedup.add(LIST_TUPLE, ref=1)

    assert dedup.find_duplicate(different) is None


def test_very_short_questions_are_never_fuzzy_matched():
    dedup = QuestionDeduplicator()
    dedup.add("What is a heap?", ref=1)

    assert dedup.find_duplicate("What is a stack?") is None
    assert dedup.find_duplicate("What is a heap data structure?") is None


def test_programming_language_names_stay_distinct():
    dedup = QuestionDeduplicator()
    dedup.add("What is C++?", ref=1)

    assert dedup.find_duplicate("What is C?") is None
    assert dedup.find_duplicate("What is C#?") is None
    assert dedup.find_duplicate("what is c++") is not None


def test_a_batch_cannot_duplicate_itself():
    dedup = QuestionDeduplicator()

    assert dedup.add_if_new("What is a decorator in Python?", ref="first") is None

    match = dedup.add_if_new("Python decorator, what is it?", ref="second")
    assert match is not None
    assert match.kind == "equivalent"
    assert match.ref == "first"
    assert len(dedup) == 1

    assert dedup.add_if_new("How does Python manage memory?", ref="third") is None
    assert len(dedup) == 2


def test_build_deduplicator_indexes_existing_questions():
    dedup = build_deduplicator(
        [(1, LIST_TUPLE), (2, "How does Python manage memory?")]
    )

    match = dedup.find_duplicate("how does python manage memory")

    assert len(dedup) == 2
    assert match is not None
    assert match.ref == 2


def test_unusable_text_is_ignored():
    dedup = QuestionDeduplicator()

    assert dedup.add("   ?!  ") is False
    assert dedup.add("") is False
    assert dedup.find_duplicate("") is None
    assert dedup.find_duplicate("???") is None
    assert len(dedup) == 0


@pytest.mark.parametrize(
    ("jaccard", "sequence"),
    [(0, 0.9), (0.8, 0), (1.5, 0.9)],
)
def test_invalid_thresholds_are_rejected(jaccard, sequence):
    with pytest.raises(ValueError):
        QuestionDeduplicator(jaccard_threshold=jaccard, sequence_threshold=sequence)