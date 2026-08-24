"""kultivait CLI: serve the proxy, inspect the harvest, dry-run a route.

Configuration is detected live from the machine (installed local models —
ollama or llama.cpp — and available CLIs) unless ~/.kultivait/config.toml
exists — `kultivait init` writes that file so the decisions are visible and
editable.
"""

import argparse
import json
import random
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import httpx
import numpy as np

from kultivait.api_backends import AnthropicBackend, OpenAIBackend, OpenRouterBackend
from kultivait.backends import CLIBackend, LlamaCppBackend, OllamaBackend
from kultivait.credentials import resolve_provider_key
from kultivait.config import (
    KNOWN_CLIS,
    RUNTIME_URLS,
    Config,
    detect,
    load_config,
    save_config,
)
from kultivait.escalations import (
    HANDOFF_PROMPT,
    EscalationStore,
    recommended_target,
    render_transcript,
)
from kultivait.gates import Gate
from kultivait.ledger import Ledger
from kultivait.router import Router
from kultivait.seeds import ROLE_SEEDS

import kultivait.bootstrap as bootstrap
import kultivait.hardware as hardware
from kultivait import keys, onboarding, setup_screen, tui

OLLAMA_URL = RUNTIME_URLS["ollama"]
LLAMACPP_URL = os.environ.get("KULTIVAIT_LLAMACPP_URL", RUNTIME_URLS["llamacpp"])
KULTIVAIT_HOME = Path.home() / ".kultivait"
CONFIG_PATH = KULTIVAIT_HOME / "config.toml"
LEDGER_PATH = KULTIVAIT_HOME / "ledger.jsonl"
COMPOST_DIR = KULTIVAIT_HOME / "compost"
ESCALATIONS_DIR = KULTIVAIT_HOME / "escalations"
PENDING_TOLLS_PATH = KULTIVAIT_HOME / "pending_tolls.jsonl"
PRESENCE_PATH = KULTIVAIT_HOME / "presence.json"
TOLL_ANSWERS_DIR = KULTIVAIT_HOME / "toll_answers"


def _survey_ollama() -> "tuple[list[str], dict[str, int]]":
    r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10)
    r.raise_for_status()
    models = r.json().get("models", [])
    return [m["name"] for m in models], {m["name"]: m.get("size", 0) for m in models}


def match_gguf_sizes(names: "list[str]", files: "dict[str, int]") -> "dict[str, int]":
    """Router model ids and cache filenames drift (path prefixes flattened to
    underscores, :quant suffixes, case varies): match when every token of the
    id appears in the filename. Unmatched names are omitted — _param_billions
    still reads a parameter count from the name itself."""
    import re

    def tokens(s: str) -> set:
        return set(re.split(r"[/:_.\-]+", s.lower())) - {""}

    sizes: dict[str, int] = {}
    for name in names:
        n = tokens(name)
        for fname, size in files.items():
            if n <= tokens(fname):
                sizes[name] = size
                break
    return sizes


def _local_llamacpp_models(
    entries: "list[dict]", cache_files: "dict[str, int]"
) -> "tuple[list[str], dict[str, int]]":
    """Filter a router /v1/models listing to models actually on disk.

    Router listings include downloadable HF suggestions; picking a tier that
    isn't downloaded would trigger a surprise multi-GB fetch on first route.
    On-disk models carry `--model <path>` in status.args (stat that path);
    --hf-repo entries count only if a matching GGUF is already cached.
    """
    names: list[str] = []
    sizes: dict[str, int] = {}
    for m in entries:
        args = m.get("status", {}).get("args", [])
        path = Path(args[args.index("--model") + 1]) if "--model" in args else None
        if path and path.exists():
            names.append(m["id"])
            sizes[m["id"]] = path.stat().st_size
        elif "--hf-repo" in args:
            matched = match_gguf_sizes([m["id"]], cache_files)
            if m["id"] in matched:
                names.append(m["id"])
                sizes[m["id"]] = matched[m["id"]]
    return names, sizes


def _gguf_dirs() -> "list[Path]":
    """Where llama-server caches GGUF files, most specific override first."""
    override = os.environ.get("KULTIVAIT_LLAMACPP_MODELS_DIR") or os.environ.get(
        "LLAMA_CACHE"
    )
    if override:
        return [Path(override)]
    return [
        Path.home() / "Library" / "Caches" / "llama.cpp",  # macOS default
        Path.home() / ".cache" / "llama.cpp",
    ]


