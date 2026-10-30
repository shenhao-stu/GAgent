"""StepFun dual-endpoint model catalog scoping (regression).

StepFun serves the same full catalog from both official endpoints — the
step_plan/v1/models response includes the pay-as-you-go models — so picking
the Plan endpoint used to list every model, and subscription-only models
showed up under the standard endpoint. The endpoint must scope the list.
"""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import android_entry

PLAN_BASE = 'https://api.stepfun.com/step_plan/v1'
API_BASE = 'https://api.stepfun.com/v1'
CATALOG = ['step-5-preview', 'step-3.7-flash', 'step-3.5-flash', 'step-3.5-flash-2603',
           'step-router-v1', 'stepaudio-2.5-asr', 'step-1o-turbo-vision', 'step-2-16k']
PLAN_MODELS = [m for m in CATALOG if android_entry._is_step_plan_model(m)]
API_MODELS = [m for m in CATALOG if not android_entry._is_step_plan_model(m)]


class StepFunScopeTest(unittest.TestCase):
    def test_plan_endpoint_keeps_only_plan_models(self):
        self.assertEqual(android_entry._scope_stepfun_models(PLAN_BASE, CATALOG), PLAN_MODELS)
        self.assertIn('step-5-preview', PLAN_MODELS)
        self.assertNotIn('step-2-16k', PLAN_MODELS)

    def test_api_endpoint_drops_plan_models(self):
        self.assertEqual(android_entry._scope_stepfun_models(API_BASE, CATALOG), API_MODELS)
        self.assertIn('step-2-16k', API_MODELS)
        self.assertNotIn('step-5-preview', API_MODELS)

    def test_non_stepfun_base_is_untouched(self):
        for base in ('https://example.test/v1', 'https://api.openai.com/v1', ''):
            self.assertEqual(android_entry._scope_stepfun_models(base, CATALOG), CATALOG)

    def test_trailing_slash_and_exact_path_suffix_tolerated(self):
        self.assertEqual(android_entry._scope_stepfun_models(PLAN_BASE + '/', CATALOG), PLAN_MODELS)
        self.assertEqual(android_entry._scope_stepfun_models(API_BASE + '/$', CATALOG), API_MODELS)

    def test_anthropic_style_plan_base_is_plan_scope(self):
        self.assertEqual(android_entry._stepfun_scope('https://api.stepfun.com/step_plan'), 'plan')

    def test_lookalike_host_is_not_stepfun(self):
        self.assertIsNone(android_entry._stepfun_scope('https://api.stepfun.com.evil.test/v1'))
        self.assertIsNone(android_entry._stepfun_scope('https://notstepfun.test/v1'))
        self.assertIsNone(android_entry._stepfun_scope('https://api.stepfun.com/v1beta'))

    def test_empty_scope_result_falls_back_to_full_catalog(self):
        self.assertEqual(android_entry._scope_stepfun_models(PLAN_BASE, ['step-2-16k']), ['step-2-16k'])


class ListModelsScopeTest(unittest.TestCase):
    """_list_models end-to-end: the fetched list itself is scoped by endpoint."""

    def _fetch(self, base):
        calls = {}

        def get(url, headers=None, proxies=None, timeout=None):
            calls['url'] = url
            calls['headers'] = headers
            return SimpleNamespace(status_code=200,
                                   json=lambda: {'object': 'list',
                                                 'data': [{'id': m} for m in CATALOG]})

        with patch.dict(sys.modules, {'requests': SimpleNamespace(get=get)}):
            out = json.loads(android_entry._list_models(json.dumps(
                {'apibase': base, 'apikey': 'test-placeholder', 'type': 'oai'})))
        return out, calls

    def test_plan_fetch_url_and_scoped_ids(self):
        out, calls = self._fetch(PLAN_BASE)
        self.assertTrue(out['ok'], out)
        self.assertEqual(calls['url'], PLAN_BASE + '/models')
        self.assertEqual(out['models'], sorted(PLAN_MODELS))   # _list_models 先 sorted 再裁剪

    def test_api_fetch_url_and_scoped_ids(self):
        out, calls = self._fetch(API_BASE)
        self.assertTrue(out['ok'], out)
        self.assertEqual(calls['url'], API_BASE + '/models')
        self.assertEqual(out['models'], sorted(API_MODELS))
