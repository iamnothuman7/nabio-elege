from .test_settings import *  # noqa: F403

DATABASES = {"default": env.db("TEST_DATABASE_URL")}  # noqa: F405
