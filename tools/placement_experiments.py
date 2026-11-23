"""Alternative per-trial placers, compared by tools/scheduler_bench.py --placer NAME.

Every placer ends in timeline_key._schedule_layout, which spreads slack and runs
the full _conflict check, so all of them enforce exactly the production rules;
they differ only in how they choose the event order.
"""

import timeline_key as tk
from timeline_key import PlacementFailure

BUDGET = tk.MAX_PLACEMENT_ATTEMPTS * tk.MAX_TIMELINE_ATTEMPTS   # 750 orders, today's worst case per trial
REPAIR_EVALS = 400


def _fail(events, why):
    raise PlacementFailure(f'{len(events)} visuals: {why}')


def proof_of_infeasibility(events):
    """Return a reason when no order can fit; the bounds hold for every order."""
    from scheduler_bench import trial_load
    load = trial_load(events)
    if load['load'] > 1 + 1e-9:
        return f"{load['binding']} lower bound {load['lb_' + load['binding']]:.2f}s > {tk.TRIAL_CONTENT_DUR}s"
    return ''


def random_orders(events, trial_start, stats, budget):
    """Today's sampler: fresh random orders until one fits."""
    rng = stats['rng']
    for _ in range(budget):
        stats['placement_attempts'] += 1
        result = tk._schedule_layout(tk._random_order(events, rng), trial_start, rng)
        if result is not None:
            return result
    return None


def repair(events, trial_start, stats, budget, evals=REPAIR_EVALS):
    """Random order, then move single events while the packing does not get longer."""
    rng = stats['rng']
    n = len(events)
    for _ in range(budget):
        stats['placement_attempts'] += 1
        layout = tk._random_order(events, rng)
        excess = tk._layout_excess(layout, trial_start)
        for _ in range(evals):
            if excess <= 1e-9:
                break
            candidate = list(layout)
            candidate.insert(rng.randrange(n), candidate.pop(rng.randrange(n)))
            value = tk._layout_excess(candidate, trial_start)
            stats['repair_evals'] = stats.get('repair_evals', 0) + 1
            if value <= excess:
                layout, excess = candidate, value
        if excess <= 1e-9:
            result = tk._schedule_layout(layout, trial_start, rng)
            if result is not None:
                return result
    return None


def critical_first(events, trial_start, stats, budget, tolerance=0.3):
    """Randomized list scheduling: pick among events that can start earliest,
    favouring the corner with the most remaining hold time."""
    rng = stats['rng']
    hold = lambda e: tk.TARGET_CORNER_HOLD if e['role'] in tk.TARGET_ROLES else tk.VISUAL_DURATION
    for _ in range(budget):
        stats['placement_attempts'] += 1
        remaining = list(events)
        rng.shuffle(remaining)
        layout, offsets = [], []
        load = {}
        for e in remaining:
            load[e['corner']] = load.get(e['corner'], 0) + hold(e)
        while remaining:
            est = [max((o + tk._pair_separation(p, e) for p, o in zip(layout, offsets)), default=0.0)
                   for e in remaining]
            low = min(est)
            pool = [i for i, t in enumerate(est) if t <= low + tolerance]
            weights = [load[remaining[i]['corner']] for i in pool]
            i = rng.choices(pool, weights)[0]
            e = remaining.pop(i)
            layout.append(e)
            offsets.append(est[i])
            load[e['corner']] -= hold(e)
        result = tk._schedule_layout(layout, trial_start, rng)
        if result is not None:
            return result
    return None


def _placer(search, fail_fast, budget):
    def place(events, trial_start, stats, **_):
        if fail_fast:
            why = proof_of_infeasibility(events)
            if why:
                _fail(events, f'provably infeasible: {why}')
        result = search(events, trial_start, stats, budget)
        if result is None:
            _fail(events, f'{search.__name__} found no order in {budget} tries')
        return result
    return place


def hybrid(events, trial_start, stats, budget):
    """Today's sampler for its usual 250 orders, then repair for the rest."""
    first = min(budget, tk.MAX_PLACEMENT_ATTEMPTS)
    return random_orders(events, trial_start, stats, first) or \
        repair(events, trial_start, stats, max(1, (budget - first) // 10))


def hybrid_critical(events, trial_start, stats, budget):
    """Today's sampler for its usual 250 orders, then critical_first for the rest."""
    first = min(budget, tk.MAX_PLACEMENT_ATTEMPTS)
    return random_orders(events, trial_start, stats, first) or \
        critical_first(events, trial_start, stats, budget - first)


PLACERS = {
    # Same sampler, but a failing trial retries alone instead of restarting the timeline.
    'trial_local': (random_orders, False),
    'trial_local_failfast': (random_orders, True),
    'repair': (repair, True),
    'critical_first': (critical_first, True),
    'hybrid': (hybrid, True),
    'hybrid_critical': (hybrid_critical, True),
}


def install(name):
    search, fail_fast = PLACERS[name]
    tk._construct_trial_schedule = _placer(search, fail_fast, BUDGET)
    tk.MAX_TIMELINE_ATTEMPTS = 1
