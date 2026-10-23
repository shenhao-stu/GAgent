import importlib.util
import os
from pathlib import Path
import sys

import pytest
CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))


def test_bus_capability_tracks_bound_port_without_leaking(tmp_path, monkeypatch):
    import bus_auth
    monkeypatch.setenv('GA_DIR', str(tmp_path))
    (tmp_path / '.bus_token').write_text('a'*64)
    (tmp_path / 'bus_port.txt').write_text('39123')
    assert bus_auth.headers('http://127.0.0.1:39123/ping') == {'Authorization': 'Bearer '+'a'*64}
    assert bus_auth.headers('http://127.0.0.1:18765/ping') == {}
    assert bus_auth.headers('https://example.test:39123/ping') == {}


@pytest.mark.parametrize('package', ['com.ljq.ga', 'io.github.shenhaostu.gagent', 'io.github.shenhaostu.gagent.debug'])
def test_navigation_never_targets_own_app(package, monkeypatch):
    import jev_ui
    monkeypatch.setenv('GA_PACKAGE', package)
    with pytest.raises(ValueError, match='foreground app'):
        jev_ui._tap_target(None, 'Open settings', package, 2, {}, False)
