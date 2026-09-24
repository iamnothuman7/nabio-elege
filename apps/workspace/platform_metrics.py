"""Best-effort, short-lived operational counts. No visitor identities or URLs.

Redis already belongs to this deployment. Counters are not billing records,
unique people or a durable audit log; they expire and may be lost on eviction.
"""

from datetime import timedelta
import logging

from django.core.cache import cache
from django.utils import timezone

from apps.core.rls import current_scope

logger = logging.getLogger(__name__)
PREFIX = "platform-usage:v1:"
RETENTION = 35 * 86400


def counter_key(day, audience):
    return f"{PREFIX}{day.isoformat()}:{audience}"


def increment(key):
    if not cache.add(key, 1, timeout=RETENTION):
        try:
            cache.incr(key)
        except ValueError:
            # An expired/evicted bucket may disappear between add and incr.
            if not cache.add(key, 1, timeout=RETENTION):
                cache.incr(key)


def record_page_view(request, response):
    if (
        request.method != "GET"
        or response.status_code != 200
        or getattr(response, "streaming", False)
        or not response.get("Content-Type", "").startswith("text/html")
        or request.headers.get("DNT") == "1"
        or request.headers.get("Sec-GPC") == "1"
        or request.headers.get("Purpose") == "prefetch"
        or "prefetch" in request.headers.get("Sec-Purpose", "")
    ):
        return
    user = request.user
    if user.is_authenticated and (user.is_staff or user.is_superuser):
        return  # Administrative inspections do not inflate customer usage.
    match = getattr(request, "resolver_match", None)
    if not match:
        return
    buckets = []
    if match.url_name in {"home", "product_landing"} and not user.is_authenticated:
        buckets = ["landing"]
    elif user.is_authenticated and request.path.startswith("/c/"):
        scope = current_scope()  # Authorized server-side scope, never a header.
        if scope.tenant_id and scope.campaign_id:
            buckets = ["workspace", "tenant:" + scope.tenant_id]
    if not buckets:
        return
    try:
        day = timezone.localdate()
        cache.add(PREFIX + "started", day.isoformat(), timeout=RETENTION)
        for audience in buckets:
            increment(counter_key(day, audience))
    except Exception:
        # Metrics must never turn a successful page into a server error.
        logger.warning("Operational page counters unavailable")


def usage_snapshot(days, tenants):
    days = 30 if days == 30 else 7
    dates = [timezone.localdate() - timedelta(days=n) for n in reversed(range(days))]
    tenant_ids = [str(tenant.pk) for tenant in tenants]
    audiences = ["landing", "workspace", *["tenant:" + pk for pk in tenant_ids]]
    keys = [counter_key(day, audience) for day in dates for audience in audiences]
    try:
        values = cache.get_many([PREFIX + "started", *keys])
    except Exception:
        return {"available": False, "days": days}

    def number(day, audience):
        return max(0, int(values.get(counter_key(day, audience), 0)))

    rows = [
        {
            "date": day,
            "landing": number(day, "landing"),
            "workspace": number(day, "workspace"),
        }
        for day in dates
    ]
    return {
        "available": True,
        "days": days,
        "started": values.get(PREFIX + "started"),
        "landing": sum(row["landing"] for row in rows),
        "workspace": sum(row["workspace"] for row in rows),
        "peak": max([1, *[max(row["landing"], row["workspace"]) for row in rows]]),
        "rows": rows,
        "tenants": [
            {
                "tenant": tenant,
                "views": sum(number(day, "tenant:" + str(tenant.pk)) for day in dates),
            }
            for tenant in tenants
        ],
    }
