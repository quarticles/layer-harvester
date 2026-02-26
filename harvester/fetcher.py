"""
Fetch WMS capabilities from live environments.

Reads credential/URL files from envs/<group>/<env>.local.env, logs in to
obtain a JWT, requests GetCapabilities, and saves the JSON response to
input/<group>/<env>.json.

No UI dependencies — all errors are returned as strings for callers to display.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Mirrors the path-resolution logic in core.py so the module works both when
# run from source and when bundled with PyInstaller.
if getattr(sys, "frozen", False):
    _ROOT = Path(sys.executable).parent
else:
    _ROOT = Path(__file__).parent.parent

ENVS_DIR = _ROOT / "envs"


# ── URL helpers ───────────────────────────────────────────────────────────────

def url_slug(url: str) -> str:
    """
    Extract a filename-safe slug from a URL.

    Examples:
        "https://dev.quarticle.ro/graph/api/v1/login" → "dev.quarticle.ro"
        "http://localhost:4200/graph/api/v1/login"    → "localhost"
    """
    hostname = urllib.parse.urlparse(url.strip()).hostname or ""
    return hostname


# ── .env parsing ──────────────────────────────────────────────────────────────

def parse_env_file(path: Path) -> dict:
    """Parse a simple KEY=VALUE file; skip blank lines and # comments."""
    env: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


# ── Directory scanning ────────────────────────────────────────────────────────

def _parse_env_filename(name: str) -> tuple[str, str] | None:
    """
    Parse a credential filename into (env_name, group).

    Expected pattern: .<group>.<environment>.env
    Examples:
        .quarticle.dev.env   → ("dev", "quarticle")
        .allianz.prod.env    → ("prod", "allianz")

    Returns None if the name does not match the pattern.
    """
    if not (name.startswith(".") and name.endswith(".env")):
        return None
    inner = name[1:-4]  # strip leading dot and .env suffix → "quarticle.dev"
    dot = inner.rfind(".")
    if dot == -1:
        return None
    return inner[dot + 1:], inner[:dot]  # (env_name, group)


def scan_envs(envs_dir: Path) -> list[tuple[str, str, dict]]:
    """
    Scan envs_dir for credential files.

    Expected layout:
        envs/.<environment>.<group>.env

    Returns a list of (group, env_name, env_dict) tuples sorted by
    group then env_name.
    """
    if not envs_dir.is_dir():
        return []

    results: list[tuple[str, str, dict]] = []
    for env_file in sorted(f for f in envs_dir.iterdir() if f.is_file()):
        parsed = _parse_env_filename(env_file.name)
        if parsed is None:
            continue
        env_name, group = parsed
        results.append((group, env_name, parse_env_file(env_file)))
    return sorted(results, key=lambda t: (t[0], t[1]))


# ── Single-file helper ────────────────────────────────────────────────────────

def env_entry_from_path(env_file: Path) -> tuple[str, str, dict]:
    """
    Convert an arbitrary .<environment>.<group>.env path to a (group, env_name, env_dict) tuple.

    Falls back to using the parent directory name as group if the filename
    does not match the expected pattern.
    """
    parsed = _parse_env_filename(env_file.name)
    if parsed:
        env_name, group = parsed
    else:
        group    = env_file.parent.name
        env_name = env_file.stem.lstrip(".")
    return group, env_name, parse_env_file(env_file)


# ── Fetch logic ───────────────────────────────────────────────────────────────

# Candidate field names to probe in the login response, in priority order.
_TOKEN_CANDIDATES = ("token", "access_token", "accessToken", "jwt", "id_token", "idToken")


def _extract_token(login_body: dict) -> str | None:
    """Return the first non-empty string value found under a known JWT field name."""
    for field in _TOKEN_CANDIDATES:
        value = login_body.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def fetch_capabilities(
    group: str,
    env_name: str,
    env_dict: dict,
    input_dir: Path,
) -> tuple[Path | None, str | None]:
    """
    Perform login → GetCapabilities → save for one environment.

    Required keys in env_dict:
        LOGIN_URL            — POST endpoint that returns a JWT
        GET_CAPABILITIES_URL — WMS GetCapabilities endpoint
        USERNAME             — login username
        PASSWORD             — login password

    The JWT token is auto-detected from the login response by probing common
    field names (token, access_token, accessToken, jwt, id_token, idToken).

    Returns:
        (saved_path, None)   on success
        (None, error_str)    on any failure; never raises
    """
    login_url = env_dict.get("LOGIN_URL", "").strip()
    caps_url  = env_dict.get("GET_CAPABILITIES_URL", "").strip()
    username  = env_dict.get("USERNAME", "").strip()
    password  = env_dict.get("PASSWORD", "").strip()

    if not login_url:
        return None, "LOGIN_URL is missing from .env file"
    if not caps_url:
        return None, "GET_CAPABILITIES_URL is missing from .env file"

    # ── Step 1: Login ─────────────────────────────────────────────────────────
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    login_req = urllib.request.Request(
        login_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(login_req, timeout=30) as resp:
            login_body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return None, f"Login failed HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return None, f"Login connection error: {exc.reason}"
    except json.JSONDecodeError:
        return None, "Login response is not valid JSON"
    except Exception as exc:  # noqa: BLE001
        return None, f"Login error: {exc}"

    token = _extract_token(login_body)
    if not token:
        available = list(login_body.keys())
        return None, f"No JWT token found in login response (keys present: {available})"

    # ── Step 2: GetCapabilities ───────────────────────────────────────────────
    caps_req = urllib.request.Request(
        caps_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(caps_req, timeout=60) as resp:
            caps_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return None, f"GetCapabilities failed HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return None, f"GetCapabilities connection error: {exc.reason}"
    except json.JSONDecodeError:
        return None, "GetCapabilities response is not valid JSON"
    except Exception as exc:  # noqa: BLE001
        return None, f"GetCapabilities error: {exc}"

    # ── Step 3: Save ──────────────────────────────────────────────────────────
    out_dir = input_dir / group
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{env_name}.json"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(caps_data, f)
    except OSError as exc:
        return None, f"Could not write {out_path}: {exc}"

    return out_path, None
