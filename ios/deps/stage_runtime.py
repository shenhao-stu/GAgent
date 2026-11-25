"""Stage signed iOS modules from main's runtime. Only tracked or shipping runtime files are eligible."""
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
RUNTIME = Path('app/src/main/assets/ga_runtime')
GUIDES = {'phone_use_ios.md', 'memory_management_sop.md', 'memory_cleanup_sop.md', 'goal_mode_sop.md'}
MODULES = {
    'android_entry', 'ios_entry', 'ios_policy', 'ios',
    'screen', 'hid', 'board_bridge',
    'pclink', 'p2p_ws_client',
    'provider_config', 'service_config', 'service_http',
    'run_guard',
}


def ship(path):
    top, *rest = path.parts
    if not rest:
        return top.endswith('.py') and path.stem in MODULES
    if top == 'memory':
        return path.name in GUIDES
    if top == 'assets':
        return rest in (['tools_schema.json'], ['tools_schema_cn.json'])
    if top == 'plugins':
        return len(rest) == 1 and path.name in {'hooks.py', 'desc_inject_hook.py', 'tool_events_hook.py'}
    if top == 'webui' and rest[0] == 'plan':
        return False
    return top in {'gacore', 'webui', 'kernel_adapter'} and path.name != 'executor.py'


def _runtime_files():
    tracked = set()
    try:
        raw = subprocess.check_output(['git', 'ls-files', '-z', '--', str(RUNTIME)], cwd=REPO)
        tracked.update(p for p in raw.decode().split('\0') if p)
    except Exception:
        pass
    root = REPO / RUNTIME
    for p in root.rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts:
            tracked.add(p.relative_to(REPO).as_posix())
    return sorted(tracked)


def stage(destination):
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError('stage_runtime requires an empty destination')
    for raw in _runtime_files():
        path = Path(raw)
        if not (REPO / path).is_file():
            continue
        rel = path.relative_to(RUNTIME)
        if ship(rel):
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / path, target)
    subprocess.run(['patch', '-s', '-f', '-F', '0', '-p1', '-i', str(REPO / 'ios/deps/signed-host.patch')],
                   cwd=destination / 'gacore', check=True)
    for module in MODULES:
        if not (destination / (module + '.py')).is_file():
            raise FileNotFoundError(module)
    for guide in GUIDES:
        if not (destination / 'memory' / guide).is_file():
            raise FileNotFoundError(guide)
    shutil.copyfile(REPO / 'ios/deps/legacy-route-hashes.json', destination / 'assets/legacy-route-hashes.json')
    shutil.copyfile(REPO / 'ios/deps/stock-memory.json', destination / 'stock-memory.json')


if __name__ == '__main__':
    stage(Path(sys.argv[1]).resolve())
