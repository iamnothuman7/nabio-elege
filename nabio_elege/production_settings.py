"""Service environment only. No checkout .env or demo credentials are loaded."""
import os

os.environ.setdefault("APP_ENV", "production")
from .settings import *  # noqa: F403,E402

DEBUG = False
LOCAL_DEMO = False
SECRET_KEY = env("SECRET_KEY")
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"].setdefault("OPTIONS", {}).update({"connect_timeout": 5, "options": "-c statement_timeout=15000 -c lock_timeout=5000"})
DATABASES["default"]["CONN_MAX_AGE"] = 60
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
MFA_REQUIRED = True
MEDIA_ROOT = Path(env("MEDIA_ROOT"))
STATIC_ROOT = Path(env("STATIC_ROOT"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": env("CACHE_URL"), "OPTIONS": {"socket_connect_timeout": 3, "socket_timeout": 3}}}
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_TASK_TIME_LIMIT = 300
CELERY_BROKER_CONNECTION_TIMEOUT = 5
CELERY_BROKER_TRANSPORT_OPTIONS = {"socket_connect_timeout": 5, "socket_timeout": 5}
