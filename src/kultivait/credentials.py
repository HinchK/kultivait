"""Provider credential resolution: env -> OS keychain -> credentials.toml.

Never logs, displays, or writes key material to config.toml.
"""

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

CREDENTIALS_PATH = Path.home() / ".kultivait" / "credentials.toml"

PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _get_env_key(provider: str) -> str | None:
    env_var = PROVIDER_ENV_VARS.get(provider.lower(), f"{provider.upper()}_API_KEY")
    val = os.environ.get(env_var)
    if val and val.strip():
        return val.strip()
    return None


def _get_keychain_key(service: str, account: str) -> str | None:
    """Query OS keychain (macOS `security find-generic-password -s <service> -a <account> -w`)."""
    if not shutil.which("security"):
        return None
    try:
        res = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if res.returncode == 0:
            val = res.stdout.strip()
            if val:
                return val
    except Exception:
        pass
    return None


def _get_file_key(provider: str, credentials_path: Path | None = None) -> str | None:
    path = credentials_path or CREDENTIALS_PATH
    if not path.exists():
        return None
    try:
        data = tomllib.loads(path.read_text())
        p_data = data.get(provider.lower()) or data.get(provider)
        if isinstance(p_data, dict):
            key = p_data.get("api_key") or p_data.get("key")
            if key and isinstance(key, str) and key.strip():
                return key.strip()
        elif isinstance(p_data, str) and p_data.strip():
            return p_data.strip()
    except Exception:
        pass
    return None


def resolve_provider_key(
    provider: str,
    credentials_path: Path | None = None,
) -> str | None:
    """Resolve API key for a provider in priority order:
    1. Environment variables (e.g. ANTHROPIC_API_KEY)
    2. OS Keychain (service='kultivait', account=provider)
    3. ~/.kultivait/credentials.toml
    """
    # 1. Environment variable
    env_key = _get_env_key(provider)
    if env_key:
        return env_key

    # 2. OS Keychain
    kc_key = _get_keychain_key("kultivait", provider.lower())
    if kc_key:
        return kc_key

    # 3. Credentials file
    file_key = _get_file_key(provider, credentials_path=credentials_path)
    if file_key:
        return file_key

    return None


def write_credentials(
    provider: str,
    key: str,
    path: Path | None = None,
) -> None:
    """Write provider key to credentials.toml with 0600 permissions."""
    cred_file = path or CREDENTIALS_PATH
    cred_file.parent.mkdir(parents=True, exist_ok=True)

    existing_data: dict = {}
    if cred_file.exists():
        try:
            existing_data = tomllib.loads(cred_file.read_text())
        except Exception:
            existing_data = {}

    existing_data[provider.lower()] = {"api_key": key}

    lines = ["# kultivait credentials — permissions 0600"]
    for prov, values in sorted(existing_data.items()):
        lines.append(f"\n[{prov}]")
        if isinstance(values, dict):
            for k, v in sorted(values.items()):
                lines.append(f'{k} = "{v}"')
        elif isinstance(values, str):
            lines.append(f'api_key = "{values}"')

    content = "\n".join(lines) + "\n"
    cred_file.write_text(content)
    try:
        os.chmod(cred_file, 0o600)
    except OSError:
        pass


def mask_key(key: str | None) -> str:
    """Safely mask key material for non-sensitive presentation."""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def probe_provider(
    provider: str,
    key: str | None = None,
    timeout_s: float = 3.0,
    client: "Any" = None,
) -> bool:
    """Run live presence probe for provider (Anthropic, OpenAI, OpenRouter).
    Returns True if probe succeeds, False otherwise."""
    import httpx

    resolved_key = key or resolve_provider_key(provider)
    if not resolved_key:
        return False

    prov_lower = provider.lower()
    http_client = client or httpx.Client(timeout=timeout_s)
    should_close = client is None

    try:
        if "anthropic" in prov_lower or "claude" in prov_lower:
            r = http_client.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": resolved_key, "anthropic-version": "2023-06-01"},
            )
            return r.status_code in (200, 201)
        elif "openai" in prov_lower or "gpt" in prov_lower:
            r = http_client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {resolved_key}"},
            )
            return r.status_code == 200
        elif "openrouter" in prov_lower:
            r = http_client.get(
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": f"Bearer {resolved_key}"},
            )
            return r.status_code == 200
        return True
    except Exception:
        return False
    finally:
        if should_close:
            try:
                http_client.close()
            except Exception:
                pass


def probe_candidate_targets(
    targets: list[str],
    target_kinds: dict[str, str] | None = None,
    timeout_s: float = 3.0,
    client: "Any" = None,
) -> dict[str, bool]:
    """Concurrently probe all API targets in candidates. CLI and local targets return True."""
    import concurrent.futures

    target_kinds = target_kinds or {}
    results: dict[str, bool] = {}
    api_targets = []

    for t in targets:
        kind = target_kinds.get(t, "api" if t in ("openrouter", "openai", "anthropic") else "cli")
        if kind == "api":
            api_targets.append(t)
        else:
            results[t] = True

    if not api_targets:
        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(api_targets))) as executor:
        future_to_target = {
            executor.submit(probe_provider, t, timeout_s=timeout_s, client=client): t
            for t in api_targets
        }
        for future in concurrent.futures.as_completed(future_to_target):
            t = future_to_target[future]
            try:
                results[t] = future.result()
            except Exception:
                results[t] = False

    return results
