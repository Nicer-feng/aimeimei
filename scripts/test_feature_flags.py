"""Isolated feature configuration and HTTP persistence checks."""
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import test_reading as fixtures
from ai_platform.features import feature_flags
from ai_platform.database import db


class FeatureFlagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ReadingTests.setUpClass()
        cls.fixture = fixtures.ReadingTests
        cls.temp = tempfile.TemporaryDirectory(prefix='aimeimei-features-')
        cls.path = Path(cls.temp.name) / 'secrets.json'
        cls.config_patch = patch('ai_platform.handlers.admin.SECRETS_PATH', cls.path)
        cls.config_patch.start()
        with db() as conn:
            conn.execute("UPDATE users SET role='admin' WHERE id='reader-a'")

    @classmethod
    def tearDownClass(cls):
        cls.config_patch.stop()
        cls.fixture.tearDownClass()
        cls.temp.cleanup()

    def setUp(self):
        self.fixture.server.secrets['feature_flags'] = {'selection_quote': False, 'side_discussion': True}

    def request(self, path, body=None, user='reader-a'):
        headers = {'Authorization': 'Bearer ' + user} if user else {}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.fixture.url + path, headers=headers,
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_legacy_config_defaults_on(self):
        self.assertTrue(feature_flags({})['long_text_detection'])
        self.assertTrue(feature_flags({'feature_flags': None})['long_text_detection'])
        code, data = self.request('/api/features', user='reader-b')
        self.assertEqual(code, 200)
        self.assertTrue(data['features']['long_text_detection'])
        self.assertFalse(data['features']['selection_quote'])

    def test_persist_off_reload_and_reenable(self):
        code, data = self.request('/api/admin/features', {'features': {'long_text_detection': False}})
        self.assertEqual(code, 200)
        expected = {'selection_quote': False, 'side_discussion': True, 'long_text_detection': False}
        self.assertEqual(data['features'], expected)
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved['feature_flags'], expected)
        self.fixture.server.secrets = saved
        self.assertEqual(self.request('/api/features', user='reader-b')[1]['features'], expected)
        self.assertTrue(self.request('/api/admin/features', {'features': {'long_text_detection': True}})[1]['features']['long_text_detection'])

    def test_other_switches_preserve_detection_value(self):
        self.request('/api/admin/features', {'features': {'long_text_detection': False}})
        self.request('/api/admin/features', {'features': {'side_discussion': False}})
        self.assertFalse(self.request('/api/admin/features')[1]['features']['long_text_detection'])
        self.assertFalse(self.request('/api/admin/features')[1]['features']['side_discussion'])

    def test_admin_auth_denies_non_admin_changes(self):
        self.assertEqual(self.request('/api/admin/features', {'features': {'long_text_detection': False}}, user='reader-b')[0], 401)
        self.assertEqual(self.request('/api/admin/features', user=None)[0], 401)
        self.assertTrue(self.request('/api/features')[1]['features']['long_text_detection'])


if __name__ == '__main__':
    unittest.main()
