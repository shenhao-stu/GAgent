"""The signed `ios` helper module for code_run scripts, with the native bridge replaced by a stub.
Run: python3 -m pytest -q ios/tests/test_ios_module.py
"""
import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from signed_runtime import HOST
from agent_loop import exhaust
from kernel_adapter import ios_executor as executor
import ios


class NativeStub(types.ModuleType):
    """Stands in for the built-in _ganative module of the app."""

    def __init__(self):
        super().__init__('_ganative')
        self.main_calls = 0

    def on_main(self, function):
        self.main_calls += 1
        return function()


class Phone:
    """What the fake Objective-C classes below read and change."""

    def __init__(self):
        self.state = 0  # UIApplicationStateActive
        self.handled_schemes = {'weixin'}
        self.installed = {'com.tencent.xin'}
        self.opened = []
        self.clipboard = None
        self.changes = 0
        self.clipboard_writable = True


def fake_objc(phone):
    """A rubicon.objc module with just the classes the ios recipes use."""

    class URL:
        def __init__(self, text):
            self.text = text
            self.scheme = text.split(':', 1)[0] if ':' in text else None

    class NSURL:
        URLWithString_ = staticmethod(lambda text: URL(text) if text else None)

    class Application:
        @property
        def applicationState(self):
            return phone.state

        def openURL_options_completionHandler_(self, url, options, completion):
            success = phone.state == 0 and url.scheme in phone.handled_schemes
            if success:
                phone.opened.append(url.text)
            completion(success)

    class UIApplication:
        sharedApplication = Application()

    class Workspace:
        def openApplicationWithBundleID_(self, bundle_id):
            if bundle_id in phone.installed:
                phone.opened.append(bundle_id)
            return bundle_id in phone.installed

    class LSApplicationWorkspace:
        defaultWorkspace = staticmethod(Workspace)

    class Pasteboard:
        changeCount = property(lambda self: phone.changes)

        @property
        def string(self):
            return phone.clipboard

        @string.setter
        def string(self, value):
            if phone.clipboard_writable:
                phone.clipboard = value
                phone.changes += 1

    class UIPasteboard:
        generalPasteboard = Pasteboard()

    classes = {item.__name__: item for item in (NSURL, UIApplication, LSApplicationWorkspace, UIPasteboard)}

    def ObjCClass(name):
        if name not in classes:
            raise NameError(name)
        return classes[name]

    module = types.ModuleType('rubicon.objc')
    module.ObjCClass = ObjCClass
    module.classes = classes
    return module


class IOSModuleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()
        (self.root / 'temp').mkdir()
        self.env = patch.dict(os.environ, {'GA_DIR': str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def app(self):
        """Install the native stub and the fake Objective-C runtime; returns (native, phone)."""
        native, phone = NativeStub(), Phone()
        rubicon = types.ModuleType('rubicon')
        rubicon.objc = fake_objc(phone)
        modules = patch.dict(sys.modules, {'_ganative': native, 'rubicon': rubicon, 'rubicon.objc': rubicon.objc})
        modules.start()
        self.addCleanup(modules.stop)
        return native, phone

    def test_module_ships_in_the_signed_payload(self):
        self.assertEqual(Path(ios.__file__).resolve(), HOST / 'ios.py')

    def test_foreground_state_is_read_on_the_main_thread(self):
        native, phone = self.app()
        self.assertIs(ios.is_foreground(), True)
        phone.state = 2  # UIApplicationStateBackground
        self.assertIs(ios.is_foreground(), False)
        self.assertEqual(native.main_calls, 2)

    def test_open_url_reports_whether_ios_opened_it(self):
        native, phone = self.app()
        self.assertIs(ios.open_url('weixin://'), True)
        self.assertIs(ios.open_url('ga-no-such-scheme://check'), False)
        phone.state = 2
        self.assertIs(ios.open_url('weixin://'), False)
        self.assertEqual(phone.opened, ['weixin://'])
        for invalid in ('', 'no scheme'):
            with self.assertRaisesRegex(ios.IOSError, 'absolute URL'):
                ios.open_url(invalid)

    def test_open_url_gives_up_when_ios_never_answers(self):
        native, phone = self.app()
        application = ios.objc.ObjCClass('UIApplication').sharedApplication
        with patch.object(type(application), 'openURL_options_completionHandler_', lambda *args: None), \
                patch.object(ios, 'OPEN_ANSWER_SECONDS', 0.01):
            with self.assertRaisesRegex(ios.IOSError, 'did not answer'):
                ios.open_url('weixin://')

    def test_open_app_launches_by_bundle_identifier_or_raises(self):
        native, phone = self.app()
        self.assertIsNone(ios.open_app('com.tencent.xin'))
        self.assertEqual(phone.opened, ['com.tencent.xin'])
        with self.assertRaisesRegex(ios.IOSError, 'did not open com.example.missing'):
            ios.open_app('com.example.missing')

    def test_clipboard_round_trip_and_ignored_write(self):
        native, phone = self.app()
        self.assertIsNone(ios.clipboard_get())
        self.assertIs(ios.clipboard_set('你好'), True)
        self.assertEqual(ios.clipboard_get(), '你好')
        phone.clipboard_writable = False
        self.assertIs(ios.clipboard_set('ignored'), False)
        self.assertEqual(ios.clipboard_get(), '你好')

    def test_a_class_missing_from_this_system_raises_ios_error(self):
        self.app()
        del sys.modules['rubicon.objc'].classes['LSApplicationWorkspace']
        with self.assertRaisesRegex(ios.IOSError, 'LSApplicationWorkspace is not available'):
            ios.open_app('com.tencent.xin')

    def test_outside_the_app_the_helpers_fail_clearly(self):
        with patch.dict(sys.modules, {'_ganative': None}):
            with self.assertRaisesRegex(ios.IOSError, 'only inside the iOS app'):
                ios.is_foreground()
            with self.assertRaisesRegex(ios.IOSError, 'only inside the iOS app'):
                ios.on_main(lambda: 1)

    def test_on_main_returns_the_function_result(self):
        self.app()
        self.assertEqual(ios.on_main(lambda: 6 * 7), 42)

    def test_objc_is_rubicon_loaded_on_first_use(self):
        self.app()
        self.assertIs(ios.objc, sys.modules['rubicon.objc'])
        with self.assertRaises(AttributeError):
            ios.missing_helper

    def test_pip_install_targets_the_package_folder_and_accepts_only_pure_python(self):
        calls = []
        statuses = iter([0, 1])
        pip_main = types.ModuleType('pip._internal.cli.main')
        pip_main.main = lambda args: calls.append(args) or next(statuses)
        names = ('pip', 'pip._internal', 'pip._internal.cli', 'pip._internal.commands',
                 'pip._internal.commands.install')
        modules = {name: types.ModuleType(name) for name in names}
        modules['pip._internal.cli.main'] = pip_main
        modules['pip._internal.commands'].install = modules['pip._internal.commands.install']
        with patch.dict(sys.modules, modules):
            ios.pip_install('humanize', 'tabulate==0.9.0')
            with self.assertRaisesRegex(ios.IOSError, 'status 1'):
                ios.pip_install('numpy')
        self.assertEqual(calls[0], ['install', '--disable-pip-version-check', '--no-input', '--upgrade',
                                    '--target', str(self.root / 'pylib'), '--only-binary=:all:',
                                    '--implementation', 'py', '--abi', 'none', '--platform', 'any',
                                    'humanize', 'tabulate==0.9.0'])

    def test_the_bundled_pip_no_longer_guards_imports(self):
        # The real pip: its guard would fail other threads' imports and warn for ever after.
        packages = Path(__file__).resolve().parents[1] / 'Resources' / 'site-packages'
        if not (packages / 'pip').is_dir():
            self.skipTest('bundled pip is not staged; run ios/deps/get_python.sh')
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules), \
                patch.object(sys, 'path', [folder, *sys.path]):
            os.symlink(packages / 'pip', Path(folder) / 'pip')
            from pip._internal.commands import install
            self.assertTrue(callable(install._prevent_further_imports),
                            'pip renamed its import guard; update ios._keep_imports_open')
            ios._keep_imports_open()
            finders = list(sys.meta_path)
            with install._prevent_further_imports(until_process_exit=False):
                importlib.import_module('pip._internal.commands.show')
            self.assertEqual(sys.meta_path, finders)
            self.assertFalse(install._IMPORT_AUDIT_HOOK_INSTALLED)

    def test_code_run_scripts_can_import_the_module(self):
        native, phone = self.app()
        phone.state = 2
        result = exhaust(executor.code_run('import ios\nprint(ios.is_foreground())', cwd=str(self.root / 'temp')))
        self.assertEqual((result['exit_code'], result['stdout']), (0, 'False\n'))


if __name__ == '__main__':
    unittest.main()
