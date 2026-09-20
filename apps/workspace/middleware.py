from django.conf import settings
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from django.core.cache import cache
from django.utils.crypto import salted_hmac
import time

from .models import SecurityProfile


class AccessSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and (request.path.startswith("/f/") or request.path.startswith("/api/v1/public/")):
            key = "public-rate:" + salted_hmac("public-rate", request.META.get("REMOTE_ADDR", "")).hexdigest() + ":" + str(int(time.time()) // 60)
            cache.add(key, 0, timeout=90)
            try:
                attempts = cache.incr(key)
            except ValueError:
                attempts = 1
                cache.set(key, attempts, timeout=90)
            if attempts > 30:
                response = JsonResponse({"detail": "Muitos envios. Aguarde um minuto e tente novamente."}, status=429)
                response["Retry-After"] = "60"
                return response
        if request.user.is_authenticated:
            profile, _ = SecurityProfile.objects.get_or_create(user=request.user)
            stamp = request.session.get("security_version", profile.session_version)
            if stamp != profile.session_version or not request.user.is_active:
                logout(request)
                return redirect("login")
            exempt = request.path in {"/seguranca/", "/sair/", "/entrar/"} or request.path.startswith("/f/") or request.path.startswith("/api/v1/public/") or request.path == "/api/healthz"
            if (settings.MFA_REQUIRED or profile.enabled_at) and not exempt:
                if not profile.enabled_at or request.session.get("mfa_version") != profile.session_version:
                    if request.path.startswith("/api/"):
                        return JsonResponse({"code": "mfa_required", "detail": "Conclua a autenticação em dois fatores."}, status=403)
                    return redirect("security")
        response = self.get_response(request)
        response["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'; object-src 'none'"
        if getattr(request, "maps_enabled", False):
            response["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://unpkg.com; style-src 'self' https://unpkg.com; style-src-attr 'unsafe-inline'; img-src 'self' data: https://tile.openstreetmap.org; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'; object-src 'none'"
            response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not request.path.startswith("/static/"):
            response["Cache-Control"] = "no-store"
        return response
