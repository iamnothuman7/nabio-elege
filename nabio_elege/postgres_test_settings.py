from .test_settings import *  # noqa: F403

DATABASES = {"default": env.db("TEST_DATABASE_URL")}  # noqa: F405
if os.environ.get("TEST_DATABASE_NAME"):  # noqa: F405
    DATABASES["default"]["TEST"] = {"NAME": os.environ["TEST_DATABASE_NAME"]}  # noqa: F405
