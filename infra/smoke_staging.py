"""Synthetic HTTP integration rehearsal; refuses production and prints no secrets."""

import http.client
from http.cookies import SimpleCookie
import io
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import sys
import time
from urllib.parse import urlencode
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nabio_elege.production_settings")
import django

django.setup()
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from apps.campaigns.models import Campaign, Permission, Tenant
from apps.core.crypto import decrypt_json
from apps.core.models import Document
from apps.core.rls import database_scope
from apps.workspace.document_services import scan_stream, upload_document
from apps.workspace.models import SecurityProfile
from apps.workspace.registry import MODULES
from apps.workspace.security import totp


class LocalTLS(http.client.HTTPSConnection):
    def connect(self):
        raw = socket.create_connection(("127.0.0.1", 8449), timeout=15)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


class Browser:
    def __init__(self):
        self.cookies = SimpleCookie()
        self.requests = 0

    def request(self, path, data=None, csrf=True):
        headers = {
            "Host": "elege.nabio.pro:8449",
            "Referer": "https://elege.nabio.pro:8449" + path,
            "Cookie": "; ".join(
                f"{key}={value.value}" for key, value in self.cookies.items()
            ),
        }
        if data is not None:
            data = dict(data)
            if csrf and "csrftoken" in self.cookies:
                data["csrfmiddlewaretoken"] = self.cookies["csrftoken"].value
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        connection = LocalTLS(
            "elege.nabio.pro", 8449, timeout=15, context=ssl.create_default_context()
        )
        connection.request(
            "POST" if data is not None else "GET",
            path,
            urlencode(data) if data is not None else None,
            headers,
        )
        response = connection.getresponse()
        for key, value in response.getheaders():
            if key.lower() == "set-cookie":
                self.cookies.load(value)
        body = response.read()
        status, location = response.status, response.getheader("Location")
        if response.getheader("X-Content-Type-Options") != "nosniff":
            raise RuntimeError("Missing security header")
        connection.close()
        self.requests += 1
        return status, location, body


def main():
    if settings.APP_ENV != "staging" or settings.DEBUG or settings.LOCAL_DEMO:
        raise RuntimeError("Synthetic smoke is restricted to non-demo staging")
    suffix = uuid.uuid4().hex[:10]
    username, password = "qa." + suffix, secrets.token_urlsafe(32)
    command = [
        "--tenant-name",
        "Homologação sintética",
        "--tenant-slug",
        "qa-" + suffix,
        "--campaign-name",
        "QA sem dados reais",
        "--campaign-code",
        "qa-" + suffix,
        "--election-id",
        "synthetic",
        "--office-code",
        "test",
        "--jurisdiction-code",
        "TEST",
        "--username",
        username,
        "--password-stdin",
    ]
    for code in Permission.objects.values_list("code", flat=True):
        command.extend(["--permission", code])
    original_stdin = sys.stdin
    try:
        sys.stdin = io.StringIO(password + "\n")
        call_command("bootstrap_operator", *command, stdout=io.StringIO())
    finally:
        sys.stdin = original_stdin
    user = User.objects.get(username=username)
    tenant = Tenant.objects.get(slug="qa-" + suffix)
    campaign = Campaign.objects.get(tenant=tenant)
    browser = Browser()
    assert browser.request("/entrar/")[0] == 200
    assert (
        browser.request(
            "/entrar/", {"username": username, "password": password}, csrf=False
        )[0]
        == 403
    )
    assert browser.request("/entrar/", {"username": username, "password": password})[
        :2
    ] == (302, "/senha/")
    assert (
        browser.cookies["sessionid"]["secure"]
        and browser.cookies["sessionid"]["httponly"]
    )
    assert browser.request("/senha/")[0] == 200
    new_password = secrets.token_urlsafe(32)
    assert browser.request(
        "/senha/",
        {
            "old_password": password,
            "new_password1": new_password,
            "new_password2": new_password,
        },
    )[:2] == (302, "/seguranca/")
    assert browser.request("/seguranca/")[0] == 200
    profile = SecurityProfile.objects.get(user=user)
    secret = decrypt_json(profile.totp_secret_ciphertext)["secret"]
    assert (
        browser.request("/seguranca/", {"code": totp(secret, int(time.time()) // 30)})[
            0
        ]
        == 200
    )
    profile.refresh_from_db()
    assert profile.enabled_at and not profile.password_change_required
    lists = forms = 0
    for module in MODULES:
        path = reverse("module_list", args=[campaign.pk, module.key])
        assert browser.request(path)[0] == 200, module.key
        lists += 1
        if module.fields:
            assert (
                browser.request(
                    reverse("module_create", args=[campaign.pk, module.key])
                )[0]
                == 200
            ), module.key
            forms += 1
    for name in ("dashboard", "campaign_map", "team", "audit_log", "reports"):
        assert browser.request(reverse(name, args=[campaign.pk]))[0] == 200, name
    create = reverse("module_create", args=[campaign.pk, "projetos"])
    assert (
        browser.request(
            create,
            {
                "title": "QA sintético",
                "description": "Sem dados reais",
                "command_id": str(uuid.uuid4()),
            },
        )[0]
        == 302
    )
    other = Campaign.objects.create(
        tenant=tenant,
        code="isolated-" + suffix,
        name="Outra campanha sintética",
        election_id="test",
        office_code="test",
        jurisdiction_code="TEST",
    )
    assert browser.request(reverse("dashboard", args=[other.pk]))[0] in (403, 404)
    assert (
        scan_stream(
            io.BytesIO(
                b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
            )
        )
        == "rejected"
    )
    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"
    assert scan_stream(io.BytesIO(pdf)) == "clean"
    with database_scope(campaign=campaign, actor=user):
        document = Document.objects.create(
            tenant=tenant,
            campaign=campaign,
            created_by=user,
            display_name="QA PDF sintético",
            classification="internal",
        )
        version = upload_document(
            user, document, SimpleUploadedFile("synthetic.pdf", pdf)
        )
        assert version.scan_status == "clean"
        private_path = settings.MEDIA_ROOT / "private" / version.storage_key
        assert private_path.read_bytes() == pdf
        quarantined = Document.objects.create(
            tenant=tenant,
            campaign=campaign,
            created_by=user,
            display_name="QA falha segura",
            classification="internal",
        )
        with override_settings(CLAMAV_PORT=0):
            blocked = upload_document(
                user, quarantined, SimpleUploadedFile("synthetic.pdf", pdf)
            )
        assert blocked.scan_status == "error" and quarantined.status == "quarantined"
    assert (
        browser.request(
            reverse("document_download", args=[campaign.pk, document.pk, version.pk])
        )[2]
        == pdf
    )
    assert browser.request(
        reverse("document_download", args=[campaign.pk, quarantined.pk, blocked.pk])
    )[0] in (403, 404)
    assert browser.request("/media/private/" + version.storage_key)[0] in (403, 404)
    assert browser.request("/sair/", {})[0] == 302
    assert browser.request(reverse("dashboard", args=[campaign.pk]))[0] == 302
    user.is_active = False
    user.save(update_fields=["is_active"])
    result = {
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sha": Path(__file__).resolve().parents[1].name,
        "https_requests": browser.requests,
        "module_lists": lists,
        "create_forms": forms,
        "password_mfa_csrf_isolation_logout": True,
        "real_antivirus_clean_eicar": True,
        "private_upload_download_and_fail_closed": True,
    }
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
