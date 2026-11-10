"""Unit tests for the rules that decide what we bet and how much.

These are the pieces that can quietly break and cost money: the play rules,
the fade rule, the going read, the class move and the staking. Run with pytest.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import plays
import staking_engine


BASE = dict(p=0.30, p_market=0.28, price=4.0, fair=3.5, map_zone="Handy", map_tag=None,
            form_rank=1, form_conf="High", going="suited", tags=[], fade=False)


def play(**kw):
    r = dict(BASE); r.update(kw)
    return plays.play_check(r)


def test_a_clean_runner_is_a_play():
    ok, reasons, misses = play()
    assert ok and not misses and len(reasons) == 8


def test_chance_under_the_bar_is_not_a_play():
    ok, _, misses = play(p=0.20)
    assert not ok and any("chance under" in m for m in misses)


def test_price_shorter_than_our_own_is_not_a_play():
    ok, _, misses = play(price=3.0, fair=3.5)
    assert not ok and "price shorter than ours" in misses


def test_odds_on_runners_are_left_alone():
    ok, _, misses = play(price=1.50, fair=1.40)
    assert not ok and any("price under" in m for m in misses)


def test_a_bad_map_stops_it():
    assert not play(map_zone="Backmarker")[0]
    assert not play(map_tag="3WNC")[0]


def test_thin_or_lower_rated_form_stops_it():
    assert not play(form_rank=4)[0]
    assert not play(form_conf="Low")[0]


def test_poor_on_the_going_stops_it():
    assert not play(going="poor")[0]


def test_fade_angles_stop_it():
    assert not play(tags=["down_trip"])[0]
    assert not play(tags=["excuse_last"])[0]


def test_misses_are_named_one_by_one():
    ok, _, misses = play(p=0.10, going="poor")
    assert not ok and len(misses) == 2


# ------------------------------------------------------------------ fades
def test_fade_only_when_proven_and_in_the_price_band():
    assert plays.is_fade(0.05, 0.10, 8.0, True)
    assert not plays.is_fade(0.05, 0.10, 8.0, False)       # not proven out of sample
    assert not plays.is_fade(0.05, 0.10, 25.0, True)       # outside the band
    assert not plays.is_fade(0.09, 0.10, 8.0, True)        # not far enough below


# ------------------------------------------------------------------ going
def test_going_verdict_reads_form_kings_records():
    assert plays.going_verdict({"heavy": "4:2-1-0"}, "Heavy") == "suited"
    assert plays.going_verdict({"heavy": "4:0-0-0"}, "Heavy") == "poor"
    assert plays.going_verdict({}, "Heavy") == "unraced"
    assert plays.going_verdict({"good": "3:0-1-0"}, "Good") == "fair"
    assert plays.going_verdict({"Heavy": "4:2-1-0"}, "Heavy") == "suited"   # casing is forgiven


def test_going_bands_map_the_track_words():
    assert plays.going_band("Good 4") == "Good"
    assert plays.going_band("Dead 5") == "Good"
    assert plays.going_band("Slow 6") == "Soft"
    assert plays.going_band("Heavy 10") == "Heavy"
    assert plays.going_band("Synthetic") == "Synthetic"
    assert plays.going_band("") is None


# ------------------------------------------------------------------ class and tags
def test_class_move_needs_a_real_gap():
    assert plays.class_move(70, 60) == ("up", 10.0)
    assert plays.class_move(60, 70) == ("down", -10.0)
    assert plays.class_move(70, 69.5) == (None, 0.5)
    assert plays.class_move(None, 70) == (None, None)


def test_last_start_tags():
    last = [{"pos": 1, "margin": 2.0, "dist": 1200, "comment": ""}]
    assert "won_last" in plays.last_start_tags(last, 1600)
    assert "up_trip" in plays.last_start_tags(last, 1600)
    assert "down_trip" in plays.last_start_tags(last, 1000)
    beaten = [{"pos": 3, "margin": -0.4, "dist": 1200, "comment": "held up for a run"}]
    tags = plays.last_start_tags(beaten, 1200)
    assert "close_last" in tags and "excuse_last" in tags and "won_last" not in tags


# ------------------------------------------------------------------ staking
def stake(odds):
    return staking_engine.calculate_stake(odds)["dollars"]


def test_stake_targets_a_hundred_dollar_win():
    assert round(stake(5.0), 2) == 25.00
    assert round(stake(3.0), 2) == 50.00


def test_stake_is_capped():
    assert stake(1.20) == staking_engine.MAX_STAKE


def test_no_stake_on_a_missing_price():
    assert stake(0) == 0


def test_minimum_acceptable_odds_and_void():
    assert staking_engine.calculate_mao(4.0, 0.15) == 4.60
    assert staking_engine.is_void(4.50, 4.0, 0.15)
    assert not staking_engine.is_void(4.80, 4.0, 0.15)
