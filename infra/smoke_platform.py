"""HTTPS product-access rehearsal, synthetic staging accounts only."""

import io
import json
import secrets
import sys
import time
import uuid

from smoke_staging import (
    Browser,
    Campaign,
    SecurityProfile,
    Tenant,
    User,
    call_command,
    decrypt_json,
    settings,
    totp,
)
from apps.campaigns.models import Membership
from apps.workspace.platform_metrics import usage_snapshot


def login(browser, username, password):
    assert browser.request("/entrar/")[0] == 200
    assert browser.request("/entrar/", {"username": username, "password": password})[
        :2
    ] == (302, "/senha/")
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
    secret = decrypt_json(
        SecurityProfile.objects.get(user__username=username).totp_secret_ciphertext
    )["secret"]
    assert (
        browser.request("/seguranca/", {"code": totp(secret, int(time.time()) // 30)})[
            0
        ]
        == 200
    )
    assert SecurityProfile.objects.get(user__username=username).enabled_at


def main():
    if settings.APP_ENV != "staging" or settings.DEBUG or settings.LOCAL_DEMO:
        raise RuntimeError(
            "Staging only; never creates QA administrators in production"
        )
    suffix = uuid.uuid4().hex[:12]
    admin_name, demo_name, third_name, operator_name = (
        "qa.admin." + suffix,
        "qa.demo." + suffix,
        "qa.client." + suffix,
        "qa.operator." + suffix,
    )
    passwords = {
        "admin_password": secrets.token_urlsafe(32),
        "demo_password": secrets.token_urlsafe(32),
    }
    original_stdin = sys.stdin
    browser, demo_browser, public_browser, operator_browser = (
        Browser(),
        Browser(),
        Browser(),
        Browser(),
    )
    try:
        try:
            sys.stdin = io.StringIO(json.dumps(passwords))
            call_command(
                "bootstrap_product_access",
                admin_username=admin_name,
                demo_username=demo_name,
                demo_slug="qa-product-" + suffix,
                credentials_stdin=True,
                stdout=io.StringIO(),
            )
        finally:
            sys.stdin = original_stdin
        campaign = Campaign.objects.get(tenant__slug="qa-product-" + suffix)
        before = usage_snapshot(7, [campaign.tenant])
        assert public_browser.request("/produto/")[0] == 200
        login(browser, admin_name, passwords["admin_password"])
        login(demo_browser, demo_name, passwords["demo_password"])
        assert browser.request("/")[:2] == (302, "/plataforma/")
        assert browser.request("/plataforma/")[0] == 200
        assert browser.request("/admin/")[0] == 200
        assert browser.request("/plataforma/?days=30")[0] == 200
        assert browser.request("/plataforma/atividade/?category=platform")[0] == 200
        assert browser.request("/plataforma/usuarios/novo/")[0] == 200
        assert demo_browser.request("/plataforma/")[0] == 403
        assert demo_browser.request("/admin/")[0] == 403
        assert demo_browser.request("/plataforma/atividade/")[0] == 403
        assert demo_browser.request("/plataforma/usuarios/novo/")[0] == 403
        status, _, content = demo_browser.request(f"/c/{campaign.pk}/")
        assert status == 200 and "Dados fictícios".encode() in content
        for page in ("mapa/", "equipe/", "relatorios/", "auditoria/"):
            assert demo_browser.request(f"/c/{campaign.pk}/" + page)[0] == 200
        after = usage_snapshot(7, [campaign.tenant])
        assert before["available"] and after["available"]
        assert after["landing"] > before["landing"]
        assert after["tenants"][0]["views"] >= before["tenants"][0]["views"] + 5
        role_id = Membership.objects.get(
            user__username=demo_name, campaign=campaign
        ).role_id
        operator_password = secrets.token_urlsafe(32)
        operator_payload = {
            "campaign": str(campaign.pk),
            "role": str(role_id),
            "username": operator_name,
            "password": operator_password,
        }
        assert (
            browser.request("/plataforma/usuarios/novo/", operator_payload, csrf=False)[
                0
            ]
            == 403
        )
        assert browser.request("/plataforma/usuarios/novo/", operator_payload)[:2] == (
            302,
            "/plataforma/",
        )
        login(operator_browser, operator_name, operator_password)
        assert operator_browser.request(f"/c/{campaign.pk}/")[0] == 200
        assert operator_browser.request("/plataforma/")[0] == 403
        operator = User.objects.get(username=operator_name)
        assert not operator.is_staff and not operator.is_superuser
        assert (
            browser.request(
                f"/plataforma/usuarios/{operator.pk}/status/", {"status": "active"}
            )[0]
            == 302
        )
        assert operator_browser.request(f"/c/{campaign.pk}/")[0] == 302
        assert browser.request("/plataforma/clientes/novo/")[0] == 200
        payload = {
            "organization": "QA cliente adicional",
            "slug": "qa-extra-" + suffix,
            "campaign_name": "QA adicional",
            "username": third_name,
            "password": secrets.token_urlsafe(32),
            "election_id": "QA",
            "office_code": "test",
            "jurisdiction_code": "DEMO",
            "is_demo": "on",
        }
        assert browser.request("/plataforma/clientes/novo/", payload)[:2] == (
            302,
            "/plataforma/",
        )
        other = Campaign.objects.get(tenant__slug=payload["slug"])
        assert demo_browser.request(f"/c/{other.pk}/")[0] == 404
        assert browser.request(f"/c/{other.pk}/")[0] == 404
        assert (
            browser.request(f"/plataforma/campanhas/{other.pk}/abrir/", {}, csrf=False)[
                0
            ]
            == 403
        )
        assert browser.request(f"/plataforma/campanhas/{other.pk}/abrir/", {})[:2] == (
            302,
            f"/c/{other.pk}/",
        )
        assert browser.request(f"/c/{other.pk}/")[0] == 200
        assert (
            browser.request(
                f"/plataforma/clientes/{other.tenant_id}/status/",
                {"status": "suspended"},
            )[0]
            == 302
        )
        assert browser.request(f"/c/{other.pk}/")[0] == 404
        assert (
            browser.request(
                f"/plataforma/clientes/{other.tenant_id}/status/", {"status": "active"}
            )[0]
            == 302
        )
        assert browser.request(f"/c/{other.pk}/")[0] == 200
        demo = User.objects.get(username=demo_name)
        assert (
            browser.request(
                f"/plataforma/usuarios/{demo.pk}/status/", {"status": "suspended"}
            )[0]
            == 302
        )
        assert demo_browser.request(f"/c/{campaign.pk}/")[0] == 302
        assert browser.request("/sair/", {})[0] == 302
        print(
            json.dumps(
                {
                    "platform_access_https": True,
                    "password_change_mfa": True,
                    "create_customer": True,
                    "create_scoped_user_and_revoke_sessions": True,
                    "aggregate_landing_and_customer_metrics": True,
                    "activity_access_restriction": True,
                    "cross_campaign_denied": True,
                    "explicit_admin_access_audited": True,
                    "session_revocation": True,
                    "requests": browser.requests
                    + demo_browser.requests
                    + public_browser.requests
                    + operator_browser.requests,
                }
            ),
            flush=True,
        )
    finally:
        # Retain evidence; only deactivate the exact synthetic accounts of this run.
        User.objects.filter(
            username__in=[admin_name, demo_name, third_name, operator_name]
        ).update(is_active=False)
        Tenant.objects.filter(
            slug__in=["qa-product-" + suffix, "qa-extra-" + suffix]
        ).update(status="suspended")


if __name__ == "__main__":
    main()
