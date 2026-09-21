"""Read-only operational checks, run by ops, never exposed as public diagnostics."""
import socket

import redis
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from apps.core.rls import verify_database_isolation


class Command(BaseCommand):
    help = "Verifica banco, migrações, cache, fila e antivírus sem imprimir credenciais."

    def handle(self, *args, **options):
        checks = {
            "database": self.database,
            "migrations": self.migrations,
            "isolation": verify_database_isolation,
            "cache": lambda: self.redis_ping(settings.CACHES["default"].get("LOCATION", "")),
            "broker": lambda: self.redis_ping(settings.CELERY_BROKER_URL),
            "antivirus": self.antivirus,
        }
        failures = []
        for name, operation in checks.items():
            try:
                if operation() is not True:
                    raise ValueError("not ready")
                self.stdout.write(f"{name}: OK")
            except Exception:
                # Provider errors may contain full connection URLs or credentials.
                failures.append(name)
                self.stdout.write(f"{name}: INDISPONÍVEL")
        if failures:
            raise CommandError("Dependências não prontas: " + ", ".join(failures))
        self.stdout.write(self.style.SUCCESS("Dependências respondendo. Isto não certifica segurança, backup ou worker ativo."))

    @staticmethod
    def database():
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)

    @staticmethod
    def migrations():
        executor = MigrationExecutor(connection)
        return not executor.migration_plan(executor.loader.graph.leaf_nodes())

    @staticmethod
    def redis_ping(url):
        if not isinstance(url, str) or not url.startswith(("redis://", "rediss://")):
            return False
        client = redis.Redis.from_url(url, socket_connect_timeout=3, socket_timeout=3)
        try:
            return client.ping()
        finally:
            client.close()

    @staticmethod
    def antivirus():
        if not settings.CLAMAV_HOST:
            return False
        with socket.create_connection((settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=3) as sock:
            sock.sendall(b"zPING\0")
            return sock.recv(64).rstrip(b"\0\n") == b"PONG"
