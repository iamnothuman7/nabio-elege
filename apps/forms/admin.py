from django.contrib import admin

from .models import (
    ContactPoint,
    Form,
    FormVersion,
    Manifestation,
    Person,
    PrivacyNoticeVersion,
    PrivacyRequest,
    ProcessingPurpose,
    ServiceRequest,
    SourceLink,
    Submission,
    Suppression,
)


admin.site.register(
    [
        ProcessingPurpose,
        PrivacyNoticeVersion,
        Form,
        FormVersion,
        SourceLink,
        Submission,
        Person,
        ContactPoint,
        Manifestation,
        Suppression,
        ServiceRequest,
        PrivacyRequest,
    ]
)
