from .settings import *  # noqa: F403


DATABASES = {  # noqa: F405
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test.sqlite3",  # noqa: F405
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
FIELD_ENCRYPTION_KEY = "I4ZUz7xTkP_dQW5RrNgZcT6vdp9xviCB7mKv_EyhvDc="
BLIND_INDEX_KEY = "test-only-blind-index-key"
RECEIPT_TOKEN_KEY = "test-only-receipt-token-key"
