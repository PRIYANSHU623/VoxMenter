
from app.services.filler_analysis import analyze_fillers

def test_sample_transcript():
    transcript = (
        "Binary search has O(log n) time complexity  um because "
        "it divides the search  umm uh space in half at each step."
    )

    result = analyze_fillers(transcript)
    counts = {item["word"]: item["count"] for item in result["counts"]}

    assert counts == {"uh": 1, "um": 1, "umm": 1}
    assert result["filler_percentage"] == 15.0
    assert len(counts) == 3

def test_no_fillers():
    result = analyze_fillers(
        "Binary search repeatedly halves the search space."
    )

    assert result["counts"] == []
    assert result["filler_percentage"] == 0.0
    assert result["suggested_pauses"] == []

def test_repeated_fillers_and_case():
    result = analyze_fillers("Um, um, UMM, uh!")
    counts = {item["word"]: item["count"] for item in result["counts"]}

    assert counts == {"uh": 1, "um": 2, "umm": 1}
    assert result["filler_percentage"] == 100.0

def test_empty_transcript():
    result = analyze_fillers("   ")

    assert result["counts"] == []
    assert result["filler_percentage"] == 0.0

def test_multiword_filler():
    result = analyze_fillers("You know, binary search is fast.")
    counts = {item["word"]: item["count"] for item in result["counts"]}

    assert counts == {"you know": 1}

if __name__ == "__main__":
    test_sample_transcript()
    test_no_fillers()
    test_repeated_fillers_and_case()
    test_empty_transcript()
    test_multiword_filler()
    print("All filler analysis tests passed!")
