#!/usr/bin/env python3
"""Inject an optional trusted-build PC Link profile without logging its contents."""
import json
import os
from pathlib import Path
import sys

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
from service_config import validate_service


def write_defaults(raw, destination):
    if not raw:
        destination.unlink(missing_ok=True)
        return
    try:
        config = validate_service('pclink', json.loads(raw))
        if not config:
            raise ValueError()
    except Exception:
        raise ValueError('Invalid PC Link build profile') from None
    destination.write_text(json.dumps(config) + '\n', encoding='utf-8')
    destination.chmod(0o600)


if __name__ == '__main__':
    write_defaults(os.environ.get('GAGENT_PCLINK_DEFAULTS', ''), CORE / 'pclink_defaults.json')
