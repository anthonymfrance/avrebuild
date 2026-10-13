"""Launcher integration checks without opening windows or running real trials."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def executable(path, content):
    path.write_text(content, encoding='utf-8')
    path.chmod(0o755)


@pytest.mark.parametrize('mounted,plan_created', [(True, False), (False, False), (True, True)])
def test_launcher_uses_final_storage_roots_and_preserves_failure_log(tmp_path, mounted, plan_created):
    study = tmp_path / 'study'
    study.mkdir()
    # Real allocation modules and settings, but all participant data is isolated.
    for source in ROOT.glob('*.py'):
        shutil.copyfile(source, study / source.name)
    launcher = (ROOT / 'preflight.sh').read_text(encoding='utf-8')
    # Simulate discovery too: this test must not depend on system JACK packages.
    launcher = launcher.replace('/usr/lib/*/pipewire-0.3/jack/libjack.so', '/dev/null')
    launcher = launcher.replace(
        'gvfs_dir="/run/user/$(id -u)/gvfs"', f'gvfs_dir="{tmp_path / "gvfs"}"',
    )
    (study / 'preflight.sh').write_text(launcher, encoding='utf-8')
    (study / 'data' / 'participant_01').mkdir(parents=True)
    server = tmp_path / 'server'
    server_data = server / 'study_data'
    (server_data / 'participant_02').mkdir(parents=True)
    commands = tmp_path / 'bin'
    commands.mkdir()
    dialogs = tmp_path / 'dialogs.jsonl'
    capture = tmp_path / 'runner.json'
    executable(commands / 'zenity', f'''#!{sys.executable}
import json, sys
with open({str(dialogs)!r}, 'a') as output:
    output.write(json.dumps(sys.argv[1:]) + '\\n')
''')
    executable(commands / 'pactl', "#!/bin/sh\nprintf 'balance 0.00\\n'\n")
    executable(commands / 'xrandr', "#!/bin/sh\nprintf 'HDMI-1 connected primary\\n   1920x1080 120.00*+\\n'\n")
    (tmp_path / 'gvfs').mkdir()
    mount_glob = '../server' if mounted else '../missing'
    (study / 'preflight_config.sh').write_text(
        f'PREFLIGHT_SERVER_MOUNT_GLOB={mount_glob!r}\n'
        "PREFLIGHT_SERVER_DATA_PATH='study_data'\n", encoding='utf-8',
    )
    executable(commands / 'pw-jack', '#!/bin/sh\nexec "$@"\n')
    python = commands / 'python'
    executable(python, f'''#!{sys.executable}
import json, os, pathlib, sys
args = sys.argv[1:]
if args[0] == '-c' and ('importlib.util' in args[1] or 'psychtoolbox.audio' in args[1]):
    sys.exit(0)
if args[0].endswith('experiment.py'):
    pid = args[1]
    report = pathlib.Path(os.environ['AV_STUDY_PREFLIGHT_REPORT']).read_text()
    pathlib.Path({str(capture)!r}).write_text(json.dumps({{'pid': pid, 'report': report}}))
    if {plan_created!r}:
        pathlib.Path('data', pid).mkdir()
    print('simulated runner failure', file=sys.stderr)
    sys.exit(1)
os.execv({sys.executable!r}, [{sys.executable!r}] + args)
''')
    env = dict(os.environ)
    for name in ('AV_STUDY_SERVER_ROOT', 'AV_STUDY_SERVER_DATA_PATH', 'LD_PRELOAD'):
        env.pop(name, None)
    env.update(
        PATH=str(commands) + os.pathsep + env['PATH'],
        AV_STUDY_DIR=str(study), AV_STUDY_PYTHON=str(python), TMPDIR=str(tmp_path),
    )
    result = subprocess.run(
        ['bash', str(study / 'preflight.sh')], env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    recorded = json.loads(capture.read_text())
    pid = 'participant_03' if mounted else 'participant_02'
    assert recorded['pid'] == pid
    assert f'participant_id={pid}\n' in recorded['report']
    # The debug-screen choice is recorded so debug sessions stay identifiable
    # after the fact (the fake zenity accepts every dialog).
    assert 'debug_overlay=true\n' in recorded['report']
    if mounted:
        reported_root = next(line.split('=', 1)[1] for line in recorded['report'].splitlines()
                             if line.startswith('server_root='))
        assert Path(reported_root).resolve() == server
    messages = [json.loads(line) for line in dialogs.read_text().splitlines()]
    error = next(args for args in messages if '--error' in args)
    text = next(arg.removeprefix('--text=') for arg in error if arg.startswith('--text='))
    log = Path(text.split('Full log: ', 1)[1])
    assert log.is_file()
    assert 'simulated runner failure' in log.read_text()
    participant = study / 'data' / pid
    assert participant.exists() == plan_created
    if plan_created:
        assert log == participant / 'launch_error.log'
        assert not list(tmp_path.glob('av-experiment-*'))
    else:
        assert log.parent == tmp_path
    assert sorted(path.name for path in server_data.iterdir()) == ['participant_02']
