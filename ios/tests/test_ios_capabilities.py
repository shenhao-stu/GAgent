"""Offline checks for truthful platform prompts and preserved user memories."""
import hashlib
import json
import os
import sys
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from signed_runtime import ANDROID, CORE, HOST
import agentmain
import ga
import ios_policy
from kernel_adapter import ios_host


class IOSCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()
        (self.root / 'memory').mkdir()
        self.memory = self.root / 'memory/global_mem_insight.txt'
        self.stock = [(ANDROID / f'assets/global_mem_insight_template{s}.txt').read_text() for s in ('', '_en')]

    def tearDown(self):
        self.directory.cleanup()

    @unittest.skipUnless(sys.platform == 'darwin', 'Swift Foundation and CryptoKit required')
    def test_migration_replaces_known_stock_and_preserves_edited_or_linked_guides(self):
        bundle = self.root / 'bundle'
        (bundle / 'memory').mkdir(parents=True)
        updated = b'ReplayKit first'
        old = b'previous stock guide'
        variants = [hashlib.sha256(content).hexdigest() for content in (b'older guide', old)]
        names = ['phone_use_ios.md', 'custom.md', 'linked.md', 'retired.md']
        (bundle / 'stock-memory.json').write_text(json.dumps({name: variants for name in names}))
        for name in names[:-1]:
            (bundle / 'memory' / name).write_bytes(updated)
        memory = self.root / 'memory'
        (memory / names[0]).write_bytes(old)
        (memory / names[1]).write_bytes(old + b'\nmy additions')
        external = self.root / 'external.md'
        external.write_bytes(old)
        (memory / names[2]).symlink_to(external)
        (memory / names[3]).write_bytes(old)
        script = self.root / 'main.swift'
        script.write_text('import Foundation\n'
                          'try Assets.refreshStockMemory(in: URL(fileURLWithPath: CommandLine.arguments[1]),'
                          ' from: URL(fileURLWithPath: CommandLine.arguments[2]))\n')
        executable = self.root / 'migrate'
        source = Path(__file__).resolve().parents[1] / 'GAgent/Assets.swift'
        subprocess.run(['xcrun', 'swiftc', source, script, '-o', executable], check=True)
        subprocess.run([executable, self.root, bundle], check=True)
        self.assertEqual((memory / names[0]).read_bytes(), updated)
        self.assertEqual((memory / names[1]).read_bytes(), old + b'\nmy additions')
        self.assertTrue((memory / names[2]).is_symlink())
        self.assertEqual(external.read_bytes(), old)
        self.assertFalse((memory / names[3]).exists())

    def test_stock_android_routes_are_replaced_without_changing_user_data(self):
        user = 'L2: 我的偏好 ../memory/preferences.md\n自定义Android项目：import droid 示例属于配对电脑。'
        for source in self.stock:
            with self.subTest(language=source[:60]):
                original = source + '\n' + user
                self.memory.write_text(original)
                with patch.object(sys, 'platform', 'ios'), patch.dict(os.environ, {'GA_DIR': str(self.root)}):
                    prompt = ga.get_global_memory()
                self.assertEqual(self.memory.read_text(), original)
                self.assertIn(user, prompt)
                self.assertIn('phone_use_ios.md', prompt)
                self.assertNotIn('import webcdp', prompt)
                self.assertNotIn('import vdisplay', prompt)
                self.assertNotIn('VLM coordinates are always forbidden', prompt)
                self.assertNotIn('本机即Android手机', prompt)
                self.assertNotIn('this machine IS the Android phone', prompt)
                self.assertNotIn('3次失败', prompt)
                self.assertNotIn('after 3 failures', prompt)

    def test_projection_is_idempotent_and_keeps_non_factory_routes(self):
        original = self.stock[0] + '\nMy project uses import webcdp on its computer.'
        projected = ios_policy.project_memory(original, self.stock)
        self.assertIn('My project uses import webcdp on its computer.', projected)
        self.assertEqual(ios_policy.project_memory(projected, self.stock), projected)

    def test_ios_prompt_no_longer_claims_local_executor_or_plugin_install(self):
        self.memory.write_text(self.stock[0])
        with patch.object(sys, 'platform', 'ios'), patch.dict(os.environ, {'GA_DIR': str(self.root)}):
            prompt = agentmain.get_system_prompt()
        self.assertIn('screen provides an image', prompt)
        self.assertNotIn('iphone_', prompt)
        self.assertNotIn('device_tool', prompt)
        self.assertNotIn('pc_catalog', prompt)
        self.assertIn('frame_id', prompt)
        self.assertIn('pc_link', prompt)
        self.assertNotIn('物理级全能执行者', prompt)
        self.assertNotIn('可装纯Python包', prompt)
        self.assertNotIn('GUI任务先读phone_use.md', prompt)

    def test_android_prompt_and_memory_are_unchanged(self):
        android = self.root / 'android'
        for directory in ('assets', 'gacore', 'kernel_adapter'):
            shutil.copytree(ANDROID / directory, android / directory)
        shutil.copyfile(ANDROID / 'run_guard.py', android / 'run_guard.py')
        probe = """
import os, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from kernel_adapter import install
agent = install(root)
for suffix, language in (('', 'zh'), ('_en', 'en')):
    os.environ['GA_LANG'] = language
    source = (root / f'assets/global_mem_insight_template{suffix}.txt').read_text()
    (root / 'memory/global_mem_insight.txt').write_text(source)
    prompt = agent.get_system_prompt()
    assert (root / f'assets/sys_prompt{suffix}.txt').read_text() in prompt
    assert source in prompt and '[iOS capability routes]' not in prompt
"""
        subprocess.run([sys.executable, '-I', '-c', probe, str(android)], check=True, timeout=30)

    def test_signed_phone_guide_is_read_only_and_does_not_replace_user_memory(self):
        user_guide = self.root / 'memory/phone_use_ios.md'
        user_guide.write_text('User notes remain editable and preserved.')
        with patch.dict(os.environ, {'GA_DIR': str(self.root)}):
            self.assertEqual(ios_policy.checked_path(ios_policy.phone_guide()), str(ios_policy.phone_guide()))
            self.assertEqual(ios_policy.checked_path(user_guide, write=True), str(user_guide))
            for path, write in ((ios_policy.phone_guide(), True), (HOST / 'memory/phone_use.md', False),
                                (CORE / 'agentmain.py', False)):
                with self.subTest(path=path, write=write), self.assertRaises(ValueError):
                    ios_policy.checked_path(path, write=write)
        self.assertEqual(user_guide.read_text(), 'User notes remain editable and preserved.')

    def test_ios_boot_seeds_platform_memory_and_preserves_existing_user_index(self):
        ios_host.seed_memory(self.memory.parent)
        self.assertEqual(self.memory.read_text(), ios_policy.MEMORY_SEED)
        user = 'L3: my_workflow.md\n自定义知识保持原样。'
        self.memory.write_text(user)
        ios_host.seed_memory(self.memory.parent)
        self.assertEqual(self.memory.read_text(), user)


if __name__ == '__main__':
    unittest.main()
