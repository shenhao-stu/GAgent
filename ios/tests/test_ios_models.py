"""Model discovery must honor the iOS endpoint disclosed before sending credentials."""
import json
import sys
import types
import unittest
from unittest.mock import patch

import signed_runtime
import requests
import android_entry


class ModelDiscoveryTests(unittest.TestCase):
    def discover(self, base, platform='ios', status=200):
        response = types.SimpleNamespace(status_code=status, json=lambda: {'data': [{'id': 'model-a'}]})
        with patch.object(sys, 'platform', platform), patch.object(requests, 'get', return_value=response) as get:
            result = json.loads(android_entry._list_models(json.dumps({
                'apibase': base, 'apikey': 'fixture-claude-key', 'type': 'claude'})))
        return result, get

    def test_ios_rejects_unsafe_endpoints_before_sending_key(self):
        for base in ('http://example.com/v1', 'https://user:secret@example.com/v1',
                     'https://example.com/v1?key=secret'):
            with self.subTest(base=base):
                result, get = self.discover(base)
                self.assertFalse(result['ok'])
                get.assert_not_called()
                self.assertNotIn('secret', result['error'])

    def test_ios_valid_https_discovery_keeps_key_at_disclosed_endpoint(self):
        result, get = self.discover('https://example.com/v1')
        self.assertEqual(result, {'ok': True, 'models': ['model-a']})
        self.assertEqual(get.call_args.args, ('https://example.com/v1/models',))
        self.assertEqual(get.call_args.kwargs['headers']['x-api-key'], 'fixture-claude-key')
        self.assertIs(get.call_args.kwargs['allow_redirects'], False)

    def test_ios_redirect_cannot_forward_key_or_masquerade_as_models(self):
        result, get = self.discover('https://example.com/v1', status=302)
        self.assertFalse(result['ok'])
        self.assertIn('重定向', result['error'])
        self.assertIs(get.call_args.kwargs['allow_redirects'], False)
        self.assertEqual(get.call_count, 1)

    def test_android_discovery_preserves_existing_transport(self):
        result, get = self.discover('http://example.com/v1', platform='android')
        self.assertTrue(result['ok'])
        self.assertEqual(get.call_args.args, ('http://example.com/v1/models',))
        self.assertNotIn('allow_redirects', get.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
