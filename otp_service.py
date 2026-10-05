"""
FastOTP Proxy & Live SMS Service for TeleCloud
Provides 24/7 background OTP API proxy, live stats, and Telegram bot integration.
"""

import os
import re
import logging
from typing import Optional, Dict, Any, List
import requests

logger = logging.getLogger("otp_service")

# Default credentials & endpoints
DEFAULT_PANEL_BASE_URL = os.environ.get(
    "PANEL_BASE_URL", 
    "https://fitting-along-bali-distributor.trycloudflare.com"
).rstrip("/")

DEFAULT_PANEL_API_KEY = os.environ.get(
    "PANEL_API_KEY", 
    "ak_ZndDBHCdhTdZGjAnHKL88anOujiqHF1G"
).strip()

# Guard against legacy broken URLs or invalid keys
if "jan-invalid-isle" in DEFAULT_PANEL_BASE_URL or not DEFAULT_PANEL_BASE_URL.startswith("http"):
    DEFAULT_PANEL_BASE_URL = "https://fitting-along-bali-distributor.trycloudflare.com"

if not DEFAULT_PANEL_API_KEY or "7EQtYszN8" in DEFAULT_PANEL_API_KEY:
    DEFAULT_PANEL_API_KEY = "ak_ZndDBHCdhTdZGjAnHKL88anOujiqHF1G"

_session = requests.Session()

def extract_api_key(
    req_key: Optional[str] = None, 
    header_key: Optional[str] = None, 
    auth_header: Optional[str] = None
) -> str:
    """Extract API key from query param, X-API-Key header, or Bearer auth header, falling back to default."""
    if req_key and req_key.strip():
        return req_key.strip()
    if header_key and header_key.strip():
        return header_key.strip()
    if auth_header and auth_header.strip():
        auth = auth_header.strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return auth
    return DEFAULT_PANEL_API_KEY

def extract_base_url(
    req_url: Optional[str] = None, 
    header_url: Optional[str] = None
) -> str:
    """Extract Base URL from query param or header, falling back to default."""
    if req_url and req_url.strip() and "jan-invalid-isle" not in req_url:
        return req_url.strip().rstrip("/")
    if header_url and header_url.strip() and "jan-invalid-isle" not in header_url:
        return header_url.strip().rstrip("/")
    return DEFAULT_PANEL_BASE_URL

def build_headers(api_key: str) -> Dict[str, str]:
    return {
        "User-Agent": "FastOTP-TeleCloud/2.2",
        "Accept": "application/json",
        "X-API-Key": api_key
    }

def get_config() -> Dict[str, Any]:
    return {
        "ok": True,
        "base_url": DEFAULT_PANEL_BASE_URL,
        "api_key": DEFAULT_PANEL_API_KEY
    }

def update_config(new_base_url: Optional[str] = None, new_api_key: Optional[str] = None) -> Dict[str, Any]:
    global DEFAULT_PANEL_BASE_URL, DEFAULT_PANEL_API_KEY
    if new_base_url and isinstance(new_base_url, str) and new_base_url.strip():
        DEFAULT_PANEL_BASE_URL = new_base_url.strip().rstrip("/")
    if new_api_key and isinstance(new_api_key, str) and new_api_key.strip():
        DEFAULT_PANEL_API_KEY = new_api_key.strip()
    return {
        "ok": True,
        "base_url": DEFAULT_PANEL_BASE_URL,
        "api_key": DEFAULT_PANEL_API_KEY,
        "message": "Configuration updated successfully"
    }

def fetch_numbers_sync(
    days: str = "2",
    key: Optional[str] = None,
    base_url: Optional[str] = None
) -> Dict[str, Any]:
    resolved_key = key or DEFAULT_PANEL_API_KEY
    resolved_base = (base_url or DEFAULT_PANEL_BASE_URL).rstrip("/")
    url = f"{resolved_base}/api/numbers"
    params = {"key": resolved_key, "days": str(days)}
    try:
        r = _session.get(url, params=params, headers=build_headers(resolved_key), timeout=18)
        if r.status_code == 200:
            return r.json()
        return {"ok": False, "detail": f"Upstream returned HTTP {r.status_code}", "raw": r.text[:200]}
    except Exception as e:
        logger.error(f"Error fetching numbers from upstream: {e}")
        return {"ok": False, "detail": str(e)}

def fetch_number_sms_sync(
    phone: str,
    key: Optional[str] = None,
    base_url: Optional[str] = None
) -> Dict[str, Any]:
    clean_phone = "".join(filter(str.isdigit, str(phone)))
    if len(clean_phone) > 10:
        clean_phone = clean_phone[-10:]
    resolved_key = key or DEFAULT_PANEL_API_KEY
    resolved_base = (base_url or DEFAULT_PANEL_BASE_URL).rstrip("/")
    url = f"{resolved_base}/api/{clean_phone}/sms"
    params = {"key": resolved_key}
    try:
        r = _session.get(url, params=params, headers=build_headers(resolved_key), timeout=18)
        if r.status_code == 200:
            return r.json()
        return {"ok": False, "detail": f"Upstream returned HTTP {r.status_code}", "raw": r.text[:200]}
    except Exception as e:
        logger.error(f"Error fetching SMS for {phone}: {e}")
        return {"ok": False, "detail": str(e)}

def fetch_panels_stats_sync(
    key: Optional[str] = None,
    base_url: Optional[str] = None
) -> Dict[str, Any]:
    resolved_key = key or DEFAULT_PANEL_API_KEY
    resolved_base = (base_url or DEFAULT_PANEL_BASE_URL).rstrip("/")
    url = f"{resolved_base}/api/panels_stats"
    params = {"key": resolved_key}
    try:
        r = _session.get(url, params=params, headers=build_headers(resolved_key), timeout=18)
        if r.status_code == 200:
            return r.json()
        return {"ok": False, "detail": f"Upstream returned HTTP {r.status_code}"}
    except Exception as e:
        logger.error(f"Error fetching panel stats: {e}")
        return {"ok": False, "detail": str(e)}

def fetch_api_status_sync(
    key: Optional[str] = None,
    base_url: Optional[str] = None
) -> Dict[str, Any]:
    resolved_key = key or DEFAULT_PANEL_API_KEY
    resolved_base = (base_url or DEFAULT_PANEL_BASE_URL).rstrip("/")
    url = f"{resolved_base}/api/status"
    params = {"key": resolved_key}
    try:
        r = _session.get(url, params=params, headers=build_headers(resolved_key), timeout=18)
        if r.status_code == 200:
            return r.json()
        return {"ok": False, "detail": f"Upstream returned HTTP {r.status_code}"}
    except Exception as e:
        logger.error(f"Error fetching API status: {e}")
        return {"ok": False, "detail": str(e)}
