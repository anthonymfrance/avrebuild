from types import SimpleNamespace

import pytest

import screens


class Stim:
    def __init__(self, window, **kwargs):
        self.text = kwargs.get('text', '')
        self.size = (800, 600)
        self.draw_count = 0
        window.stims.append(self)

    def draw(self):
        self.draw_count += 1


@pytest.mark.parametrize('key, expected', [('space', True), ('escape', False)])
def test_instruction_screen_draws_text_and_graphic(key, expected):
    window = SimpleNamespace(size=(1920, 1080), stims=[], flip=lambda: None)
    kb = SimpleNamespace(getKeys=lambda **kwargs: [SimpleNamespace(name=key)])
    visual = SimpleNamespace(TextStim=Stim, ImageStim=Stim)
    assert screens._numpad_image_path().is_file()
    assert screens.instructions(window, kb, visual) is expected
    assert len(window.stims) == 3
    assert window.stims[0].text == screens.INSTRUCTIONS_TOP
    assert window.stims[2].text == screens.INSTRUCTIONS_BOTTOM
    assert all(stim.draw_count == 1 for stim in window.stims)
    assert window.stims[1].size[0] <= window.size[0] * 0.45
    assert window.stims[1].size[1] <= window.size[1] * 0.28
