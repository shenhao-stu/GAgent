"""The optional display adapter must load before any device connection exists."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


@pytest.mark.parametrize('package', [None, 'io.github.shenhaostu.gagent.debug'])
def test_import_uses_installation_identity_without_device_io(monkeypatch, package):
    if package is None:
        monkeypatch.delenv('GA_PACKAGE', raising=False)
    else:
        monkeypatch.setenv('GA_PACKAGE', package)
    monkeypatch.setitem(sys.modules, 'droid', ModuleType('droid'))
    path = Path(__file__).parents[1] / 'app/src/main/assets/gacore/vdisplay.py'
    spec = importlib.util.spec_from_file_location('vdisplay_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._PKG == (package or 'io.github.shenhaostu.gagent')
    assert callable(module.vd_probe)
