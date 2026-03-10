MEGA_STAT_MULT = {
    "small_mega": 1.20,
    "medium_mega": 1.40,
    "big_mega": 1.60,
}

COMBOS = [
    ("small_mega", False),
    ("medium_mega", False),
    ("big_mega", False),
    (None, True),
    ("small_mega", True),
    ("medium_mega", True),
    ("big_mega", True),
]


def calc_score_changes(base_stats, base_energy_cost, w_energy_change=0.006):
    table = {}
    for mega, use_anklet in COMBOS:
        stat_m = 1.0
        if mega:
            stat_m *= MEGA_STAT_MULT[mega]
        if use_anklet:
            stat_m *= 1.50

        extra_stats = base_stats * (stat_m - 1.0)

        extra_energy = 0.0
        if use_anklet:
            extra_energy = base_energy_cost * 0.20

        score_change = extra_stats * 0.01 - extra_energy * w_energy_change

        label = "+".join(filter(None, [mega, "anklet" if use_anklet else None]))
        table[label] = {
            "extra_stats": round(extra_stats, 1),
            "extra_energy": round(extra_energy, 1),
            "score_change": round(score_change, 4),
        }
    return table
