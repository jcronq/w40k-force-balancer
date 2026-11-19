"""Dice primitives + to-wound chart helpers."""
from __future__ import annotations

import random


def roll_d6(rng: random.Random) -> int:
    return rng.randint(1, 6)


def roll_2d6(rng: random.Random) -> int:
    return rng.randint(1, 6) + rng.randint(1, 6)


def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def to_wound_threshold(strength: int, toughness: int) -> int:
    if strength >= 2 * toughness:
        return 2
    if strength > toughness:
        return 3
    if strength == toughness:
        return 4
    if strength * 2 <= toughness:
        return 6
    return 5
