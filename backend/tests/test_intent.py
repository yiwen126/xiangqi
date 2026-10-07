"""Move-intent detection: attack facts, defense facts, and `detect`."""
from app.analysis.intent import detect, new_attacks
from app.analysis.tactics import capture_is_legal
from app.xiangqi.board import Board, Move
from app.xiangqi.movegen import is_in_check


def attack_tags(fen: str, uci: str):
    before = Board.from_fen(fen)
    move = Move.from_uci(uci)
    after = before.clone()
    after.apply_move(move)
    return new_attacks(before, after, move)


def test_new_contact_on_undefended_horse_is_a_win_attack():
    # Red general on d0 rather than e0: with both generals on the e-file the
    # position has them facing, and no capture counts as legal there.
    tags = attack_tags("4k4/9/9/9/R8/3n5/9/9/9/3K5 w - - 0 1", "a5d5")
    assert len(tags) == 1
    tag = tags[0]
    assert tag.kind == "attack"
    assert tag.piece == "R"
    assert tag.piece_sq == (4, 3)
    assert tag.target_sqs == [(5, 3)]
    assert tag.detail == {"tier": "win", "see": 4.0, "defended": False}


def test_attack_on_a_defended_chariot_is_win_tier_with_net_gain():
    # The horse lands on d3; its attack on the chariot on e5 is worth 5 pawns
    # after the pawn recaptures.
    tags = attack_tags("4k4/9/9/4p4/4r4/9/9/9/2N6/3K5 w - - 0 1", "c1d3")
    assert len(tags) == 1
    assert tags[0].detail == {"tier": "win", "see": 5.0, "defended": True}


def test_attack_on_a_defended_horse_is_an_even_exchange_offer():
    tags = attack_tags("4k4/9/9/4p4/4n4/9/9/9/2N6/3K5 w - - 0 1", "c1d3")
    assert len(tags) == 1
    assert tags[0].detail == {"tier": "even", "see": 0.0, "defended": True}


def test_preexisting_contact_is_not_reported():
    # The chariot already attacked the horse on d4 before the general moved.
    assert attack_tags("4k4/9/9/9/9/R2n5/9/9/9/3K5 w - - 0 1", "d0d1") == []


def test_capturing_move_never_names_the_captured_piece():
    # a4d4 captures the pawn on d4 and only then attacks the horse on g4.
    tags = attack_tags("4k4/9/9/9/9/R2p2n2/9/9/9/3K5 w - - 0 1", "a4d4")
    assert [t.target_sqs[0] for t in tags] == [(5, 6)]


def test_standoff_with_a_more_valuable_attacker_is_not_reported():
    # A chariot poking a defended horse reaches SEE 0 by declining the trade;
    # that is not pressure and must not be worded as an exchange offer.
    assert attack_tags("4k4/9/9/4p4/4n4/9/9/9/R8/3K5 w - - 0 1", "a1e1") == []


def test_pawn_targets_are_below_the_pressure_threshold():
    assert attack_tags("4k4/9/9/9/4p4/9/9/9/R8/3K5 w - - 0 1", "a1e1") == []


def test_pinned_attacker_does_not_create_a_threat():
    # Black chariot on e5 is pinned against its general by the red chariot on
    # e1; its "attack" on the red horse on g5 is not a real threat.
    before = Board.from_fen("4k4/9/9/9/4r1N2/p8/9/9/4R4/3K5 b - - 0 1")
    assert capture_is_legal(before, (4, 4), (4, 6)) is False
    assert attack_tags("4k4/9/9/9/4r1N2/p8/9/9/4R4/3K5 b - - 0 1", "a4a3") == []


def test_the_general_is_never_an_attack_target():
    before = Board.from_fen("4k4/9/9/9/9/9/9/9/9/3KR4 w - - 0 1")
    move = Move.from_uci("e0e8")
    after = before.clone()
    after.apply_move(move)
    assert is_in_check(after, "b") is True  # 车五进八: that is 将军, not an attack row
    assert new_attacks(before, after, move) == []


