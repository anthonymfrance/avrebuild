"""Launcher integration checks without opening windows or running real trials."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

import config


ROOT = Path(__file__).resolve().parents[1]
CONSENT_URL = 'https://example.test/consent'
PARTICIPANT_LOG_URL = 'https://example.test/log'


def executable(path, content):
    path.write_text(content, encoding='utf-8')
    path.chmod(0o755)


def run_launcher(tmp_path, *, mounted=True, plan_created=False, debug=True, skip_gates=False,
                 digital=False, server_uri=None, gio_succeeds=True, initial_mode=None,
                 server_root=None, allow_digital=False):
    """Run preflight.sh in an isolated study directory with fake system commands.

    ``debug=False`` makes the fake zenity choose the participant run, and
    ``skip_gates=True`` makes it press the skip button whenever one is offered.
    ``digital=True`` makes the fake default sink an S/PDIF output. ``server_uri``
    configures the share to auto-mount; ``gio_succeeds`` says whether the fake
    ``gio`` claims the mount worked (it never actually creates a mount point).
    ``server_root`` gives the machine a configured absolute mount point (the
    Camp-Lab CIFS share) instead of a gvfs mount.
    """
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
    server = Path(server_root) if server_root is not None else tmp_path / 'server'
    server_data = server / 'study_data'
    (server_data / 'participant_02').mkdir(parents=True)
    commands = tmp_path / 'bin'
    commands.mkdir()
    dialogs = tmp_path / 'dialogs.jsonl'
    pactl_log = tmp_path / 'pactl.jsonl'
    browser_log = tmp_path / 'browser.jsonl'
    capture = tmp_path / 'runner.json'
    expected_volume = f'{config.SYSTEM_VOLUME_PERCENT}%'
    executable(commands / 'zenity', f'''#!{sys.executable}
import json, sys
args = sys.argv[1:]
with open({str(dialogs)!r}, 'a') as output:
    output.write(json.dumps(args) + chr(10))
if '--ok-label=Debug run' in args and not {debug!r}:
    sys.exit(1)
if {skip_gates!r} and '--extra-button=Skip (debug)' in args:
    print('Skip (debug)')
    sys.exit(1)
''')
    sink_name = 'alsa_output.test_sink'
    sink_desc = 'Digital Stereo (IEC958)' if digital else 'Test Headphones Analog Stereo'
    executable(commands / 'pactl', f'''#!{sys.executable}
import json, sys
args = sys.argv[1:]
with open({str(pactl_log)!r}, 'a') as output:
    output.write(json.dumps(args) + chr(10))
if args[:1] == ['get-default-sink']:
    print({sink_name!r})
elif args[:2] == ['list', 'sinks']:
    print('Sink #0')
    print('\tName: ' + {sink_name!r})
    print('\tDescription: ' + {sink_desc!r})
elif args[:1] == ['get-sink-volume']:
    print('Volume: front-left: 49152 /  {expected_volume} / -7.50 dB,   front-right: 49152 /  {expected_volume} / -7.50 dB')
    print('        balance 0.00')
else:
    print('balance 0.00')
''')
    xrandr_log = tmp_path / 'xrandr.jsonl'
    if initial_mode is None:
        executable(commands / 'xrandr', "#!/bin/sh\nprintf 'HDMI-1 connected primary\\n   1920x1080 120.00*+\\n'\n")
    else:
        # Stateful panel: reflects the mode it is asked to switch to, so the
        # launcher's switch and its restore-on-exit can both be observed.
        mode_file = tmp_path / 'xrandr_mode'
        mode_file.write_text(initial_mode, encoding='utf-8')
        executable(commands / 'xrandr', f'''#!{sys.executable}
import json, sys
args = sys.argv[1:]
with open({str(xrandr_log)!r}, 'a') as output:
    output.write(json.dumps(args) + chr(10))
current = open({str(mode_file)!r}).read().strip()
if '--output' in args:
    current = args[args.index('--mode') + 1]
    open({str(mode_file)!r}, 'w').write(current)
    sys.exit(0)
modes = [('1280x720', ['60.00']), ('1920x1080', ['120.00', '60.00']), ('2560x1440', ['240.00', '120.00'])]
print('HDMI-1 connected primary ' + current + '+0+0')
for mode, rates in modes:
    cells = [rate + ('*' if mode == current and index == 0 else '') for index, rate in enumerate(rates)]
    print('   ' + mode + '   ' + '  '.join(cells))
''')
    executable(commands / 'xdg-open', f'''#!{sys.executable}
import json, sys
with open({str(browser_log)!r}, 'a') as output:
    output.write(json.dumps(sys.argv[1:]) + chr(10))
''')
    (tmp_path / 'gvfs').mkdir()
    mount_glob = '../server' if mounted else '../missing'
    (study / 'preflight_config.sh').write_text(
        f'PREFLIGHT_SERVER_MOUNT_GLOB={mount_glob!r}\n'
        "PREFLIGHT_SERVER_DATA_PATH='study_data'\n"
        f'PREFLIGHT_CONSENT_URL={CONSENT_URL!r}\n'
        f'PREFLIGHT_PARTICIPANT_LOG_URL={PARTICIPANT_LOG_URL!r}\n'
        + (f'PREFLIGHT_SERVER_URI={server_uri!r}\n' if server_uri else '')
        + (f'PREFLIGHT_SERVER_ROOT={str(server)!r}\n' if server_root is not None else '')
        + ("PREFLIGHT_ALLOW_DIGITAL_SINK='1'\n" if allow_digital else ''),
        encoding='utf-8',
    )
    executable(commands / 'pw-jack', '#!/bin/sh\nexec "$@"\n')
    if server_uri:
        executable(commands / 'gio', f'#!/bin/sh\nexit {0 if gio_succeeds else 1}\n')
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
    # The launcher backgrounds xdg-open, so wait for the fake to finish writing.
    count = -1
    for _ in range(100):
        lines = browser_log.read_text().splitlines() if browser_log.is_file() else []
        if len(lines) == count:
            break
        count = len(lines)
        time.sleep(0.02)
    return SimpleNamespace(
        result=result,
        recorded=json.loads(capture.read_text()) if capture.is_file() else None,
        messages=[json.loads(line) for line in dialogs.read_text().splitlines()],
        browsers=[json.loads(line) for line in browser_log.read_text().splitlines()]
        if browser_log.is_file() else [],
        pactl=[json.loads(line) for line in pactl_log.read_text().splitlines()],
        xrandr=[json.loads(line) for line in xrandr_log.read_text().splitlines()]
        if xrandr_log.is_file() else [],
        study=study,
        server=server,
        server_data=server_data,
        tmp_path=tmp_path,
    )


@pytest.mark.parametrize('mounted,plan_created', [(True, False), (False, False), (True, True)])
def test_launcher_uses_final_storage_roots_and_preserves_failure_log(tmp_path, mounted, plan_created):
    run = run_launcher(tmp_path, mounted=mounted, plan_created=plan_created)
    assert run.result.returncode == 1, run.result.stdout + run.result.stderr
    recorded = run.recorded
    pid = 'participant_03' if mounted else 'participant_02'
    assert recorded['pid'] == pid
    assert f'participant_id={pid}\n' in recorded['report']
    # The debug-screen choice is recorded so debug sessions stay identifiable
    # after the fact (the fake zenity accepts every dialog).
    assert 'debug_overlay=true\n' in recorded['report']
    # Both browser steps open, in order, and the confirmations reach the report.
    assert run.browsers == [[CONSENT_URL], [PARTICIPANT_LOG_URL]]
    assert f'browser_urls_opened={CONSENT_URL} {PARTICIPANT_LOG_URL}\n' in recorded['report']
    assert 'consent_form=completed\n' in recorded['report']
    assert 'participant_log=confirmed\n' in recorded['report']
    assert 'browser_close=confirmed\n' in recorded['report']
    if mounted:
        reported_root = next(line.split('=', 1)[1] for line in recorded['report'].splitlines()
                             if line.startswith('server_root='))
        assert Path(reported_root).resolve() == run.server
    # Volume is pinned on the sink the route check validated, not on whatever
    # happens to be the default a moment later.
    assert ['set-sink-volume', 'alsa_output.test_sink', f'{config.SYSTEM_VOLUME_PERCENT}%'] in run.pactl
    assert f'system_volume_percent={config.SYSTEM_VOLUME_PERCENT}\n' in recorded['report']
    assert 'system_volume_status=pinned\n' in recorded['report']
    debug_dialog = next(args for args in run.messages if '--ok-label=Debug run' in args)
    assert '--cancel-label=Participant run' in debug_dialog
    assert '--default-cancel' in debug_dialog
    error = next(args for args in run.messages if '--error' in args)
    text = next(arg.removeprefix('--text=') for arg in error if arg.startswith('--text='))
    log = Path(text.split('Full log: ', 1)[1])
    assert log.is_file()
    assert 'simulated runner failure' in log.read_text()
    participant = run.study / 'data' / pid
    assert participant.exists() == plan_created
    if plan_created:
        assert log == participant / 'launch_error.log'
        assert not list(run.tmp_path.glob('av-experiment-*'))
    else:
        assert log.parent == run.tmp_path
    expected_server_entries = {'participant_02', '.claims'} if plan_created else {'participant_02'}
    assert {path.name for path in run.server_data.iterdir()} == expected_server_entries
    if plan_created:
        claim_files = list((run.server_data / '.claims').glob('participant_03.lock'))
        assert len(claim_files) == 1
        claim = json.loads(claim_files[0].read_text())
        assert claim['participant_id'] == 'participant_03'
        assert isinstance(claim['pid'], int)
        assert claim['host'] and claim['started_utc'] and claim['token']
    else:
        assert not (run.server_data / '.claims').exists()


@pytest.mark.parametrize('debug', [True, False])
def test_browser_gates_offer_skip_only_on_debug_runs(tmp_path, debug):
    run = run_launcher(tmp_path, debug=debug, skip_gates=True)
    gate = next(args for args in run.messages if '--ok-label=Consent completed' in args)
    assert ('--extra-button=Skip (debug)' in gate) == debug
    assert '--cancel-label=No, stop' in gate
    pid = run.recorded['pid']
    pid_dialog = next(
        args for args in run.messages
        if '--info' in args and any(pid in arg for arg in args)
    )
    assert run.messages.index(pid_dialog) < run.messages.index(gate)
    if debug:
        # Skipping one gate ends the browser block and the session still continues.
        assert run.browsers == [[CONSENT_URL]]
        assert 'consent_form=skipped\n' in run.recorded['report']
        assert 'participant_log=skipped\n' in run.recorded['report']
        assert 'browser_close=skipped\n' in run.recorded['report']
    else:
        assert run.browsers == [[CONSENT_URL], [PARTICIPANT_LOG_URL]]
        assert 'consent_form=completed\n' in run.recorded['report']
        assert 'participant_log=confirmed\n' in run.recorded['report']
        assert 'browser_close=confirmed\n' in run.recorded['report']


def test_digital_default_sink_blocks_preflight(tmp_path):
    """An S/PDIF or HDMI default output is never the study's headphone route."""
    run = run_launcher(tmp_path, digital=True)
    assert run.result.returncode == 1, run.result.stdout + run.result.stderr
    rows = next(args for args in run.messages if '--list' in args)
    assert any('Default output is digital' in arg for arg in rows)
    # A failed preflight must not consume a participant number: no folder is
    # created, and the reserved claim is released on exit.
    assert {path.name for path in run.server_data.iterdir()} == {'participant_02'}
    assert sorted(path.name for path in (run.study / 'data').iterdir()) == ['participant_01']
    error = next(args for args in run.messages if '--error' in args)
    assert any('required preflight checks failed' in arg for arg in error)


