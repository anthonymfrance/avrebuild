from pathlib import Path


def test_block_continuation_does_not_expose_soa():
    source = Path(__file__).parents[1].joinpath('experiment.py').read_text()
    block_intro = source.split('if not continuation(', 1)[1].split('):', 1)[0]
    assert 'SOA' not in block_intro