def test_defending_a_hanging_piece_reports_the_threat():
    tags = detect(Board.from_fen("3k5/9/9/9/9/2N6/9/9/r8/R3K4 w - - 0 1"), Move.from_uci("c4b2"))
    assert len(tags) == 1
    tag = tags[0]
    assert tag.kind == "defend"
    assert tag.piece == "R"
    assert tag.piece_sq == (9, 0)
    assert tag.target_sqs == [(8, 0)]
    assert tag.detail == {"escape": False, "see_before": 9.0, "threat_uci": "a1a0"}


def test_defend_by_capturing_the_threatener_still_names_the_threat():
    tags = detect(Board.from_fen("3k5/9/9/9/9/9/1N7/9/r8/R3K4 w - - 0 1"), Move.from_uci("b3a1"))
    assert len(tags) == 1
    assert tags[0].kind == "defend"
    assert tags[0].piece_sq == (9, 0)
    assert tags[0].detail["threat_uci"] == "a1a0"


def test_escape_from_an_attack_uses_the_origin_square():
    tags = detect(Board.from_fen("4k4/9/9/9/9/9/9/3K5/r8/R8 w - - 0 1"), Move.from_uci("a0i0"))
    assert len(tags) == 1
    tag = tags[0]
    assert tag.kind == "defend"
    assert tag.detail["escape"] is True
    assert tag.piece_sq == (9, 0)  # the square it left, not i0
    assert tag.detail["threat_uci"] == "a1a0"


def test_piece_that_stays_hanging_is_not_reported():
    # The chariot on a0 stays hanging; moving the general does not defend it.
    assert detect(Board.from_fen("3k5/9/9/9/9/9/9/9/r8/R3K4 w - - 0 1"), Move.from_uci("e0f0")) == []


def test_attacks_are_ranked_and_capped():
    tags = detect(Board.from_fen("4k4/9/9/3n1c3/6r2/9/9/5N3/9/3K5 w - - 0 1"), Move.from_uci("f2e4"))
    # Chariot 9.0 and cannon 4.5 first; the horse 4.0 is dropped by the cap.
    assert [t.target_sqs[0] for t in tags] == [(4, 6), (3, 5)]
    assert all(t.kind == "attack" and t.detail["tier"] == "win" for t in tags)


def test_detect_is_deterministic():
    fen, uci = "4k4/9/9/3n1c3/6r2/9/9/5N3/9/3K5 w - - 0 1", "f2e4"
    assert detect(Board.from_fen(fen), Move.from_uci(uci)) == detect(Board.from_fen(fen), Move.from_uci(uci))


def test_a_checking_move_does_not_claim_a_hanging_piece_is_saved():
    # Red's rook on a0 is hanging to the black rook on a1. Moving the other
    # rook to h9 gives check; SEE cannot judge black's captures while black
    # is in check, so no "saved" claim may be made.
    assert detect(Board.from_fen("4k4/9/9/9/7R1/9/9/9/r8/R2K5 w - - 0 1"), Move.from_uci("h5h9")) == []


def test_detect_does_not_mutate_the_callers_board():
    board = Board.from_fen("4k4/9/9/3n1c3/6r2/9/9/5N3/9/3K5 w - - 0 1")
    fen_before = board.to_fen()
    detect(board, Move.from_uci("f2e4"))
    assert board.to_fen() == fen_before


def test_discovered_attack_is_attributed_to_the_freed_piece():
    # Moving the chariot off the a-file leaves the cannon on a2 with exactly
    # one screen (the pawn on a6), so it now attacks the black chariot on a8.
    tags = detect(Board.from_fen("4k4/r8/9/p8/9/R8/9/C8/9/3K5 w - - 0 1"), Move.from_uci("a4i4"))
    assert len(tags) == 1
    assert tags[0].piece == "C"
    assert tags[0].piece_sq == (7, 0)
    assert tags[0].target_sqs == [(1, 0)]
