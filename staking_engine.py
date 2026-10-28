"""Staking engine for The Edge - Target-Profit model.

Replaces the previous Quarter-Kelly logic with a strict "To-Win $100" target
profit model, plus Minimum Acceptable Odds (MAO) gating. Mock data only
(see CLAUDE.md). All sizing is in AUD dollars.

    Stake $ = TARGET_PROFIT / (market_odds - 1.0)

so that a winning bet returns exactly TARGET_PROFIT in profit at the taken price.
"""

# Target profit per winning bet, in dollars.
TARGET_PROFIT = 100.0

# MAO gating.
DEFAULT_MIN_EDGE = 0.15

# Staking modes.
STAKE_CONSUMER = "Consumer / To-Win-$100"
STAKE_SYNDICATE = "Syndicate / Quarter-Kelly"
KELLY_FRACTION = 0.25
DEFAULT_BANKROLL = 2000.0


def target_profit_stake(market_odds, target=TARGET_PROFIT):
    """Dollar stake required to win `target` at the given decimal odds."""
    b = market_odds - 1.0
    if b <= 0:
        return 0.0
    return round(target / b, 2)


def quarter_kelly_stake(model_prob, odds, bankroll=DEFAULT_BANKROLL):
    """Fractional (quarter) Kelly dollar stake for bankroll compounding."""
    b = odds - 1.0
    if b <= 0 or model_prob is None:
        return 0.0
    f = (b * model_prob - (1.0 - model_prob)) / b
    return round(max(0.0, f * KELLY_FRACTION) * bankroll, 2)


def calculate_stake(market_odds, mode=STAKE_CONSUMER, model_prob=None,
                    bankroll=DEFAULT_BANKROLL, target=TARGET_PROFIT):
    """Return the recommended stake for a bet as a dict.

    Consumer mode sizes to win a fixed target; Syndicate mode uses Quarter-Kelly
    on the bankroll. Keys: dollars, mode, to_win, bet.
    """
    if mode == STAKE_SYNDICATE and model_prob is not None:
        dollars = quarter_kelly_stake(model_prob, market_odds, bankroll)
        return {"dollars": dollars, "mode": STAKE_SYNDICATE, "bet": dollars > 0,
                "to_win": round(dollars * (market_odds - 1.0), 2)}
    dollars = target_profit_stake(market_odds, target)
    return {"dollars": dollars, "mode": STAKE_CONSUMER, "to_win": target, "bet": dollars > 0}


def calculate_mao(fair_odds, min_edge=DEFAULT_MIN_EDGE):
    """Minimum Acceptable Odds = fair_odds * (1 + min_edge).

    A market price at or above MAO is bettable; below it the edge is too thin
    and the bet should be flagged VOID/NO BET.
    """
    return round(fair_odds * (1.0 + min_edge), 2)


def is_void(market_odds, fair_odds, min_edge=DEFAULT_MIN_EDGE):
    """True if the market price is below MAO (bet is VOID / NO BET)."""
    return market_odds < calculate_mao(fair_odds, min_edge)


if __name__ == "__main__":
    for fair, market in [(8.78, 14.98), (4.57, 5.57), (6.65, 8.18)]:
        stake = calculate_stake(market)
        mao = calculate_mao(fair)
        win_profit = stake["dollars"] * (market - 1.0)
        print("fair=${} market=${} -> stake ${:.2f} (wins ${:.2f})  MAO=${} void={}".format(
            fair, market, stake["dollars"], win_profit, mao, is_void(market, fair)))
