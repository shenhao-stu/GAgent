"""Run the desktop Hub with its transport and an existing Python environment.

An older Hub can opt into the iOS transport if its signal handling differs.
"""
import argparse
import importlib.util
from pathlib import Path
import runpy
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hub', type=Path, help='Existing desktop frontends/hub.py')
    parser.add_argument('--package-dir', type=Path, action='append', default=[],
                        help='Optional existing site-packages with the same Python ABI')
    parser.add_argument('--legacy-ios-transport', action='store_true',
                        help='Load this iOS transport in place of an older desktop transport')
    args = parser.parse_args()
    for directory in args.package_dir:
        sys.path.append(str(directory.expanduser().resolve(strict=True)))
    # Fail before listening rather than accepting a pairing that cannot forward requests.
    import aiohttp, fastapi, uvicorn  # noqa: F401
    hub = args.hub.expanduser().resolve(strict=True)
    if args.legacy_ios_transport:
        transport = Path(__file__).resolve().parents[2] / 'app/src/main/assets/ga_runtime/p2p_ws_client.py'
        spec = importlib.util.spec_from_file_location('p2p_ws_client', transport)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.DEFAULT_SIGNAL_URL = module.STANDARD_SIGNAL_URL
    sys.path.insert(0, str(hub.parent))
    sys.argv = [str(hub)]
    runpy.run_path(str(hub), run_name='__main__')


if __name__ == '__main__':
    main()
