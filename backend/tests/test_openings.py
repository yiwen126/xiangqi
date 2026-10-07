"""Opening book tests.

The book previously reported 「你已经离开了…常见理论」 on every move from ply 3
onward, which is nagging rather than teaching. Leaving theory is a one-time
event and must be announced exactly once.
"""
from app.analysis.openings import find_opening, is_in_book


def test_names_a_known_opening():
    info = find_opening(["h2e2"])
    assert info["name"] == "中炮局"
    assert info["in_book"] is True
    assert info["left_book_now"] is False


def test_follows_a_deeper_mainline():
    info = find_opening(["h2e2", "h9g7", "h0g2", "i9h9"])
    assert info["name"] == "中炮直车对屏风马"
    assert info["in_book"] is True


def test_left_book_now_fires_exactly_once():
    """The whole point: announce the departure on the ply it happens, then be
    quiet about it for the rest of the game."""
    in_book = ["h2e2", "h9g7"]
    assert find_opening(in_book)["in_book"] is True

    diverged = in_book + ["a0a1"]           # not a book continuation
    info = find_opening(diverged)
    assert info["in_book"] is False
    assert info["left_book_now"] is True

    # Every later move still knows the opening's name but no longer nags.
    for extra in (["b0c2"], ["b0c2", "b9c7"], ["b0c2", "b9c7", "c3c4"]):
        later = find_opening(diverged + extra)
        assert later["left_book_now"] is False, f"nagged again after {extra}"
        assert later["in_book"] is False


def test_running_past_the_end_of_a_line_counts_as_leaving_book():
    # 中炮对单提马 is only two plies deep.
    assert is_in_book(["h2e2", "b9a7"]) is True
    info = find_opening(["h2e2", "b9a7", "h0g2"])
    assert info["in_book"] is False
    assert info["left_book_now"] is True


def test_unknown_first_move_has_no_opening():
    info = find_opening(["a0a1"])
    assert info["name"] is None
    assert info["in_book"] is False
    assert info["left_book_now"] is False


def test_empty_history_is_trivially_in_book():
    assert is_in_book([]) is True


def test_pawn_openings_are_not_swapped():
    """c3c4 is 兵七进一 (挺七兵) and g3g4 is 兵三进一 (挺三兵); the book used to
    label them the other way round."""
    assert "七兵" in find_opening(["c3c4"])["note"]
    assert "三兵" in find_opening(["g3g4"])["note"]


def test_palace_crossing_cannons_are_distinguished():
    """炮二平六 crosses the palace (过宫炮); 炮二平四 only reaches the advisor
    corner (士角炮). These were both filed under 过宫炮 before."""
    assert find_opening(["h2d2"])["name"] == "过宫炮"
    assert find_opening(["h2f2"])["name"] == "士角炮"
    assert find_opening(["b2f2"])["name"] == "过宫炮"
    assert find_opening(["b2d2"])["name"] == "士角炮"