def test_digital_sink_is_accepted_when_the_lab_opts_in(tmp_path):
    """This lab's route is the DAC's S/PDIF output, so it may be accepted.

    The default stays fatal (see the test above); PREFLIGHT_ALLOW_DIGITAL_SINK
    records the deliberate decision so the route is not silently analog-only.
    """
    run = run_launcher(tmp_path, digital=True, allow_digital=True)
    assert run.result.returncode == 1, run.result.stdout + run.result.stderr
    rows = next(args for args in run.messages if '--list' in args)
    assert not any('Default output is digital' in arg for arg in rows)
    assert any('Digital output accepted' in arg for arg in rows)
    # The audio gate passed, so the run reaches the runner instead of stopping at
    # the checklist with a fatal-check dialog.
    assert not any('required preflight checks failed' in ' '.join(args) for args in run.messages)


@pytest.mark.parametrize(
    'gio_succeeds,expected', [(False, 'mount_failed'), (True, 'mount_not_visible')],
)
def test_unmounted_server_attempts_mount_and_reports_status(tmp_path, gio_succeeds, expected):
    """An unmounted share is mounted once, and its real outcome is reported."""
    run = run_launcher(
        tmp_path, mounted=False, server_uri='smb://example.test/share',
        gio_succeeds=gio_succeeds,
    )
    assert run.result.returncode == 1, run.result.stdout + run.result.stderr
    rows = next(args for args in run.messages if '--list' in args)
    # gio can exit 0 without the share appearing under the configured glob; that
    # must never be reported as a successful mount.
    assert any(f'Not mounted ({expected})' in arg for arg in rows)
    assert f'server_mount_status={expected}\n' in run.recorded['report']
    assert 'server_mounted=false\n' in run.recorded['report']
    # The session may still continue, but only after local-only storage is chosen.
    assert any('local-only storage' in ' '.join(args) for args in run.messages)


