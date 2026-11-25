"""An unavailable or unapproved member must not block an approved Auto fallback."""
import sys
import unittest
from unittest.mock import patch

import signed_runtime
import requests
import ios_policy
import llmcore


class IOSFallbackTests(unittest.TestCase):
    def run_chain(self, approved_secondary):
        class Response:
            status_code = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def json(self):
                return {'choices': [{'message': {'content': 'approved reply'}}]}

        def authorize(session):
            if session.name == 'secondary' and approved_secondary:
                return {}
            raise ios_policy.ConsentRequired({'receivers': [], 'accepted': False})

        with patch.object(sys, 'platform', 'ios'):
            clients = [llmcore.NativeToolClient(llmcore.NativeOAISession({
                'name': name, 'apibase': 'https://' + name + '.example/v1',
                'apikey': 'test-only', 'model': 'model-a', 'stream': False,
            })) for name in ('primary', 'secondary')]
            chain = llmcore.MixinSession(clients, {'llm_nos': [0, 1], 'max_retries': 1})
            with patch.object(ios_policy, 'model_headers', side_effect=authorize), \
                 patch.object(requests, 'post', return_value=Response()) as post:
                output = ''.join(chain.raw_ask([{'role': 'user', 'content': 'test'}]))
        return output, post

    def test_approved_secondary_runs_without_sending_to_primary(self):
        output, post = self.run_chain(True)
        self.assertEqual(output, 'approved reply')
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[0], 'https://secondary.example/v1/chat/completions')
        self.assertFalse(post.call_args.kwargs['allow_redirects'])

    def test_no_member_is_contacted_without_consent(self):
        output, post = self.run_chain(False)
        self.assertIn('ios_consent_required', output)
        post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
