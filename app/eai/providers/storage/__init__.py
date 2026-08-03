"""Object storage factory (spec §6)."""

from __future__ import annotations

from ... import config
from .base import LocalObjectStore, ObjectStore  # noqa: F401


def get_object_store(name: str | None = None) -> ObjectStore:
    name = name or config.provider_name("storage")
    if name == "local":
        return LocalObjectStore()
    if name == "s3":  # pragma: no cover - prod slot
        raise NotImplementedError("S3ObjectStore is a later-phase slot")
    raise ValueError(f"Unknown storage provider: {name}")
