"""Conversational custom rule & bonus engine for The Edge (Phase 6).

Lets a user (via the co-pilot) create unlimited custom bonuses/penalties that
apply to runners matching a filter, scoped to one race, several races, or the
whole meeting. Pure Python (no Streamlit) so it is unit-testable; the app holds
a single RuleManager in session state. Mock data only (see CLAUDE.md).
"""

import uuid
from dataclasses import dataclass, field

SCOPE_THIS = "this_race"
SCOPE_SELECTED = "selected_races"
SCOPE_MEETING = "whole_meeting"

FILTER_TYPES = ("lane_range", "barrier_range", "settle_zone",
                "weight_threshold", "prep_stage", "tactical_tag")


def match(filter_type, filter_params, runner):
    """True if a runner matches a filter. Shared by RuleManager and the co-pilot preview.

    runner may carry: lane, barrier, settle_zone, weight, prep_stage, prep_run_num,
    tactical_tag.
    """
    ft, p = filter_type, filter_params
    if ft == "lane_range":
        return p.get("min_lane", 0) <= runner.get("lane", -1) <= p.get("max_lane", 99)
    if ft == "barrier_range":
        return p.get("min_barrier", 0) <= runner.get("barrier", -1) <= p.get("max_barrier", 99)
    if ft == "settle_zone":
        zones = p.get("zones") or ([p["zone"]] if "zone" in p else [])
        rz = (runner.get("settle_zone", "") or "").lower()
        return any(z.lower() in rz for z in zones)
    if ft == "weight_threshold":
        w = runner.get("weight")
        if w is None:
            return False
        if "min_weight" in p and w < p["min_weight"]:
            return False
        if "max_weight" in p and w > p["max_weight"]:
            return False
        return ("min_weight" in p) or ("max_weight" in p)
    if ft == "prep_stage":
        if "prep_run_num" in p and runner.get("prep_run_num") == p["prep_run_num"]:
            return True
        stage = str(p.get("stage", "")).lower()
        return bool(stage) and stage in (runner.get("prep_stage", "") or "").lower()
    if ft == "tactical_tag":
        return p.get("tag", "").lower() in (runner.get("tactical_tag", "") or "").lower()
    return False


@dataclass
class CustomRule:
    description: str
    points: float
    filter_type: str
    filter_params: dict = field(default_factory=dict)
    scope: str = SCOPE_THIS
    target_race_ids: list = field(default_factory=list)
    rule_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def scope_label(self):
        if self.scope == SCOPE_MEETING:
            return "All Races"
        if self.scope == SCOPE_SELECTED:
            return "Races " + ", ".join("R{}".format(r) for r in self.target_race_ids)
        return "R{} Only".format(self.target_race_ids[0]) if self.target_race_ids else "This Race"


class RuleManager:
    """Holds and evaluates custom rules."""

    def __init__(self):
        self.rules = []

    # -- management ----------------------------------------------------------
    def add_rule(self, rule):
        self.rules.append(rule)
        return rule.rule_id

    def remove_rule(self, rule_id):
        before = len(self.rules)
        self.rules = [r for r in self.rules if r.rule_id != rule_id]
        return len(self.rules) < before

    def clear_all_rules(self, race_id=None):
        if race_id is None:
            n = len(self.rules)
            self.rules = []
            return n
        keep = [r for r in self.rules if not self._applies(r, race_id)]
        removed = len(self.rules) - len(keep)
        self.rules = keep
        return removed

    def _applies(self, rule, race_id):
        if rule.scope == SCOPE_MEETING:
            return True
        return race_id in (rule.target_race_ids or [])

    def get_active_rules(self, race_id):
        return [r for r in self.rules if self._applies(r, race_id)]

    def all_rules(self):
        return list(self.rules)

    # -- evaluation ----------------------------------------------------------
    def _match(self, rule, runner):
        return match(rule.filter_type, rule.filter_params, runner)

    def evaluate_runner_rules(self, runner, race_id):
        """Return (total_points_delta, [badge dicts]) for one runner in a race."""
        total = 0.0
        badges = []
        for r in self.get_active_rules(race_id):
            if self._match(r, runner):
                total += r.points
                badges.append({"description": r.description, "points": r.points,
                               "type": "bonus" if r.points >= 0 else "penalty",
                               "rule_id": r.rule_id})
        return round(total, 2), badges


if __name__ == "__main__":
    mgr = RuleManager()
    mgr.add_rule(CustomRule("Lanes 4-7 Bias (+2.5)", 2.5, "lane_range",
                            {"min_lane": 4, "max_lane": 7}, SCOPE_MEETING))
    mgr.add_rule(CustomRule("3WNC Tax (-2.0)", -2.0, "tactical_tag",
                            {"tag": "3WNC"}, SCOPE_THIS, [1]))
    r1 = {"lane": 4, "barrier": 10, "tactical_tag": "3WNC", "weight": 55}
    print(mgr.evaluate_runner_rules(r1, 1))
    print("meeting rules for race 2:", len(mgr.get_active_rules(2)))
