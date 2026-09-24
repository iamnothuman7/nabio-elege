from datetime import date, datetime
from decimal import Decimal

from django import template
from django.utils import timezone
from django.utils.html import format_html

from apps.workspace.registry import LABELS

register = template.Library()


@register.simple_tag
def nav_icon(name):
    from apps.workspace.navigation_icons import ALIASES, PATHS

    path = PATHS.get(ALIASES.get(name, name), PATHS["grid"])
    return format_html(
        '<svg class="nav-icon" width="20" height="20" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="{}"/></svg>',
        path,
    )


@register.filter
def field_label(name):
    label = LABELS.get(name, name.replace("_", " ").capitalize())
    return label.replace(" (centavos)", "") if "cents" in name else label


@register.filter
def cell(obj, name):
    if obj._meta.model_name == "electorregistration" and name == "person":
        from apps.core.crypto import decrypt_json
        return decrypt_json(obj.person.display_name_ciphertext).get("value", "Cadastro voluntário")
    display = getattr(obj, f"get_{name}_display", None)
    if display:
        return display()
    value = getattr(obj, name, None)
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Sim" if value else "Não"
    if "cents" in name:
        return "R$ " + f"{Decimal(value) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime("%d/%m/%Y %H:%M") if timezone.is_aware(value) else value.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


@register.filter
def group_active(group, key):
    return any(module.key == key for module in group["modules"])


@register.filter
def has_permission(permissions, code):
    return code in permissions
