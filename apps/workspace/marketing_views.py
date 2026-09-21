from django.conf import settings
from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def landing(request):
    return render(
        request,
        "workspace/landing.html",
        {"local_demo": getattr(settings, "LOCAL_DEMO", False)},
    )


@require_GET
def access_help(request):
    return render(request, "workspace/access_help.html")