def _survey_llamacpp() -> "tuple[list[str], dict[str, int]]":
    """Names from the router's /v1/models (the authoritative request ids);
    sizes by stat-ing GGUF files on disk, because /v1/models reports full
    metadata only for currently-loaded models."""
    r = httpx.get(f"{LLAMACPP_URL}/v1/models", timeout=10)
    r.raise_for_status()
    entries = r.json().get("data", [])
    files: dict[str, int] = {}
    for d in _gguf_dirs():
        if d.expanduser().is_dir():
            for f in d.expanduser().rglob("*.gguf"):
                files[f.name] = f.stat().st_size
    return _local_llamacpp_models(entries, files)


def _reachable(url: str) -> bool:
    try:
        return httpx.get(url, timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def _running_runtime() -> "str | None":
    """Which local server actually answers right now, if any."""
    if _reachable(f"{OLLAMA_URL}/api/tags"):
        return "ollama"
    if _reachable(f"{LLAMACPP_URL}/v1/models"):
        return "llamacpp"
    return None


def _detect_runtime() -> str:
    """Prefer whichever local server is actually running; if both, ollama
    (the eval-proven setup). KULTIVAIT_RUNTIME overrides."""
    return os.environ.get("KULTIVAIT_RUNTIME") or _running_runtime() or "ollama"


def _survey_local(runtime: str) -> "tuple[list[str], dict[str, int]]":
    return _survey_llamacpp() if runtime == "llamacpp" else _survey_ollama()


def _available_clis() -> "list[str]":
    return [cli for cli in KNOWN_CLIS if shutil.which(cli)]


def get_config() -> Config:
    if CONFIG_PATH.exists():
        config = load_config(CONFIG_PATH)
    else:
        runtime = _detect_runtime()
        models, sizes = _survey_local(runtime)
        config = detect(models, _available_clis(), sizes=sizes, runtime=runtime)
    # env overrides win, always
    distill = os.environ.get("KULTIVAIT_DISTILL_MODEL")
    num_ctx = os.environ.get("KULTIVAIT_NUM_CTX")
    if distill or num_ctx:
        from dataclasses import replace

        config = replace(
            config,
            distill_model=distill or config.distill_model,
            num_ctx=int(num_ctx) if num_ctx else config.num_ctx,
        )
    return config


def _require_embed_model(config: Config) -> str:
    if not config.embed_model:
        if config.runtime == "llamacpp":
            hint = (
                "Download a nomic-embed-text GGUF into your llama.cpp models dir\n"
                "and mark it `embedding = 1` in a --models-preset INI\n"
                "(see README: Using with llama.cpp), then retry."
            )
        else:
            hint = "Pull one (274 MB), then retry:\n\n    ollama pull nomic-embed-text"
        sys.exit(f"kultivait needs a local embedding model to weigh prompts.\n{hint}\n")
    return config.embed_model


def _embed_batch(config: Config, texts: "list[str]") -> np.ndarray:
    if config.runtime == "llamacpp":
        r = httpx.post(
            f"{config.embed_url()}/v1/embeddings",
            json={"model": config.embed_model, "input": texts},
            timeout=120,
        )
        r.raise_for_status()
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        return np.array([d["embedding"] for d in data])
    r = httpx.post(
        f"{config.embed_url()}/api/embed",
        json={"model": config.embed_model, "input": texts},
        timeout=120,
    )
    r.raise_for_status()
    return np.array(r.json()["embeddings"])


def build_router(config: Config) -> Router:
    _require_embed_model(config)
    centroids = {}
    for tier in config.tiers:
        vecs = _embed_batch(config, ROLE_SEEDS[tier.role])
        vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        centroids[tier.name] = vecs.mean(axis=0)
    return Router(centroids=centroids, capability_order=config.capability_order())


def _provider_for_tier(name: str, model: str | None) -> str:
    name_lower = name.lower()
    if "openrouter" in name_lower:
        return "openrouter"
    if "anthropic" in name_lower or "claude" in name_lower:
        return "anthropic"
    if "openai" in name_lower or "gpt" in name_lower or "o3" in name_lower:
        return "openai"
    if model:
        model_lower = model.lower()
        if "/" in model_lower:
            return "openrouter"
        if "claude" in model_lower:
            return "anthropic"
        if "gpt" in model_lower or "o1" in model_lower or "o3" in model_lower:
            return "openai"
    return name_lower


def build_backends(config: Config) -> dict:
    backends = {}
    for tier in config.tiers:
        if tier.kind == "ollama":
            backends[tier.name] = OllamaBackend(
                tier.model, config.chat_base_url, num_ctx=config.num_ctx
            )
        elif tier.kind == "llamacpp":
            backends[tier.name] = LlamaCppBackend(tier.model, config.chat_base_url)
        elif tier.kind == "cli":
            backends[tier.name] = CLIBackend(
                tier.command, price_in=tier.price_in, price_out=tier.price_out
            )
        elif tier.kind == "api":
            prov = _provider_for_tier(tier.name, tier.model)
            key = resolve_provider_key(prov)
            if key:
                if prov == "openrouter":
                    backends[tier.name] = OpenRouterBackend(
                        model=tier.model or "anthropic/claude-3.7-sonnet",
                        api_key=key,
                        price_in=tier.price_in,
                        price_out=tier.price_out,
                    )
                elif prov == "anthropic":
                    backends[tier.name] = AnthropicBackend(
                        model=tier.model or "claude-3-7-sonnet-20250219",
                        api_key=key,
                        price_in=tier.price_in,
                        price_out=tier.price_out,
                    )
                elif prov == "openai":
                    backends[tier.name] = OpenAIBackend(
                        model=tier.model or "gpt-4o",
                        api_key=key,
                        price_in=tier.price_in,
                        price_out=tier.price_out,
                    )
        # "virtual" tiers get no backend: classified, never served — the
        # escalation path fires instead.
    return backends


def _distill_generate_for(config: Config):
    import re

    def generate(prompt: str) -> str:
        messages = [{"role": "user", "content": prompt}]
        if config.runtime == "llamacpp":
            payload = {"model": config.distill_model, "messages": messages, "stream": False}
            r = httpx.post(
                f"{config.chat_base_url}/v1/chat/completions", json=payload, timeout=600
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"] or ""
        else:
            payload = {
                "model": config.distill_model,
                "messages": messages,
                "stream": False,
                "options": {"num_ctx": config.num_ctx},
            }
            if (config.distill_model or "").startswith("qwen3"):
                payload["think"] = False
            r = httpx.post(f"{config.chat_base_url}/api/chat", json=payload, timeout=600)
            r.raise_for_status()
            text = r.json()["message"]["content"]
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    return generate


def build_gate(config: Config, template: "str | None" = None) -> Gate:
    kwargs = {"template": template} if template else {}
    return Gate(generate=_distill_generate_for(config), compost_dir=COMPOST_DIR, **kwargs)


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _run_setup_screen(first_run: bool) -> "setup_screen.setup_state.SetupOutcome":
    """The magnitude-parity setup screen: preparation checklist -> garden
    chooser -> download -> serve. RealDriver is wired with this module's
    probes; the screen owns every consent (Enter, Esc, the sudo card)."""
    driver = setup_screen.RealDriver(
        scan=hardware.scan,
        plan=hardware.plan,
        probe=_running_runtime,
        survey=_survey_local,
        clis=_available_clis,
    )
    with keys.KeyReader() as reader:
        return setup_screen.run_setup(driver=driver, keys=reader, first_run=first_run)


def _survey_and_save(runtime: str) -> None:
    try:
        models, sizes = _survey_local(runtime)
    except httpx.HTTPError:
        models, sizes = [], {}  # bare machine: virtual-tier config, not a traceback
    clis = _available_clis()
    config = detect(models, clis, sizes=sizes, runtime=runtime)
    tui.console.print(
        tui.render_survey(runtime, config.chat_base_url, models, clis, config)
    )
    save_config(config, CONFIG_PATH)
    tui.console.print(f"\n[green]✓[/green] wrote {CONFIG_PATH}")
    tui.console.print("edit it anytime; start the proxy with: [bold]kultivait serve[/bold]")


def cmd_init(args: argparse.Namespace) -> None:
    forced = os.environ.get("KULTIVAIT_RUNTIME")
    first_run = not onboarding.is_complete()
    if not args.no_setup and _stdin_is_tty() and (args.setup or first_run):
        outcome = _run_setup_screen(first_run=first_run)
        if outcome.exit != "closed":
            _survey_and_save(outcome.runtime or forced or _detect_runtime())
            if first_run:
                onboarding.complete(skipped=outcome.exit == "skipped")
                if outcome.exit == "skipped":
                    tui.console.print(
                        "re-run [bold]kultivait init[/bold] anytime to grow a local garden"
                    )
        return
    _survey_and_save(forced or _detect_runtime())


def _render_route_menu(ticket: "Any") -> str:
    if hasattr(ticket, "ticket_id"):
        tid = ticket.ticket_id
        orig_prompt = ticket.original_prompt
        options = ticket.options
        created_at = ticket.created_at
        timeout_s = ticket.timeout_s
    else:
        tid = ticket.get("ticket_id", "")
        orig_prompt = ticket.get("original_prompt", "")
        options = ticket.get("options", [])
        created_at = ticket.get("created_at", time.time())
        timeout_s = ticket.get("timeout_s", 60.0)

    remaining = max(0, int(timeout_s - (time.time() - created_at)))
    lines = [
        f"Route Menu — Contested Request [ticket: {tid}] ({remaining}s remaining)",
    ]
    if orig_prompt:
        snippet = orig_prompt[:80] + ("..." if len(orig_prompt) > 80 else "")
        lines.append(f"Prompt: {snippet}")
    lines.append("")

    for i, opt in enumerate(options, 1):
        if hasattr(opt, "target"):
            target = opt.target
            display_name = opt.display_name
            fit = opt.fit
            cost = opt.estimated_cost_usd
            canonical = opt.effort.canonical
            cli_flags = " ".join(opt.effort.cli_flags)
        else:
            target = opt.get("target", "")
            display_name = opt.get("display_name", target)
            fit = opt.get("fit", 0.0)
            cost = opt.get("estimated_cost_usd", 0.0)
            canonical = opt.get("effort", "balanced")
            cli_flags = " ".join(opt.get("cli_flags", []))

        fit_str = f"{fit:.2f}" if fit > 0 else "—"
        cost_str = f"${cost:.4f}" if cost > 0 else "$0.00"
        effort_str = f"{canonical} ({cli_flags})" if cli_flags else canonical
        if target == "local":
            lines.append(f"  [{i}] {display_name:<20} keep-it-local (original prompt, $0.00)")
        else:
            lines.append(
                f"  [{i}] {display_name:<20} fit: {fit_str:<5} cost: {cost_str:<8} effort: {effort_str}"
            )

    lines.append("")
    lines.append(f"Controls: [1-{len(options)}] select, [e] override effort, [q] quit")
    return "\n".join(lines)


def _prompt_choice(options_count: int, input_fn=input) -> "tuple[int, str | None] | None":
    while True:
        try:
            raw = input_fn(f"selection [1-{options_count}, e, q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if raw in ("q", "quit", "exit"):
            return None

        if raw == "e":
            opt_idx = 0
            if options_count > 1:
                try:
                    opt_raw = input_fn(f"option to override [1-{options_count}]: ").strip()
                except (EOFError, KeyboardInterrupt):
                    return None
                if not opt_raw.isdigit() or not (1 <= int(opt_raw) <= options_count):
                    print(f"invalid option: {opt_raw}")
                    continue
                opt_idx = int(opt_raw) - 1

            try:
                eff_raw = input_fn("effort level [1: fast, 2: balanced, 3: deep]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return None

            eff_map = {
                "1": "fast", "f": "fast", "fast": "fast",
                "2": "balanced", "b": "balanced", "balanced": "balanced",
                "3": "deep", "d": "deep", "deep": "deep",
            }
            if eff_raw in eff_map:
                return (opt_idx, eff_map[eff_raw])
            else:
                print(f"invalid effort level: {eff_raw}")
                continue

        if raw.isdigit() and 1 <= int(raw) <= options_count:
            return (int(raw) - 1, None)

        print(f"invalid selection: {raw}")


_INPUT_LOCK = threading.Lock()


def _start_tty_watcher(
    tollbooth: "Any",
    poll_interval: float = 0.2,
    input_fn=input,
) -> threading.Thread:
    handled_tickets = set()

    def _watcher_loop():
        while True:
            time.sleep(poll_interval)
            if not tollbooth.enabled:
                continue
            pending = list(tollbooth._pending.values())
            for ticket in pending:
                if ticket.ticket_id in handled_tickets:
                    continue
                handled_tickets.add(ticket.ticket_id)
                if ticket.ticket_id not in tollbooth._pending:
                    continue
                with _INPUT_LOCK:
                    if ticket.ticket_id not in tollbooth._pending:
                        continue
                    tui.console.print(_render_route_menu(ticket))
                    try:
                        res = _prompt_choice(len(ticket.options), input_fn=input_fn)
                        if res is not None:
                            opt_idx, effort_override = res
                            chosen_opt = ticket.options[opt_idx]
                            tollbooth.answer_ticket(
                                ticket.ticket_id,
                                chosen_opt.target,
                                effort_canonical=effort_override,
                            )
                            tui.console.print(f"toll answered: {chosen_opt.target}")
                    except (EOFError, KeyboardInterrupt):
                        pass
                    except Exception:
                        pass

    t = threading.Thread(target=_watcher_loop, daemon=True, name="tollbooth-tty-watcher")
    t.start()
    return t


def cmd_choose(
    args: argparse.Namespace | None = None,
    queue_path: Path | None = None,
    answers_dir: Path | None = None,
    presence_path: Path | None = None,
    input_fn=input,
) -> None:
    q_path = queue_path or getattr(args, "queue_path", None) or PENDING_TOLLS_PATH
    ans_dir = answers_dir or getattr(args, "answers_dir", None) or TOLL_ANSWERS_DIR
    pres_path = presence_path or getattr(args, "presence_path", None) or PRESENCE_PATH

    try:
        pres_path.parent.mkdir(parents=True, exist_ok=True)
        pres_path.write_text(json.dumps({"ts": time.time(), "surface": "choose"}))
    except Exception:
        pass

    if not q_path.exists():
        tui.console.print("[dim]no pending tolls[/dim]")
        return

    while True:
        if not q_path.exists():
            tui.console.print("[dim]no pending tolls[/dim]")
            return
        lines = [l.strip() for l in q_path.read_text().splitlines() if l.strip()]
        if not lines:
            tui.console.print("[dim]no pending tolls[/dim]")
            return

        ticket_data = json.loads(lines[0])
        ticket_id = ticket_data.get("ticket_id")
        options = ticket_data.get("options", [])
        if not options:
            tui.console.print("[dim]no pending tolls[/dim]")
            return

        tui.console.print(_render_route_menu(ticket_data))
        res = _prompt_choice(len(options), input_fn=input_fn)
        if res is None:
            break

        opt_idx, effort_override = res
        chosen_opt = options[opt_idx]
        target = chosen_opt.get("target") if isinstance(chosen_opt, dict) else chosen_opt.target
        choice_str = "human:local" if target == "local" else f"human:frontier:{target}"

        ans_dir.mkdir(parents=True, exist_ok=True)
        ans_file = ans_dir / f"{ticket_id}.json"
        ans_file.write_text(
            json.dumps(
                {
                    "choice": choice_str,
                    "effort_canonical": effort_override,
                    "ts": time.time(),
                }
            )
        )
        tui.console.print(f"toll answered: {choice_str}")
        try:
            pres_path.write_text(json.dumps({"ts": time.time(), "surface": "choose"}))
        except Exception:
            pass

        time.sleep(0.15)
        new_lines = [l.strip() for l in q_path.read_text().splitlines() if l.strip()]
        if len(new_lines) <= 1 and (not new_lines or json.loads(new_lines[0]).get("ticket_id") == ticket_id):
            break


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from kultivait.server import create_app
    from kultivait.tollbooth import TollboothQueue

    config = get_config()
    print("cultivating centroids from seed prompts...", file=sys.stderr)
    escalations = EscalationStore(ESCALATIONS_DIR)
    ledger = Ledger(LEDGER_PATH)
    tollbooth = TollboothQueue(
        queue_path=PENDING_TOLLS_PATH,
        presence_path=PRESENCE_PATH,
        answers_dir=TOLL_ANSWERS_DIR,
        default_timeout_s=config.toll_timeout_s,
        enabled=config.toll_enabled,
        escalations=escalations,
        ledger=ledger,
    )
    if _stdin_is_tty():
        tollbooth.register_presence("tty")
        _start_tty_watcher(tollbooth)

    app = create_app(
        router=build_router(config),
        embed=lambda text: _embed_batch(config, [text])[0],
        backends=build_backends(config),
        ledger=ledger,
        gate=build_gate(config),
        escalations=escalations,
        preprocess_timeout_s=config.preprocess_timeout_s,
        tollbooth=tollbooth,
        toll_timeout_s=config.toll_timeout_s,
        toll_enabled=config.toll_enabled,
    )
    port = args.port or config.port
    print(f"kultivait listening on http://localhost:{port}", file=sys.stderr)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def cmd_route(args: argparse.Namespace) -> None:
    config = get_config()
    router = build_router(config)
    decision = router.classify(_embed_batch(config, [args.prompt])[0])
    print(json.dumps(decision.__dict__, indent=2))


def cmd_prune(args: argparse.Namespace) -> None:
    transcript = Path(args.file).read_text() if args.file else sys.stdin.read()
    result = build_gate(get_config()).distill(
        transcript, from_phase=args.from_phase, to_phase=args.to_phase
    )
    print(result.brief)
    print(
        f"\n--- pruned {result.tokens_before} -> {result.tokens_after} tokens "
        f"({100 * (1 - result.tokens_after / result.tokens_before):.0f}% composted, "
        f"recoverable: {result.compost_id})",
        file=sys.stderr,
    )


def cmd_escalations(args: argparse.Namespace) -> None:
    import datetime

    store = EscalationStore(ESCALATIONS_DIR)
    listed = store.list()
    if not listed:
        print("no escalations recorded — the local garden has been enough")
        return

    if not args.brief:
        for e in listed:
            when = datetime.datetime.fromtimestamp(e.ts).strftime("%m-%d %H:%M")
            print(f"{e.id}  {when}  wanted {e.requested_tier:<12}  {e.snippet}")
        print(f"\n{len(listed)} escalation(s). Distill one: kultivait escalations --brief [ID]")
        return

    config = get_config()
    target = args.id or listed[-1].id
    record = next(e for e in listed if e.id == target)
    transcript = render_transcript(store.load_messages(target))
    print(f"distilling {target} with {config.distill_model}...", file=sys.stderr)
    gate = build_gate(config, template=HANDOFF_PROMPT)
    result = gate.distill(transcript, from_phase="local", to_phase="cloud")
    print(f"# Escalation brief — take this to {recommended_target(record.requested_tier)}\n")
    print(result.brief)
    print(
        f"\n--- {result.tokens_before} -> {result.tokens_after} tokens · "
        f"full conversation recoverable: {target}",
        file=sys.stderr,
    )


def format_harvest(stats: dict) -> str:
    if stats["prompts"] == 0:
        return (
            "the harvest — nothing planted yet\n"
            "  start the proxy (kultivait serve) and route some work through it."
        )
    local_pct = round(100 * stats["local_prompts"] / stats["prompts"])
    notional_spent = stats.get("notional_spent_usd", stats.get("spent_usd", 0.0))
    metered_spent = stats.get("metered_spent_usd", 0.0)
    lines = [
        "the harvest — season to date",
        "",
        f"  prompts routed     {stats['prompts']}  ({local_pct}% local)",
        f"  local tokens       {stats['tokens_local']:,}",
        f"  spent              ${stats['spent_usd']:.2f}",
        f"  frontier baseline  ${stats['baseline_usd']:.2f}",
        f"  notional spent     ${notional_spent:.2f}",
        f"  metered cash out   ${metered_spent:.2f}",
        f"  kept in pocket     ${stats['saved_usd']:.2f}",
    ]
    toll = stats.get("toll_activity")
    if toll and (
        toll.get("fired", 0) > 0
        or toll.get("answered", 0) > 0
        or toll.get("expired", 0) > 0
        or toll.get("skipped", 0) > 0
        or any(toll.get("preprocess_marks", {}).values())
        or bool(toll.get("route_choices"))
    ):
        toll_rate_pct = round(100 * toll.get("toll_rate", 0.0))
        lines += [
            "",
            "  toll activity",
            f"    tolls fired        {toll.get('fired', 0)}  ({toll_rate_pct}% toll rate)",
            f"    answered {toll.get('answered', 0)}, expired {toll.get('expired', 0)}, skipped {toll.get('skipped', 0)}",
        ]
        rcs = toll.get("route_choices", {})
        if rcs:
            lines.append("    route choices:")
            for choice, count in rcs.items():
                if count > 0:
                    lines.append(f"      {choice:<22} {count}")
        marks = toll.get("preprocess_marks", {})
        if marks and any(marks.values()):
            lines.append(
                f"    preprocessor marks  ok: {marks.get('ok', 0)}, skipped: {marks.get('skipped', 0)}, timeout: {marks.get('timeout', 0)}, fail: {marks.get('fail', 0)}"
            )

    esc = stats.get("escalations", {"count": 0, "recent": []})
    if esc["count"]:
        lines += ["", f"  {esc['count']} cloud-worthy prompt(s) served locally:"]
        for e in esc["recent"]:
            lines.append(f"    wanted {e['requested']}, served {e['served']}: {e['snippet']}")
        lines.append("    distill a handoff: kultivait escalations --brief")
    if stats.get("truncated_inputs"):
        lines += ["", f"  ⚠ {stats['truncated_inputs']} input(s) hit the context ceiling (raise num_ctx?)"]
    return "\n".join(lines)


def cmd_harvest(args: argparse.Namespace) -> None:
    stats = Ledger(LEDGER_PATH).harvest()
    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        print(format_harvest(stats))


def cmd_distill_corpus(args: argparse.Namespace) -> None:
    """D1 demo surface: materialize the anchor set + held-out roster from a
    harvest directory (default: the live ~/.kultivait)."""
    from kultivait.distill import dry_run_report

    report = dry_run_report(Path(args.harvest_dir))
    print(json.dumps(report, indent=2))


def cmd_distill_generate(args: argparse.Namespace) -> None:
    """D2: run the dual-teacher generator. --live dispatches real CLI teachers
    (subscription; ledger-tagged); without it the command refuses — synthetic
    training data comes from teachers, never silently from a stub."""
    from kultivait.distill.corpus import load_harvest, split_heldout, write_corpus
    from kultivait.distill.generator import generate_corpus, real_teacher_fns

    if not args.live:
        print("refusing to generate without --live: teacher dispatches are real "
              "(subscription CLIs, ledger-tagged). Re-run with --live.")
        return
    entries, escalations = load_harvest(Path(args.harvest_dir))
    from kultivait.distill.corpus import extract_anchors
    seeds, heldout = split_heldout(extract_anchors(entries, escalations, []))
    if not seeds:
        print("no seed anchors in the harvest (escalation pool empty)")
        return
    fns = real_teacher_fns(judge_cli=args.judge_cli, rewriter_cli=args.rewriter_cli)
    rng = random.Random(args.seed)

    def ledger_tag(**entry):
        ledger = Ledger(LEDGER_PATH)
        ledger.record(**entry)

    report = generate_corpus(
        seeds, vary_fn=fns["vary_fn"], label_fn=fns["label_fn"],
        rewrite_fn=fns["rewrite_fn"], target_pairs=args.target_pairs, rng=rng,
        ledger_record=ledger_tag,
    )
    out = Path(args.out_dir)
    write_corpus(report.pairs, [], out, heldout=heldout)
    print(json.dumps({"out_dir": str(out), "pairs": len(report.pairs),
                      "stats": report.stats}, indent=2))


def cmd_eval(args: argparse.Namespace) -> None:
    from kultivait.capability_eval import (
        format_eval_summary,
        load_corpus,
        run_capability_eval,
    )

    config = get_config()
    backends = build_backends(config)
    if not backends:
        print("no backends configured for capability eval.", file=sys.stderr)
        return

    targets = [args.target] if getattr(args, "target", None) else None
    efforts = [args.effort] if getattr(args, "effort", None) else None
    corpus_path = Path(args.corpus) if getattr(args, "corpus", None) else None
    artifacts_dir = Path(args.artifacts_dir) if getattr(args, "artifacts_dir", None) else Path(".kultivait/eval_artifacts")
    ledger = Ledger(LEDGER_PATH)

    summary = run_capability_eval(
        backends=backends,
        targets=targets,
        efforts=efforts,
        corpus=load_corpus(corpus_path) if corpus_path else None,
        artifacts_dir=artifacts_dir,
        ledger=ledger,
    )
    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2))
    else:
        print(format_eval_summary(summary))


def main() -> None:
    parser = argparse.ArgumentParser(prog="kultivait")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="survey this machine and write config")
    init.add_argument(
        "--no-setup", action="store_true", help="never offer to install or download anything"
    )
    init.add_argument(
        "--setup",
        action="store_true",
        help="reopen the setup screen even if onboarding is complete",
    )
    init.set_defaults(func=cmd_init)

    serve = sub.add_parser("serve", help="run the routing proxy")
    serve.add_argument("--port", type=int, default=None)
    serve.set_defaults(func=cmd_serve)

    route = sub.add_parser("route", help="classify a prompt without executing it")
    route.add_argument("prompt")
    route.set_defaults(func=cmd_route)

    prune = sub.add_parser("prune", help="distill a transcript into a handoff brief")
    prune.add_argument("file", nargs="?", help="transcript file (default: stdin)")
    prune.add_argument("--from", dest="from_phase", default="previous")
    prune.add_argument("--to", dest="to_phase", default="next")
    prune.set_defaults(func=cmd_prune)

    esc = sub.add_parser(
        "escalations", help="list cloud-worthy prompts served locally; distill a handoff brief"
    )
    esc.add_argument("id", nargs="?", help="escalation id (default: most recent)")
    esc.add_argument("--brief", action="store_true", help="distill a paste-ready brief")
    esc.set_defaults(func=cmd_escalations)

    harvest = sub.add_parser("harvest", help="show cumulative savings")
    harvest.add_argument("--json", action="store_true", help="machine-readable output")
    harvest.set_defaults(func=cmd_harvest)

    distill = sub.add_parser("distill", help="distillation pipeline operations")
    distill_sub = distill.add_subparsers(dest="distill_cmd")
    corpus_cmd = distill_sub.add_parser("corpus", help="assemble the corpus from the harvest")
    corpus_cmd.add_argument("--dry-run", action="store_true",
                            help="print anchors, strata, and the held-out roster")
    corpus_cmd.add_argument("--harvest-dir", default=str(KULTIVAIT_HOME),
                            help="harvest directory (default ~/.kultivait)")
    corpus_cmd.set_defaults(func=cmd_distill_corpus)
    gen_cmd = distill_sub.add_parser("generate", help="run the dual-teacher synthetic generator")
    gen_cmd.add_argument("--live", action="store_true",
                         help="dispatch real CLI teachers (subscription; ledger-tagged)")
    gen_cmd.add_argument("--target-pairs", type=int, default=1500,
                         help="target corpus size (strata-exact quotas)")
    gen_cmd.add_argument("--out-dir", default=str(KULTIVAIT_HOME / "distill-corpus"),
                         help="output directory for train/valid JSONL + sidecars")
    gen_cmd.add_argument("--harvest-dir", default=str(KULTIVAIT_HOME),
                         help="harvest directory for seed anchors")
    gen_cmd.add_argument("--judge-cli", default="opencode", help="judge teacher CLI (neutral family)")
    gen_cmd.add_argument("--rewriter-cli", default="claude", help="rewriter teacher CLI")
    gen_cmd.add_argument("--seed", type=int, default=42, help="rng seed")
    gen_cmd.set_defaults(func=cmd_distill_generate)

    choose = sub.add_parser("choose", help="answer pending tolls out-of-band")
    choose.set_defaults(func=cmd_choose)

    eval_cmd = sub.add_parser("eval", help="run direct-to-backend capability evaluation")
    eval_cmd.add_argument("--target", help="specific target backend to evaluate")
    eval_cmd.add_argument("--effort", choices=["fast", "balanced", "deep"], help="specific effort level")
    eval_cmd.add_argument("--corpus", help="path to custom corpus JSON file")
    eval_cmd.add_argument("--artifacts-dir", help="directory to write per-case artifact JSONs")
    eval_cmd.add_argument("--json", action="store_true", help="machine-readable summary output")
    eval_cmd.set_defaults(func=cmd_eval)

    bench_cmd = sub.add_parser("benchmark", help="alias for eval")
    bench_cmd.add_argument("--target", help="specific target backend to evaluate")
    bench_cmd.add_argument("--effort", choices=["fast", "balanced", "deep"], help="specific effort level")
    bench_cmd.add_argument("--corpus", help="path to custom corpus JSON file")
    bench_cmd.add_argument("--artifacts-dir", help="directory to write per-case artifact JSONs")
    bench_cmd.add_argument("--json", action="store_true", help="machine-readable summary output")
    bench_cmd.set_defaults(func=cmd_eval)

    args = parser.parse_args()
    args.func(args)



if __name__ == "__main__":
    main()
