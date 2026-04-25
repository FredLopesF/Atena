"""Adapter package — exports factory and Protocol."""

from src.adapters.archive_org import ArchiveOrgAdapter
from src.adapters.archive_org_zip import ArchiveOrgZipAdapter
from src.adapters.base import SourceAdapter
from src.adapters.direct_url import DirectUrlAdapter
from src.core.models import Console


def create_adapter(console: Console) -> SourceAdapter:
    """Return the correct adapter instance for *console*."""
    if console.type == "archive_org":
        if not console.identifier:
            raise ValueError(
                f"Console '{console.name}' has type 'archive_org' but no identifier."
            )
        return ArchiveOrgAdapter(
            identifier=console.identifier,
            extensions=console.extensions or None,
            auth_email=console.auth_email,
            auth_password=console.auth_password,
        )
    if console.type == "direct_url":
        if not console.url:
            raise ValueError(
                f"Console '{console.name}' has type 'direct_url' but no url."
            )
        return DirectUrlAdapter(base_url=console.url)
    if console.type == "archive_org_zip":
        if not console.url:
            raise ValueError(
                f"Console '{console.name}' has type 'archive_org_zip' but no url."
            )
        return ArchiveOrgZipAdapter(
            base_url=console.url,
            auth_email=console.auth_email,
            auth_password=console.auth_password,
        )
    raise ValueError(f"Unknown console type: '{console.type}'")


__all__ = ["SourceAdapter", "ArchiveOrgAdapter", "DirectUrlAdapter", "ArchiveOrgZipAdapter", "create_adapter"]
