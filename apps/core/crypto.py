import base64
import hashlib
import hmac
import json

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _required_secret(setting_name):
    value = getattr(settings, setting_name, "")
    if not value:
        raise ImproperlyConfigured(f"A configuração {setting_name} é obrigatória.")
    return value


def encrypt_json(value):
    key = _required_secret("FIELD_ENCRYPTION_KEY").encode("ascii")
    plaintext = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return Fernet(key).encrypt(plaintext)


def decrypt_json(ciphertext):
    key = _required_secret("FIELD_ENCRYPTION_KEY").encode("ascii")
    plaintext = Fernet(key).decrypt(bytes(ciphertext))
    return json.loads(plaintext.decode("utf-8"))


def blind_index(value, *, campaign_id):
    key = _required_secret("BLIND_INDEX_KEY").encode("utf-8")
    normalized = f"{campaign_id}:{value.strip().casefold()}".encode("utf-8")
    return hmac.new(key, normalized, hashlib.sha256).hexdigest()


def derive_receipt_token(receipt_id):
    key = _required_secret("RECEIPT_TOKEN_KEY").encode("utf-8")
    digest = hmac.new(key, str(receipt_id).encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
