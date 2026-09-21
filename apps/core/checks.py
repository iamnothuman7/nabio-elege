from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def production_guardrails(app_configs, **kwargs):
    if getattr(settings, "APP_ENV", "development") not in {"staging", "production"}:
        return []
    errors = []

    def require(condition, code, message):
        if not condition:
            errors.append(Error(message, id=f"nabio.{code}"))

    require(not settings.DEBUG and not getattr(settings, "LOCAL_DEMO", False), "E001", "Demonstração e DEBUG são proibidos neste ambiente.")
    require(settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql", "E002", "Use PostgreSQL dedicado em staging/produção.")
    require("apps.core.scope_middleware.CampaignScopeMiddleware" in settings.MIDDLEWARE, "E013", "O contexto transacional de isolamento deve estar ativo.")
    require(settings.MFA_REQUIRED, "E003", "MFA deve ser obrigatório neste ambiente.")
    require(settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE and settings.SECURE_SSL_REDIRECT, "E004", "Exija HTTPS e cookies seguros.")
    hosts = settings.ALLOWED_HOSTS
    require(bool(hosts) and all(h and not h.startswith(".") and "*" not in h and h not in {"localhost", "127.0.0.1", "testserver"} for h in hosts), "E005", "Defina somente hosts explícitos de staging/produção.")
    origins = settings.CSRF_TRUSTED_ORIGINS
    require(bool(origins) and all(urlsplit(o).scheme == "https" and urlsplit(o).hostname in hosts and "*" not in o for o in origins), "E006", "Defina origens CSRF HTTPS correspondentes aos hosts autorizados.")
    secrets = [settings.SECRET_KEY, settings.FIELD_ENCRYPTION_KEY, settings.BLIND_INDEX_KEY, settings.RECEIPT_TOKEN_KEY]
    placeholders = ("replace", "change-me", "test-only", "local-demo", "django-insecure", "<", ">")
    valid = all(isinstance(s, str) and len(s) >= 32 and not any(p in s.lower() for p in placeholders) for s in secrets)
    require(valid and len(set(secrets)) == len(secrets), "E007", "Configure quatro segredos fortes, independentes e exclusivos; valores não são exibidos.")
    try:
        Fernet(settings.FIELD_ENCRYPTION_KEY.encode())
        key_valid = settings.FIELD_ENCRYPTION_KEY != "I4ZUz7xTkP_dQW5RrNgZcT6vdp9xviCB7mKv_EyhvDc="
    except (ValueError, TypeError):
        key_valid = False
    require(key_valid, "E008", "Configure uma chave Fernet válida e diferente da demonstração.")
    cache = settings.CACHES["default"]
    require(cache["BACKEND"] == "django.core.cache.backends.redis.RedisCache" and str(cache.get("LOCATION", "")).startswith(("redis://", "rediss://")), "E009", "Use Redis compartilhado entre workers para os limites de requisição.")
    require(bool(settings.CLAMAV_HOST), "E010", "Configure o serviço antivírus antes de liberar uploads.")
    for name in ["MEDIA_ROOT", "STATIC_ROOT"]:
        path = Path(getattr(settings, name))
        require(path.is_absolute() and path != Path(path.anchor) and not path.is_relative_to(settings.BASE_DIR), "E011", f"{name} deve usar um diretório persistente específico fora da release.")
    require(Path(settings.MEDIA_ROOT) != Path(settings.STATIC_ROOT) and not Path(settings.MEDIA_ROOT).is_relative_to(settings.STATIC_ROOT) and not Path(settings.STATIC_ROOT).is_relative_to(settings.MEDIA_ROOT), "E012", "Separe uploads privados e arquivos estáticos públicos.")
    return errors
