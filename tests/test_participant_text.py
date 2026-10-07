from pathlib import Path
from collections import defaultdict

from participant_setup import derive_rng
from stimulus_split import split_pool
import config


def test_block_continuation_does_not_expose_soa():
    source = Path(__file__).parents[1].joinpath('experiment.py').read_text()
    block_intro = source.split('if not continuation(', 1)[1].split('):', 1)[0]
    assert 'SOA' not in block_intro


def test_first_timeline_soa_is_independent_of_first_sampled_item():
    by_item = defaultdict(list)
    for seed in range(20_000):
        split_rng = derive_rng(seed, 'split_slotting')
        assignment = split_pool(split_rng)
        first_item = assignment['animate']['PT'][0]
        first_soa = derive_rng(seed, 'timeline').uniform(
            config.PT_SOA_MIN, config.PT_SOA_MAX,
        )
        by_item[first_item].append(first_soa)
    assert set(by_item) == set(__import__('stimulus_split').ANIMATE)
    means = [sum(values) / len(values) for values in by_item.values()]
    assert max(abs(mean - 1.0) for mean in means) < 0.05
