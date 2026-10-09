import os

os.environ.setdefault("DJANGO_SECRET_KEY", "insecure-test-only-key")

from lerp.settings import *  # noqa: E402,F403

# No collected static files in tests, so skip WhiteNoise.
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
