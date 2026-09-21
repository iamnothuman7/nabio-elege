"""Manage only the new Nabio virtual host; never use certbot --nginx."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys

from first_install import DOMAIN, assert_baseline, run, utc, write_new

STAGING = Path("/var/www/apps/nabio-elege-staging")
PRODUCTION = Path("/var/www/apps/nabio-elege")
SITE = Path("/etc/nginx/sites-available") / DOMAIN
LINK = Path("/etc/nginx/sites-enabled") / DOMAIN
MARKER = "# Managed exclusively for Nabio Elege\n"
STATE = STAGING / "shared/tls-state.json"


def proxy(root, port):
    return f"""
    client_max_body_size 22m;
    access_log /var/log/nginx/nabio-elege-access.log nabio_elege_minimal;
    error_log /var/log/nginx/nabio-elege-error.log warn;
    location /static/ {{ alias {root}/shared/staticfiles/; add_header X-Content-Type-Options nosniff always; }}
    location /media/ {{ return 404; }}
    location ~ /\\. {{ deny all; }}
    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host "";
        proxy_set_header Forwarded "";
        proxy_connect_timeout 3s;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
        limit_req zone=nabio_elege_requests burst=80 nodelay;
        limit_req_status 429;
    }}
"""


def config(tls=False, public=False):
    body = (
        MARKER
        + """log_format nabio_elege_minimal '$time_iso8601 $request_id $request_method $status $body_bytes_sent $request_time';
limit_req_zone $binary_remote_addr zone=nabio_elege_requests:10m rate=40r/s;
"""
    )
    body += f"""server {{
    listen 80;
    listen [::]:80;
    server_name {DOMAIN};
    access_log off;
    location ^~ /.well-known/acme-challenge/ {{ root {STAGING}/shared/acme; default_type text/plain; }}
    location / {{ {"return 301 https://" + DOMAIN + "$request_uri;" if tls else "return 503;"} }}
}}
"""
    if tls:
        certificate = f"""ssl_certificate /etc/letsencrypt/live/{DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:NabioElegeTLS:1m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;"""
        body += f"""server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {DOMAIN};
    {certificate}
    {proxy(PRODUCTION, 8090) if public else "location / { return 503; }"}
}}
server {{
    listen 127.0.0.1:8449 ssl;
    server_name {DOMAIN};
    {certificate}
    {proxy(STAGING, 8091)}
}}
"""
    return body


def install(tls=False, public=False):
    assert_baseline(STAGING)
    before = None
    if SITE.exists():
        if not STATE.exists() or not SITE.read_text().startswith(MARKER):
            raise RuntimeError("Unknown existing virtual host; refusing overwrite")
        state = json.loads(STATE.read_text())
        if hashlib.sha256(SITE.read_bytes()).hexdigest() != state["sha256"]:
            raise RuntimeError("Virtual host changed outside this deployment")
        before = SITE.read_text()
        write_new(STAGING / f"shared/backups/nginx-{utc()}.conf", before)
    elif LINK.exists() or LINK.is_symlink():
        raise RuntimeError("Existing nginx link")
    content = config(tls, public)
    temporary = SITE.with_name(DOMAIN + ".pending")
    write_new(temporary, content, 0o644)
    temporary.replace(SITE)
    if not LINK.exists():
        LINK.symlink_to(SITE)
    try:
        run(["nginx", "-t"])
    except Exception:
        if before is not None:
            SITE.write_text(before)
        else:
            LINK.unlink()  # Only the just-created, exact Nabio link.
        raise
    STATE.write_text(
        json.dumps(
            {
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "utc": utc(),
                "tls": tls,
                "public": public,
            }
        )
    )
    STATE.chmod(0o600)
    run(["systemctl", "reload", "nginx"])
    assert_baseline(STAGING)
    print("NABIO_VHOST_ACTIVE", {"tls": tls, "public": public}, flush=True)


def certificate(dry_run=False):
    accounts = list(
        Path("/etc/letsencrypt/accounts/acme-v02.api.letsencrypt.org/directory").glob(
            "*/regr.json"
        )
    )
    if len(accounts) != 1:
        raise RuntimeError("Select authorized production ACME registration explicitly")
    args = [
        "certbot",
        "certonly",
        "--non-interactive",
        "--webroot",
        "-w",
        str(STAGING / "shared/acme"),
        "--cert-name",
        DOMAIN,
        "-d",
        DOMAIN,
        "--account",
        accounts[0].parent.name,
        "--no-directory-hooks",
        "--deploy-hook",
        "/usr/sbin/nginx -t && /bin/systemctl reload nginx",
    ]
    if dry_run:
        args = [
            "certbot",
            "renew",
            "--cert-name",
            DOMAIN,
            "--dry-run",
            "--no-directory-hooks",
        ]
    print(run(args), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("challenge", "certificate", "staging", "publish", "renew-test"),
    )
    action = parser.parse_args().action
    try:
        if action == "challenge":
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 8449))
            install()
        elif action == "certificate":
            certificate()
        elif action == "renew-test":
            certificate(True)
        elif action == "staging":
            install(tls=True)
        elif action == "publish":
            for root in (STAGING, PRODUCTION):
                if not (root / "shared/validation-passed.json").exists():
                    raise RuntimeError(
                        "Runtime, restore and staging gates must be recorded first"
                    )
            install(tls=True, public=True)
    except Exception as exc:
        print(f"STOPPED: {exc}", file=sys.stderr)
        sys.exit(1)
