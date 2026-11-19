"""Dice + to-wound chart primitives."""
from __future__ import annotations

import w40k_force_balancer as sim


def test_to_wound_threshold_covers_all_tiers():
    # S >= 2*T  => 2+
    assert sim.to_wound_threshold(10, 4) == 2
    # S > T    => 3+
    assert sim.to_wound_threshold(5, 4) == 3
    # S == T   => 4+
    assert sim.to_wound_threshold(4, 4) == 4
    # S < T    => 5+
    assert sim.to_wound_threshold(3, 4) == 5
    # S*2 <= T => 6+
    assert sim.to_wound_threshold(2, 10) == 6


def test_clamp():
    assert sim.clamp(5, 0, 10) == 5
    assert sim.clamp(-5, 0, 10) == 0
    assert sim.clamp(15, 0, 10) == 10
