"""Configuration: how Kultivait meets a machine it has never seen.

`detect()` is a pure function from (installed ollama models, available CLIs)
to a Config, so any stranger's laptop is a unit-test fixture. Local-only
setups keep *virtual* cloud tiers: classification still recognizes
cloud-worthy prompts so the escalation-brief path fires — there is simply no
backend to serve them.
"""

import re
import tomllib
import warnings
from dataclasses import dataclass, field
from pathlib import Path

ROLES = ["simple", "reasoning", "docs", "architect"]  # capability order

# Local runtimes and their default server addresses.
RUNTIME_URLS = {
    "ollama": "http://localhost:11434",
    "llamacpp": "http://localhost:8080",
}

# Known embedding models (never generation candidates), preferred first.
EMBED_MODELS = ["nomic-embed-text", "bge-m3", "all-minilm", "mxbai-embed"]

KNOWN_CLIS = {
    "claude": "architect",
    "codex": "architect",
    "opencode": "architect",
    "agy": "docs",
    "gemini": "docs",
}
CLI_PRICING = {  # USD per million tokens, rough frontier-tier defaults
    "claude": (3.0, 15.0),
    "codex": (1.25, 10.0),
    # opencode is multi-provider so price varies by selected provider/model; conservative default:
    "opencode": (3.0, 15.0),
    "agy": (1.25, 10.0),
    "gemini": (1.25, 10.0),
}

DEFAULT_API_PRICE_IN = 3.0
DEFAULT_API_PRICE_OUT = 15.0


@dataclass(frozen=True)
class ProviderDefaults:
    model: str            # pinned exact id
    price_in: float       # USD/MTok
    price_out: float
    max_output_tokens: int
    token_field: str      # "max_tokens" | "max_completion_tokens"


# Curated per-model capability metadata (the #64 dogfooding fix generalized):
# exact pinned ids -> whether the model accepts reasoning-effort params.
# Providers 400 on reasoning fields for non-reasoning models (live evidence:
# Google Vertex rejected the `thinking` translation for llama-3.3-70b).
# Unknown ids fall back to the family-pattern list in api_backends.
MODEL_SUPPORTS_REASONING: dict[str, bool] = {
    # OpenAI
    "gpt-4o": False, "openai/gpt-4o": False,
    "gpt-4o-mini": False, "openai/gpt-4o-mini": False,
    "openai/gpt-5.6-sol": True, "openai/gpt-5.6-terra": True,
    "openai/gpt-5.6-luna": True, "openai/gpt-5.5": True,
    # Anthropic
    "anthropic/claude-sonnet-5": True, "claude-sonnet-5": True,
    "anthropic/claude-haiku-4.5": True,
    # Meta — no reasoning params
    "meta-llama/llama-3.3-70b-instruct": False,
    # Neutral teacher families (ADR 0016 amendment)
    "x-ai/grok-4.6": True,
    "deepseek/deepseek-v4-flash-0731": True,
    "deepseek/deepseek-v4-pro-0813": True,
    # Google
    "google/gemini-3.7-flash": False,
}


PROVIDER_DEFAULTS: dict[str, ProviderDefaults] = {
    "anthropic": ProviderDefaults(
        model="claude-3-7-sonnet-20250219",
        price_in=3.0,
        price_out=15.0,
        max_output_tokens=8192,
        token_field="max_tokens",
    ),
    "openai": ProviderDefaults(
        model="gpt-4o",
        price_in=2.5,
        price_out=10.0,
        max_output_tokens=16384,
        token_field="max_completion_tokens",
    ),
    "openrouter": ProviderDefaults(
        model="anthropic/claude-3.7-sonnet",
        price_in=3.0,
        price_out=15.0,
        max_output_tokens=8192,
        token_field="max_tokens",
    ),
}


@dataclass(frozen=True)
class TierSpec:
    name: str
    role: str
    kind: str  # "ollama" | "llamacpp" | "cli" | "virtual" | "api"
    model: "str | None" = None
    command: "list[str] | None" = None
    price_in: float = 0.0
    price_out: float = 0.0


