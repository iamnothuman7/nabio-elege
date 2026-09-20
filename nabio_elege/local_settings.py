"""Isolated, loopback-only demonstration. Never use for a public deployment."""
import os

os.environ.setdefault("SECRET_KEY", "local-demo-only-do-not-deploy")
from .settings import *  # noqa: F403,E402

DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "demo.sqlite3"}}
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
MFA_REQUIRED = False
LOCAL_DEMO = True
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
FIELD_ENCRYPTION_KEY = "I4ZUz7xTkP_dQW5RrNgZcT6vdp9xviCB7mKv_EyhvDc="
BLIND_INDEX_KEY = "local-demo-only-blind-index"
RECEIPT_TOKEN_KEY = "local-demo-only-receipt"
