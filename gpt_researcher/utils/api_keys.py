import os
from typing import Iterable


def _split_key_list(raw_value: str) -> list[str]:
    """Split comma/newline/semicolon-separated key lists and remove blanks."""
    normalized = raw_value.replace("\n", ",").replace(";", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def collect_api_keys(
    primary_env_var: str,
    fallback_env_var: str | None = None,
    list_env_var: str | None = None,
    explicit_keys: Iterable[str] | None = None,
) -> list[str]:
    """
    Collect API keys in priority order with de-duplication.

    Priority:
    1. explicit_keys values (if any)
    2. primary_env_var
    3. fallback_env_var
    4. list_env_var (comma/newline/semicolon separated)
    """
    candidates: list[str] = []

    if explicit_keys:
        for key in explicit_keys:
            if key:
                candidates.append(key.strip())

    primary_key = os.getenv(primary_env_var, "").strip()
    if primary_key:
        candidates.extend(_split_key_list(primary_key))

    if fallback_env_var:
        fallback_key = os.getenv(fallback_env_var, "").strip()
        if fallback_key:
            candidates.extend(_split_key_list(fallback_key))

    if list_env_var:
        list_value = os.getenv(list_env_var, "").strip()
        if list_value:
            candidates.extend(_split_key_list(list_value))

    # Preserve order while removing duplicates.
    unique_keys: list[str] = []
    seen: set[str] = set()
    for key in candidates:
        if key and key not in seen:
            seen.add(key)
            unique_keys.append(key)

    return unique_keys


def mask_api_key(key: str) -> str:
    """Mask an API key for safe logging, showing only the first 4 and last 4 chars."""
    if not key or len(key) <= 10:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


def is_probable_quota_or_auth_error(error_text: str) -> bool:
    """Heuristic for key-exhausted/auth-limited errors where fallback keys help."""
    text = (error_text or "").lower()
    signals = (
        "quota",
        "rate limit",
        "too many requests",
        "insufficient credits",
        "insufficient credit",
        "credits exhausted",
        "usage limit",
        "unauthorized",
        "forbidden",
        "401",
        "403",
        "429",
        "invalid api key",
        "api key is invalid",
    )
    return any(signal in text for signal in signals)