@dataclass(frozen=True)
class DistillConfig:
    """The distillation pipeline's serving seat (ADR 0017): the live preprocess
    model, resolved per-call so a config edit swaps models with no restart."""

    model: str = "qwen3.5:4b"
    shadow_model: str = ""  # gate-passing distillate name; empty = none
    shadow_mode: str = "off"  # "off" | "on"
    shadow_sample_rate: float = 1.0


@dataclass(frozen=True)
class Config:
    tiers: "list[TierSpec]" = field(default_factory=list)
    embed_model: "str | None" = "nomic-embed-text"
    distill_model: "str | None" = None
    num_ctx: int = 32768
    port: int = 4114
    runtime: str = "ollama"  # "ollama" | "llamacpp"
    chat_base_url: str = RUNTIME_URLS["ollama"]
    # llama.cpp may need a dedicated embedding server (its --embedding flag
    # is server-wide); empty means "same server as chat".
    embed_base_url: str = ""
    preprocess_timeout_s: float = 15.0
    toll_timeout_s: float = 60.0
    toll_enabled: bool = True
    distill: DistillConfig = field(default_factory=DistillConfig)

    def capability_order(self) -> "list[str]":
        return [t.name for t in self.tiers]

    def embed_url(self) -> str:
        return self.embed_base_url or self.chat_base_url


SIMPLE_TIER_FLOOR_B = 4.0  # below ~4B, "simple" work stops being reliable
GB_PER_BILLION_Q4 = 0.75  # rough q4 quantization: bytes -> parameter estimate


def _param_billions(model: str, size_bytes: "int | None" = None) -> float:
    """Size class from the model name, falling back to disk size for
    unparseable names — a name without a number is not a tiny model."""
    m = re.search(r"(\d+(?:\.\d+)?)b", model.lower())
    if m:
        return float(m.group(1))
    if size_bytes:
        return size_bytes / 1e9 / GB_PER_BILLION_Q4
    return 0.0


def _is_embedding(model: str) -> bool:
    return any(e in model.lower() for e in EMBED_MODELS) or "embed" in model.lower()


def detect(
    ollama_models: "list[str]",
    available_clis: "list[str]",
    sizes: "dict[str, int] | None" = None,
    runtime: str = "ollama",
) -> Config:
    """`ollama_models` is any local model listing — ollama tags or GGUF
    names/ids from a llama-server router; the sizing rules are identical."""
    sizes = sizes or {}
    embeds = [m for m in ollama_models if _is_embedding(m)]
    billions = {
        m: _param_billions(m, sizes.get(m))
        for m in ollama_models
        if not _is_embedding(m)
    }
    general = sorted(billions, key=billions.get)

    embed_model = None
    for preferred in EMBED_MODELS:
        match = next((m for m in embeds if preferred in m.lower()), None)
        if match:
            embed_model = match
            break
    if embed_model is None and embeds:
        embed_model = embeds[0]

    tiers: list[TierSpec] = []
    if general:
        above_floor = [m for m in general if billions[m] >= SIMPLE_TIER_FLOOR_B]
        simple = above_floor[0] if above_floor else general[-1]
        largest = general[-1]
        tiers.append(TierSpec(name=simple, role="simple", kind=runtime, model=simple))
        tiers.append(TierSpec(name=largest, role="reasoning", kind=runtime, model=largest))

    cli_by_role: dict[str, str] = {}
    for cli in available_clis:
        role = KNOWN_CLIS.get(cli)
        if role and role not in cli_by_role:
            cli_by_role[role] = cli
    for role in ("docs", "architect"):
        if role in cli_by_role:
            cli = cli_by_role[role]
            price_in, price_out = CLI_PRICING.get(cli, (3.0, 15.0))
            tiers.append(
                TierSpec(
                    name=cli if role == "architect" else f"{role}:{cli}",
                    role=role, kind="cli", command=[cli],
                    price_in=price_in, price_out=price_out,
                )
            )
        else:
            # Virtual tier: classified, never served — escalation fires instead.
            tiers.append(TierSpec(name=f"frontier:{role}", role=role, kind="virtual"))

    tiers.sort(key=lambda t: ROLES.index(t.role))
    return Config(
        tiers=tiers,
        embed_model=embed_model,
        distill_model=general[-1] if general else None,
        runtime=runtime,
        chat_base_url=RUNTIME_URLS.get(runtime, RUNTIME_URLS["ollama"]),
    )