def test_preflight_sets_required_mode_and_restores_best_mode(tmp_path):
    """The study mode is applied at launch and the best mode comes back on exit."""
    run = run_launcher(tmp_path, initial_mode='1280x720')
    assert run.result.returncode == 1, run.result.stdout + run.result.stderr
    study_mode = ['--output', 'HDMI-1', '--mode', '1920x1080', '--rate', '120.00']
    assert study_mode in run.xrandr
    assert 'display_mode_action=set\n' in run.recorded['report']
    assert 'display_mode_set=1920x1080@120.00\n' in run.recorded['report']
    assert 'active_mode=1920x1080\n' in run.recorded['report']
    rows = next(args for args in run.messages if '--list' in args)
    assert any('set by preflight' in arg for arg in rows)
    # The runner failed, and the exit trap still restored the best mode.
    assert run.xrandr[-1] == ['--output', 'HDMI-1', '--mode', '2560x1440', '--rate', '240.00']


def test_configured_mount_root_is_used_without_a_gvfs_mount(tmp_path):
    """A configured absolute mount (the Camp-Lab CIFS share) needs no gvfs mount.

    The share is mounted by the system under /mnt, so it never appears under the
    gvfs directory the launcher used to glob. Without this the launcher would
    report the server as missing and quietly keep every session local.
    """
    mount = tmp_path / 'camp-lab-server' / 'Anthony'
    run = run_launcher(tmp_path, mounted=False, server_root=mount, plan_created=True)
    assert run.result.returncode == 1, run.result.stdout + run.result.stderr
    recorded = run.recorded
    assert recorded['pid'] == 'participant_03'
    assert 'server_mounted=true\n' in recorded['report']
    assert f'server_root={mount}\n' in recorded['report']
    assert f'server_data_path=study_data\n' in recorded['report']
    assert 'server_mount_status=configured_mount\n' in recorded['report']
    rows = next(args for args in run.messages if '--list' in args)
    assert any(f'Mounted and writable: {mount}' in arg for arg in rows)
    # The ID is reserved on the configured mount, not locally.
    claims = list((run.server_data / '.claims').glob('participant_03.lock'))
    assert len(claims) == 1
    assert json.loads(claims[0].read_text())['participant_id'] == 'participant_03'
