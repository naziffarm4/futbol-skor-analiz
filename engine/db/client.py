"""Supabase istemci bağlantı yöneticisi ve hata yakalama katmanı."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import httpx
from postgrest.exceptions import APIError
from supabase import Client, ClientOptions, create_client

from engine.config import Settings, settings

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Tüm veritabanı katmanı hataları için temel istisna sınıfı."""


class DatabaseConfigError(DatabaseError):
    """Eksik veya geçersiz Supabase bağlantı yapılandırması hatası."""


class DatabaseConnectionError(DatabaseError):
    """Supabase istemci başlatma veya ağ erişim hatası."""


class DatabaseOperationError(DatabaseError):
    """PostgREST sorgu yürütme veya veri kısıtı hatası."""


_clients: dict[bool, Client] = {}


def _validate_credentials(cfg: Settings, use_service_role: bool) -> tuple[str, str]:
    url = cfg.supabase_url
    key = cfg.resolve_api_key(use_service_role=use_service_role)

    if not url or "your-project-ref" in url:
        raise DatabaseConfigError(
            "SUPABASE_URL tanımlı değil veya örnek değer içeriyor. Lütfen .env dosyasını yapılandırın."
        )

    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise DatabaseConfigError(f"Geçersiz SUPABASE_URL formatı: {url!r}")

    if not key or key.startswith("your-supabase-"):
        raise DatabaseConfigError(
            "SUPABASE_KEY / SUPABASE_SERVICE_ROLE_KEY tanımlı değil. Lütfen .env dosyasını yapılandırın."
        )

    return url, key


def get_supabase_client(
    *,
    use_service_role: bool = False,
    force_refresh: bool = False,
    cfg: Settings | None = None,
) -> Client:
    """Önbellekli Supabase istemcisi döndürür; yapılandırma ve başlatma hatalarını yakalar."""
    if cfg is None and not force_refresh and use_service_role in _clients:
        return _clients[use_service_role]

    active_cfg = cfg or (Settings.from_env() if force_refresh else settings)
    url, key = _validate_credentials(active_cfg, use_service_role=use_service_role)

    try:
        options = ClientOptions(postgrest_client_timeout=active_cfg.http_timeout_seconds)
        client = create_client(url, key, options=options)
    except DatabaseError:
        raise
    except Exception as exc:
        logger.exception("Supabase istemcisi başlatılamadı.")
        raise DatabaseConnectionError(f"Supabase istemcisi oluşturulamadı: {exc}") from exc

    if cfg is None:
        _clients[use_service_role] = client
    return client


def reset_clients() -> None:
    """Önbellekteki Supabase istemcilerini temizler."""
    _clients.clear()


def execute_query(operation: Callable[[], Any], *, context: str = "query") -> Any:
    """PostgREST / Supabase sorgularını çalıştırır ve ağ/API hatalarını standart istisnalara dönüştürür."""
    try:
        return operation()
    except APIError as exc:
        logger.error("Supabase API hatası (%s): %s", context, exc)
        raise DatabaseOperationError(f"Veritabanı sorgu hatası ({context}): {exc.message}") from exc
    except httpx.HTTPError as exc:
        logger.error("Supabase ağ hatası (%s): %s", context, exc)
        raise DatabaseConnectionError(f"Supabase bağlantı/zaman aşımı hatası ({context}): {exc}") from exc
    except DatabaseError:
        raise
    except Exception as exc:
        logger.exception("Beklenmeyen veritabanı hatası (%s).", context)
        raise DatabaseOperationError(f"Beklenmeyen veritabanı hatası ({context}): {exc}") from exc
