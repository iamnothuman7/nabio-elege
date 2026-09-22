from functools import wraps

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST, require_safe

from apps.campaigns.models import Campaign, Role, Tenant
from apps.core.models import AuditEvent
from .platform_metrics import usage_snapshot
from .platform_services import (
    create_customer,
    create_customer_access,
    open_campaign,
    require_platform_admin,
    set_tenant_status,
    set_user_status,
)


def platform_admin(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        require_platform_admin(request.user)
        return view(request, *args, **kwargs)

    return wrapper


class CustomerForm(forms.Form):
    organization = forms.CharField(label="Organização / cliente", max_length=180)
    slug = forms.SlugField(label="Identificador da organização", max_length=100)
    campaign_name = forms.CharField(label="Nome da campanha", max_length=180)
    election_id = forms.CharField(label="Eleição / ciclo", max_length=100)
    office_code = forms.CharField(label="Cargo", max_length=80)
    jurisdiction_code = forms.CharField(
        label="Abrangência / UF / município", max_length=100
    )
    username = forms.CharField(label="Usuário do gestor", max_length=150)
    password = forms.CharField(
        label="Senha inicial (mínimo 12 caracteres)",
        min_length=12,
        max_length=1024,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    is_demo = forms.BooleanField(
        label="Cliente de demonstração — somente dados fictícios", required=False
    )


class CampaignChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.tenant.name} · {obj.name}"


class CustomerAccessForm(forms.Form):
    campaign = CampaignChoice(
        label="Campanha do cliente",
        queryset=Campaign.objects.none(),
    )
    role = forms.ModelChoiceField(
        label="Papel de acesso na organização",
        queryset=Role.objects.none(),
        help_text="O papel deve pertencer à mesma organização da campanha.",
    )
    username = forms.CharField(label="Nome de usuário", max_length=150)
    password = forms.CharField(
        label="Senha inicial (mínimo 12 caracteres)",
        min_length=12,
        max_length=1024,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["campaign"].queryset = (
            Campaign.objects.filter(tenant__status="active")
            .exclude(phase="archived")
            .select_related("tenant")
            .order_by("tenant__name", "name")
        )
        self.fields["role"].queryset = (
            Role.objects.filter(tenant__status="active")
            .exclude(code="platform-operator")
            .select_related("tenant")
            .order_by("tenant__name", "name")
        )

    def clean(self):
        data = super().clean()
        campaign, role = data.get("campaign"), data.get("role")
        if campaign and role and campaign.tenant_id != role.tenant_id:
            self.add_error(
                "role", "O papel deve pertencer à organização da campanha selecionada."
            )
        return data


@platform_admin
@require_safe
def dashboard(request):
    query = request.GET.get("q", "").strip()[:100]
    tenants = Tenant.objects.annotate(
        campaign_count=Count("campaigns", distinct=True)
    ).order_by("name")
    campaigns = Campaign.objects.select_related("tenant").order_by(
        "tenant__name", "name"
    )
    users = User.objects.select_related("securityprofile").order_by("username")
    if query:
        tenants = tenants.filter(Q(name__icontains=query) | Q(slug__icontains=query))
        campaigns = campaigns.filter(
            Q(name__icontains=query) | Q(tenant__name__icontains=query)
        )
        users = users.filter(username__icontains=query)
    tenant_page = Paginator(tenants, 20).get_page(request.GET.get("tenants_page"))
    context = {
        "title": "Administração da plataforma",
        "query": query,
        "tenant_count": Tenant.objects.count(),
        "campaign_count": Campaign.objects.count(),
        "user_count": User.objects.count(),
        "active_user_count": User.objects.filter(is_active=True).count(),
        "tenants": tenant_page,
        "usage": usage_snapshot(
            30 if request.GET.get("days") == "30" else 7, list(tenant_page)
        ),
        "campaigns": Paginator(campaigns, 20).get_page(
            request.GET.get("campaigns_page")
        ),
        "accounts": Paginator(users, 20).get_page(request.GET.get("users_page")),
        "events": AuditEvent.objects.filter(
            actor=request.user, campaign__isnull=True, action__startswith="platform."
        ).order_by("-occurred_at")[:20],
    }
    return render(request, "workspace/platform.html", context)


@platform_admin
@sensitive_post_parameters("password")
def user_create(request):
    if request.method not in ("GET", "HEAD", "POST"):
        from django.http import HttpResponseNotAllowed

        return HttpResponseNotAllowed(["GET", "HEAD", "POST"])
    form = CustomerAccessForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            create_customer_access(actor=request.user, **form.cleaned_data)
        except (ValidationError, IntegrityError):
            form.add_error(
                None,
                "Confira a senha, o usuário e o papel de acesso. Nenhuma criação parcial foi mantida.",
            )
        else:
            messages.success(
                request,
                "Usuário criado sem privilégios de plataforma. Troca de senha inicial e MFA obrigatórios no primeiro acesso.",
            )
            return redirect("platform_dashboard")
    return render(
        request, "workspace/platform_user.html", {"title": "Novo usuário", "form": form}
    )


@platform_admin
@require_safe
def activity(request):
    category = request.GET.get("category", "")
    if category not in {"platform", "security"}:
        category = ""
    query = request.GET.get("q", "").strip()[:100]
    events = AuditEvent.objects.filter(actor=request.user, campaign__isnull=True)
    if category:
        events = events.filter(action__startswith=category + ".")
    if query:
        events = events.filter(
            Q(action__icontains=query) | Q(resource_type__icontains=query)
        )
    page = Paginator(events.order_by("-occurred_at", "-pk"), 50).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "workspace/platform_activity.html",
        {
            "title": "Registros de atividade",
            "events": page,
            "category": category,
            "query": query,
        },
    )


@platform_admin
@sensitive_post_parameters("password")
def customer_create(request):
    if request.method not in ("GET", "HEAD", "POST"):
        from django.http import HttpResponseNotAllowed

        return HttpResponseNotAllowed(["GET", "HEAD", "POST"])
    form = CustomerForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            create_customer(actor=request.user, **form.cleaned_data)
        except (ValidationError, IntegrityError):
            form.add_error(
                None,
                "Confira os dados, a força da senha e se os identificadores já existem. Nenhum cadastro parcial foi mantido.",
            )
        else:
            messages.success(
                request,
                "Cliente criado. O gestor deve trocar a senha inicial e configurar MFA no primeiro acesso.",
            )
            return redirect("platform_dashboard")
    return render(
        request,
        "workspace/platform_customer.html",
        {"title": "Novo cliente", "form": form},
    )


@platform_admin
@require_POST
def campaign_open(request, object_id):
    campaign = get_object_or_404(
        Campaign.objects.select_related("tenant"), pk=object_id
    )
    try:
        open_campaign(actor=request.user, campaign=campaign)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("platform_dashboard")
    destination = (
        "audit_log" if request.POST.get("destination") == "audit" else "dashboard"
    )
    return redirect(destination, campaign_id=campaign.pk)


@platform_admin
@require_POST
def tenant_status(request, object_id):
    tenant = get_object_or_404(Tenant, pk=object_id)
    try:
        set_tenant_status(
            actor=request.user, tenant=tenant, status=request.POST.get("status", "")
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Situação da organização atualizada.")
    return redirect("platform_dashboard")


@platform_admin
@require_POST
def user_status(request, object_id):
    user = get_object_or_404(User, pk=object_id)
    try:
        status = request.POST.get("status")
        if status not in ("active", "suspended"):
            raise ValidationError("Status inválido.")
        set_user_status(actor=request.user, user=user, active=status == "active")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Acesso atualizado e sessões anteriores revogadas.")
    return redirect("platform_dashboard")
