import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.debug import sensitive_post_parameters

from apps.campaigns.models import Membership
from apps.core.crypto import decrypt_json, encrypt_json, hash_token
from apps.core.client_address import client_address
from apps.core.services import append_audit_event
from .models import Invitation, LoginGuard, SecurityProfile
from .security import new_totp_secret, verify_second_factor


@sensitive_post_parameters("password")
@require_http_methods(["GET", "POST"])
def login_view(request):
    error = ""
    username = ""
    if request.method == "POST":
        username = request.POST.get("username", "")[:150]
        password = request.POST.get("password", "")
        keys = [salted_hmac("login", "account:" + username.casefold()).hexdigest(), salted_hmac("login", "ip:" + client_address(request)).hexdigest()]
        with transaction.atomic():
            guards = [LoginGuard.objects.select_for_update().get_or_create(key=key)[0] for key in sorted(keys)]
            blocked = any(g.locked_until and g.locked_until > timezone.now() for g in guards)
            user = None if blocked or len(password) > 1024 else authenticate(request, username=username, password=password)
            if user is not None:
                for guard in guards:
                    guard.failures = 0
                    guard.locked_until = None
                    guard.save()
                login(request, user)
                profile, _ = SecurityProfile.objects.get_or_create(user=user)
                request.session["security_version"] = profile.session_version
                if profile.password_change_required:
                    return redirect("password_change")
                return redirect("security" if settings.MFA_REQUIRED or profile.enabled_at else "home")
            if not blocked:
                for guard in guards:
                    guard.failures += 1
                    if guard.failures >= 5:
                        guard.locked_until = timezone.now() + timedelta(minutes=15)
                        guard.failures = 0
                    guard.save()
        error = "Não foi possível entrar. Confira seus dados ou aguarde 15 minutos se houve várias tentativas."
    return render(request, "workspace/login.html", {"error": error, "username": username, "local_demo": getattr(settings, "LOCAL_DEMO", False)})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
@sensitive_post_parameters("code")
def security_view(request):
    profile, _ = SecurityProfile.objects.get_or_create(user=request.user)
    if not profile.totp_secret_ciphertext:
        profile.totp_secret_ciphertext = encrypt_json({"secret": new_totp_secret()})
        profile.save()
    error = ""
    codes = []
    if request.method == "POST":
        if verify_second_factor(request.user, request.POST.get("code", "")):
            with transaction.atomic():
                profile = SecurityProfile.objects.select_for_update().get(user=request.user)
                if not profile.enabled_at:
                    profile.enabled_at = timezone.now()
                    codes = [secrets.token_hex(8) for _ in range(8)]
                    profile.recovery_hashes = [hash_token(code) for code in codes]
                if request.POST.get("action") == "revoke_sessions":
                    profile.session_version += 1
                profile.save()
            request.session.cycle_key()
            request.session["mfa_version"] = profile.session_version
            request.session["security_version"] = profile.session_version
            append_audit_event(actor=request.user, action="security.mfa_verified", resource_type="user", resource_id=request.user.pk)
            if not codes:
                messages.success(request, "Autenticação confirmada. As sessões foram atualizadas.")
                return redirect("home")
        else:
            error = "Código inválido, já utilizado ou temporariamente bloqueado."
    secret = decrypt_json(profile.totp_secret_ciphertext)["secret"] if not profile.enabled_at else ""
    return render(request, "workspace/security.html", {"secret": secret, "codes": codes, "error": error, "enabled": bool(profile.enabled_at)})


@sensitive_post_parameters("password", "token")
def accept_invitation(request):
    error = ""
    if request.method == "POST":
        try:
            with transaction.atomic():
                invitation = Invitation.objects.select_for_update().filter(token_hash=hash_token(request.POST.get("token", "").strip())).first()
                if not invitation or invitation.accepted_at or invitation.revoked_at or invitation.expires_at <= timezone.now() or invitation.tenant.status != "active":
                    raise ValidationError("Convite inválido ou expirado.")
                user = User.objects.filter(username=invitation.username).first()
                if user:
                    if not request.user.is_authenticated or request.user.pk != user.pk:
                        raise ValidationError("Este convite é para uma conta existente. Entre nessa conta antes de aceitar.")
                else:
                    user = User(username=invitation.username)
                    password = request.POST.get("password", "")
                    if len(password) > 1024:
                        raise ValidationError("A senha deve ter no máximo 1024 caracteres.")
                    validate_password(password, user)
                    user.set_password(password)
                    user.save()
                Membership.objects.update_or_create(user=user, campaign=invitation.campaign, defaults={"tenant": invitation.tenant, "role": invitation.role, "status": "active", "revoked_at": None, "expires_at": None, "invited_by": invitation.created_by})
                invitation.accepted_at = timezone.now()
                invitation.save()
                append_audit_event(actor=user, tenant=invitation.tenant, campaign=invitation.campaign, action="membership.invitation_accepted", resource_type="invitation", resource_id=invitation.pk)
            messages.success(request, "Convite aceito. Entre com sua conta para continuar.")
            return redirect("home" if request.user.is_authenticated else "login")
        except ValidationError as exc:
            error = " ".join(exc.messages)
    return render(request, "workspace/invitation.html", {"error": error})


@login_required
@sensitive_post_parameters("old_password", "new_password1", "new_password2", "second_factor")
def password_change(request):
    from .account_forms import SecurePasswordChangeForm

    profile, _ = SecurityProfile.objects.get_or_create(user=request.user)
    form = SecurePasswordChangeForm(request.user, mfa_enabled=bool(profile.enabled_at))
    changed = False
    if request.method == "POST":
        # Serialize password changes against the current stored password, not a
        # stale request.user. Failed attempts must commit their guard counters.
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            profile = SecurityProfile.objects.select_for_update().get(user=user)
            key = salted_hmac("password-change", str(user.pk)).hexdigest()
            guard, _ = LoginGuard.objects.select_for_update().get_or_create(key=key)
            form = SecurePasswordChangeForm(user, request.POST, mfa_enabled=bool(profile.enabled_at))
            if guard.locked_until and guard.locked_until > timezone.now():
                form.add_error(None, "Muitas tentativas. Aguarde 15 minutos.")
            elif form.is_valid():
                if profile.enabled_at and not verify_second_factor(user, form.cleaned_data["second_factor"]):
                    form.add_error("second_factor", "Código inválido, utilizado ou temporariamente bloqueado.")
                else:
                    form.save()
                    # verify_second_factor updates the same profile; save only
                    # the password/session fields so recovery counters survive.
                    profile.password_change_required = False
                    profile.password_changed_at = timezone.now()
                    profile.session_version += 1
                    profile.save(update_fields=["password_change_required", "password_changed_at", "session_version"])
                    append_audit_event(actor=user, action="security.password_changed", resource_type="user", resource_id=user.pk)
                    changed = True
            if changed:
                guard.failures = 0
                guard.locked_until = None
            elif not (guard.locked_until and guard.locked_until > timezone.now()):
                guard.failures += 1
                if guard.failures >= 5:
                    guard.failures = 0
                    guard.locked_until = timezone.now() + timedelta(minutes=15)
            guard.save()
        if changed:
            update_session_auth_hash(request, user)
            request.session["security_version"] = profile.session_version
            if profile.enabled_at:
                request.session["mfa_version"] = profile.session_version
            else:
                request.session.pop("mfa_version", None)
            messages.success(request, "Senha alterada. As outras sessões foram encerradas.")
            return redirect("security" if settings.MFA_REQUIRED and not profile.enabled_at else "home")
    return render(request, "workspace/password_change.html", {"form": form, "required": profile.password_change_required})
