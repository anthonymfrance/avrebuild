from pathlib import Path
from collections import defaultdict

from participant_setup import derive_rng
from stimulus_split import split_pool
import config
import screens
import session_io


def test_block_continuation_does_not_expose_soa():
    source = Path(__file__).parents[1].joinpath('experiment.py').read_text()
    block_intro = source.split('if not continuation(', 1)[1].split('):', 1)[0]
    assert 'SOA' not in block_intro


def test_block_intro_names_the_target_group_not_a_single_picture():
    animals = screens.block_intro_message(0, 2, 'animate')
    objects = screens.block_intro_message(1, 2, 'inanimate')
    assert animals.startswith('Block 1 of 2: ANIMALS')
    assert objects.startswith('Block 2 of 2: OBJECTS')
    assert 'when you see any animal' in animals
    assert 'when you see any object' in objects
    assert 'when you see one' not in animals + objects
    assert set(screens.BLOCK_TARGET_PHRASE) == set(config.BLOCK_LABELS)
    assert screens.BLOCK_TARGET_PHRASE['animate'] == 'any animal'
    assert screens.BLOCK_TARGET_PHRASE['inanimate'] == 'any object'


def test_block_wording_is_not_a_config_snapshot_value():
    """A config constant would refuse every existing participant plan."""
    assert 'BLOCK_TARGET_PHRASE' not in session_io.config_snapshot()


def test_center_mark_is_presentation_only_in_the_config_snapshot():
    """Switching the mark shape must not refuse a plan made with another one.

    Only the two constants added for the option are left out: the mark values
    that predate it stay study parameters, so no existing plan's stored snapshot
    changed when it was added.
    """
    snapshot = session_io.config_snapshot()
    assert session_io.PRESENTATION_ONLY == {'FIXATION_SHAPE', 'FIXATION_BORDER_WIDTH'}
    assert not session_io.PRESENTATION_ONLY & set(snapshot)
    assert {'FIXATION_COLOR', 'FIXATION_HIT_COLOR', 'FIXATION_FLASH_DUR'} <= set(snapshot)


def test_every_mark_option_has_participant_wording():
    assert set(screens.MARK_NAMES) == {'cross', 'circle', 'border'}


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
