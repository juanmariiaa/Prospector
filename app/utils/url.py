"""URL utility helpers."""


def normalize_url(url: str) -> str:
    """Ensure URL has an https:// scheme. Returns empty string unchanged."""
    if not url:
        return url
    if not url.startswith(("http://", "https://")):
        return f"https://{url}"
    return url
