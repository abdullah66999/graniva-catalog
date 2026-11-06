"""Read-only checks for FacetLine GitHub Actions provider credentials.

The script never prints credentials or provider response bodies. It does not
generate content, write to Supabase, or publish to GitHub Pages.
"""

import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def request_status(url: str, headers: dict[str, str]) -> int | str:
    try:
        request = Request(url, headers=headers, method="GET")
        with urlopen(request, timeout=20) as response:
            response.read(1024)
            return response.status
    except HTTPError as error:
        status = error.code
        error.close()
        return status
    except URLError:
        return "network_error"
    except (TimeoutError, OSError):
        return "network_error"


def main() -> int:
    supabase_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    supabase_key = os.environ.get("SUPABASE_SECRET_KEY", "").strip()
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    google_key = os.environ.get("GOOGLE_API_KEY", "").strip()

    parsed = urlsplit(supabase_url)
    valid_url = (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.hostname.endswith(".supabase.co")
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
        and not parsed.username
    )
    valid_key_shape = supabase_key.startswith("sb_secret_")
    print(f"Supabase URL shape: {'ok' if valid_url else 'invalid'}")
    print(f"Supabase key shape expected by cloud worker: {'ok' if valid_key_shape else 'invalid'}")

    statuses: list[tuple[str, int | str]] = []
    if valid_url and supabase_key:
        statuses.append(("Supabase Storage bucket", request_status(
            f"{supabase_url}/storage/v1/bucket/facetline-private",
            {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}", "Accept": "application/json"},
        )))
    else:
        statuses.append(("Supabase Storage bucket", "skipped_invalid_config"))

    if openrouter_key:
        statuses.append(("OpenRouter read-only key endpoint", request_status(
            "https://openrouter.ai/api/v1/key",
            {"Authorization": f"Bearer {openrouter_key}", "Accept": "application/json"},
        )))
    else:
        statuses.append(("OpenRouter read-only key endpoint", "missing"))

    if google_key:
        statuses.append(("Google AI Studio model-list endpoint", request_status(
            "https://generativelanguage.googleapis.com/v1beta/models",
            {"x-goog-api-key": google_key, "Accept": "application/json"},
        )))
    else:
        statuses.append(("Google AI Studio model-list endpoint", "missing"))

    for name, status in statuses:
        print(f"{name}: HTTP {status}" if isinstance(status, int) else f"{name}: {status}")
    return 0 if all(status == 200 for _, status in statuses) and valid_url and valid_key_shape else 1


if __name__ == "__main__":
    raise SystemExit(main())

