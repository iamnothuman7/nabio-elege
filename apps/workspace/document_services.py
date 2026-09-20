import hashlib
import socket
import struct
import uuid

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import FileSystemStorage
from django.db import transaction

from apps.campaigns.services import require_campaign_permission
from apps.core.models import Document, DocumentVersion
from .services import audit


def private_storage():
    return FileSystemStorage(location=settings.MEDIA_ROOT / "private")


def require_document_access(actor, document):
    require_campaign_permission(actor, document.campaign, "documents.download.resource")
    if document.classification != "internal":
        require_campaign_permission(actor, document.campaign, f"documents.read_{document.classification}.campaign")


def scan_stream(file):
    if not settings.CLAMAV_HOST:
        return "pending"
    try:
        with socket.create_connection((settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=8) as connection:
            connection.sendall(b"zINSTREAM\0")
            file.seek(0)
            for chunk in iter(lambda: file.read(65536), b""):
                connection.sendall(struct.pack("!I", len(chunk)) + chunk)
            connection.sendall(struct.pack("!I", 0))
            reply = bytearray()
            while len(reply) < 4096:
                chunk = connection.recv(1024)
                if not chunk:
                    break
                reply.extend(chunk)
                if b"\0" in reply:
                    break
            result = bytes(reply).rstrip(b"\0\n")
            if result == b"stream: OK":
                return "clean"
            if result.endswith(b" FOUND"):
                return "rejected"
            return "error"
    except (OSError, TimeoutError):
        return "error"
    finally:
        file.seek(0)


def upload_document(actor, document, uploaded):
    require_campaign_permission(actor, document.campaign, "documents.create.campaign")
    if document.classification != "internal":
        require_campaign_permission(actor, document.campaign, f"documents.read_{document.classification}.campaign")
    if not uploaded or not 0 < uploaded.size <= 20 * 1024 * 1024:
        raise ValidationError("Envie um PDF, PNG ou JPEG com até 20 MB.")
    header = uploaded.read(16)
    uploaded.seek(0)
    if header.startswith(b"%PDF-"):
        media_type = "application/pdf"
    elif header.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type = "image/png"
    elif header.startswith(b"\xff\xd8\xff"):
        media_type = "image/jpeg"
    else:
        raise ValidationError("O conteúdo não corresponde a um tipo permitido.")
    digest = hashlib.sha256()
    for chunk in uploaded.chunks():
        digest.update(chunk)
    uploaded.seek(0)
    scan = scan_stream(uploaded)
    storage = private_storage()
    key = f"{document.campaign_id}/{uuid.uuid4().hex}"
    saved = storage.save(key, uploaded)
    try:
        document.status = "available" if scan == "clean" else "rejected" if scan == "rejected" else "quarantined"
        document.save()
        version = DocumentVersion.objects.create(document=document, version_number=1, storage_key=saved, sha256=digest.hexdigest(), media_type=media_type, size_bytes=uploaded.size, scan_status=scan, uploaded_by=actor)
        audit(actor, document, "document.uploaded", scan_status=scan)
        return version
    except Exception:
        storage.delete(saved)
        raise


@transaction.atomic
def rescan_document(actor, document):
    require_document_access(actor, document)
    document = Document.objects.select_for_update().get(pk=document.pk)
    version = document.versions.order_by("-version_number").first()
    if not version or document.status not in {"quarantined", "rejected"}:
        raise ValidationError("O documento não está aguardando análise.")
    with private_storage().open(version.storage_key, "rb") as file:
        version.scan_status = scan_stream(file)
    version.save(update_fields=["scan_status", "updated_at"])
    document.status = "available" if version.scan_status == "clean" else "rejected" if version.scan_status == "rejected" else "quarantined"
    document.save()
    audit(actor, document, "document.rescanned", scan_status=version.scan_status)
    return version.scan_status
