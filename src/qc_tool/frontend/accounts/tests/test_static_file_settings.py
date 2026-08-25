"""Static-file behavior must follow the deployment environment, not DEBUG."""

from django.conf import settings
from django.test import SimpleTestCase


class DevelopmentStaticFileSettingsTests(SimpleTestCase):
    def test_non_secure_environment_reads_live_static_sources(self):
        """Local DEBUG=False sessions must not be pinned to collectstatic."""

        self.assertFalse(settings.IS_SECURE_ENVIRONMENT)
        self.assertTrue(settings.WHITENOISE_AUTOREFRESH)
        self.assertTrue(settings.WHITENOISE_USE_FINDERS)
        self.assertEqual(settings.WHITENOISE_MAX_AGE, 0)