def save_config(config: Config, path: Path) -> None:
    lines = [
        "# kultivait configuration — regenerate anytime with: kultivait init",
        f"runtime = {_toml_str(config.runtime)}",
        f"chat_base_url = {_toml_str(config.chat_base_url)}",
        f"embed_base_url = {_toml_str(config.embed_base_url)}",
        f"embed_model = {_toml_str(config.embed_model)}",
        f"distill_model = {_toml_str(config.distill_model)}",
        f"num_ctx = {config.num_ctx}",
        f"port = {config.port}",
        f"preprocess_timeout_s = {config.preprocess_timeout_s}",
        f"toll_timeout_s = {config.toll_timeout_s}",
        f"toll_enabled = {'true' if config.toll_enabled else 'false'}",
    ]
    for t in config.tiers:
        lines += ["", "[[tiers]]", f'name = "{t.name}"', f'role = "{t.role}"', f'kind = "{t.kind}"']
        if t.model:
            lines.append(f'model = "{t.model}"')
        if t.command:
            lines.append(f"command = [{', '.join(chr(34) + c + chr(34) for c in t.command)}]")
        if t.price_in or t.price_out:
            lines.append(f"price_in = {t.price_in}")
            lines.append(f"price_out = {t.price_out}")
    d = config.distill
    lines += [
        "",
        "[distill]",
        f"model = {_toml_str(d.model)}",
        f"shadow_model = {_toml_str(d.shadow_model)}",
        f'shadow_mode = "{d.shadow_mode}"',
        f"shadow_sample_rate = {d.shadow_sample_rate}",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def _toml_str(value: "str | None") -> str:
    return f'"{value}"' if value is not None else '""'


def load_config(path: Path) -> Config:
    data = tomllib.loads(Path(path).read_text())
    tiers = []
    for t in data.get("tiers", []):
        kind = t["kind"]
        price_in = float(t.get("price_in", 0.0))
        price_out = float(t.get("price_out", 0.0))
        if kind == "api" and price_in == 0.0 and price_out == 0.0:
            warnings.warn(
                f"Tier '{t['name']}' has kind='api' but no pricing configured; "
                f"defaulting to conservative ${DEFAULT_API_PRICE_IN}/${DEFAULT_API_PRICE_OUT} per MTok",
                UserWarning,
                stacklevel=2,
            )
            price_in = DEFAULT_API_PRICE_IN
            price_out = DEFAULT_API_PRICE_OUT
        tiers.append(
            TierSpec(
                name=t["name"],
                role=t["role"],
                kind=kind,
                model=t.get("model"),
                command=t.get("command"),
                price_in=price_in,
                price_out=price_out,
            )
        )
    dd = data.get("distill") or {}
    shadow_mode = dd.get("shadow_mode") or "off"
    if shadow_mode not in ("off", "on"):
        raise ValueError(f"distill.shadow_mode must be 'off' or 'on', got {shadow_mode!r}")
    return Config(
        tiers=tiers,
        embed_model=data.get("embed_model") or None,
        distill_model=data.get("distill_model") or None,
        num_ctx=data.get("num_ctx", 32768),
        port=data.get("port", 4114),
        runtime=data.get("runtime") or "ollama",
        chat_base_url=data.get("chat_base_url") or RUNTIME_URLS["ollama"],
        embed_base_url=data.get("embed_base_url") or "",
        preprocess_timeout_s=float(data.get("preprocess_timeout_s", 15.0)),
        distill=DistillConfig(
            model=dd.get("model") or "qwen3.5:4b",
            shadow_model=dd.get("shadow_model") or "",
            shadow_mode=shadow_mode,
            shadow_sample_rate=float(dd.get("shadow_sample_rate", 1.0)),
        ),
    )
