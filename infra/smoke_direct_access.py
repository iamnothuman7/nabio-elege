"""HTTPS rehearsal of owner-authorized direct access; synthetic staging only."""

import io
import json
import secrets
import sys
import uuid

from smoke_staging import (
    Browser,
    Campaign,
    SecurityProfile,
    Tenant,
    User,
    call_command,
    settings,
)
from apps.campaigns.models import Membership
from apps.core.rls import database_scope
from apps.workspace.models import FieldWorker
from apps.workspace.security import requires_second_factor


def main():
    if settings.APP_ENV != "staging" or settings.DEBUG or settings.LOCAL_DEMO:
        raise RuntimeError("Synthetic staging only")
    suffix = uuid.uuid4().hex[:10]
    admin, demo, real = (
        "qa.direct." + prefix + suffix for prefix in ("admin", "demo", "real")
    )
    demo_slug, real_slug = "qa-direct-demo-" + suffix, "qa-direct-real-" + suffix
    initial = {
        "admin_password": secrets.token_urlsafe(24),
        "demo_password": secrets.token_urlsafe(24),
    }
    passwords = {
        "admin_password": secrets.token_urlsafe(24),
        "customer_password": secrets.token_urlsafe(24),
    }
    owner_browser, customer_browser = Browser(), Browser()
    old_stdin = sys.stdin
    try:
        sys.stdin = io.StringIO(json.dumps(initial))
        call_command(
            "bootstrap_product_access",
            admin_username=admin,
            demo_username=demo,
            demo_slug=demo_slug,
            credentials_stdin=True,
            stdout=io.StringIO(),
        )
        original = Campaign.objects.get(tenant__slug=demo_slug)
        sys.stdin = io.StringIO(json.dumps(passwords))
        call_command(
            "prepare_direct_access",
            admin_username=admin,
            customer_username=demo,
            new_customer_username=real,
            tenant_slug=real_slug,
            customer_name="Synthetic real customer",
            passwords_stdin=True,
            confirm_password_only=True,
            stdout=io.StringIO(),
        )
        campaign = Campaign.objects.get(tenant__slug=real_slug)
        assert not campaign.is_demo
        for browser, username, key, destination in (
            (owner_browser, admin, "admin_password", "/plataforma/"),
            (customer_browser, real, "customer_password", f"/c/{campaign.pk}/"),
        ):
            assert browser.request("/entrar/")[0] == 200
            assert (
                browser.request(
                    "/entrar/",
                    {"username": username, "password": passwords[key]},
                    csrf=False,
                )[0]
                == 403
            )
            assert browser.request(
                "/entrar/", {"username": username, "password": passwords[key]}
            )[:2] == (302, "/")
            assert browser.request("/")[:2] == (302, destination)
            assert browser.request(destination)[0] == 200
            profile = SecurityProfile.objects.get(user__username=username)
            assert not profile.password_change_required and not requires_second_factor(
                profile.user, profile
            )
            assert (
                browser.cookies["sessionid"]["secure"]
                and browser.cookies["sessionid"]["httponly"]
            )
        assert customer_browser.request("/plataforma/")[0] == 403
        assert customer_browser.request(f"/c/{original.pk}/")[0] == 404
        assert customer_browser.request("/api/v1/campaigns")[0] == 200
        assert customer_browser.request("/seguranca/")[0] == 200
        user = User.objects.get(username=real)
        with database_scope(campaign=campaign, actor=user):
            assert FieldWorker.objects.filter(campaign=campaign).count() == 0
        with database_scope(campaign=original, actor=user):
            assert FieldWorker.objects.filter(campaign=original).count() == 3
        assert Membership.objects.get(user=user, campaign=original).status == "revoked"
        assert not User.objects.filter(username=demo).exists()
        assert owner_browser.request("/plataforma/atividade/")[0] == 200
        for browser in (owner_browser, customer_browser):
            assert browser.request("/sair/", {})[0] == 302
        print(
            json.dumps(
                {
                    "password_only_https_login": True,
                    "csrf_and_roles_preserved": True,
                    "empty_real_customer": True,
                    "synthetic_history_preserved": True,
                    "requests": owner_browser.requests + customer_browser.requests,
                }
            ),
            flush=True,
        )
    finally:
        sys.stdin = old_stdin
        User.objects.filter(username__in=[admin, demo, real]).update(is_active=False)
        Tenant.objects.filter(slug__in=[demo_slug, real_slug]).update(
            status="suspended"
        )


if __name__ == "__main__":
    main()
