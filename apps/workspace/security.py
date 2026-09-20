"""Small RFC 6238 implementation using the Python standard library."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.crypto import decrypt_json, hash_token
from .models import SecurityProfile


def new_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret, counter, digits=6):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff
    return str(number % (10 ** digits)).zfill(digits)


def matching_counter(secret, code, last_counter=-1, now=None):
    code = str(code).strip()
    if len(code) != 6 or not code.isdigit():
        return None
    counter = int(time.time() if now is None else now) // 30
    for candidate in (counter, counter - 1, counter + 1):
        if candidate > last_counter and hmac.compare_digest(totp(secret, candidate), code):
            return candidate
    return None


def verify_second_factor(user, code):
    # Commit failed attempts too; do not raise inside this atomic block.
    valid = False
    with transaction.atomic():
        profile = SecurityProfile.objects.select_for_update().get(user=user)
        if profile.locked_until and profile.locked_until > timezone.now():
            return False
        secret = decrypt_json(profile.totp_secret_ciphertext)["secret"]
        counter = matching_counter(secret, code, profile.last_counter)
        recovery = hash_token(code.strip())
        if counter is not None:
            profile.last_counter = counter
            valid = True
        elif profile.enabled_at and recovery in profile.recovery_hashes:
            profile.recovery_hashes = [item for item in profile.recovery_hashes if not hmac.compare_digest(item, recovery)]
            valid = True
        if valid:
            profile.failures = 0
            profile.locked_until = None
        else:
            profile.failures += 1
            if profile.failures >= 5:
                profile.locked_until = timezone.now() + timedelta(minutes=15)
                profile.failures = 0
        profile.save()
    return valid
