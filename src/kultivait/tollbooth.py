"""Tollbooth Core: pending-tolls queue, presence tracking, route menu building,
and auto-policy resolution for contested routing verdicts.
"""

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from kultivait.config import CLI_PRICING, KNOWN_CLIS, PROVIDER_DEFAULTS
from kultivait.effort import EffortPlan, resolve_effort
from kultivait.escalations import EscalationStore
from kultivait.ledger import Ledger
from kultivait.preprocessor import AnalysisResult, TargetFit


@dataclass(frozen=True)
class RouteOption:
    target: str            # "claude" | "agy" | "codex" | "opencode" | "gemini" | "openrouter" | "openai" | "anthropic" | "local"
    display_name: str
    fit: float
    effort: EffortPlan
    estimated_cost_usd: float
    prompt_to_send: str    # rewritten prompt for frontier, original for local
    cash_annotation: str = "$0"
    kind: str = "cli"      # "api" | "cli" | "local"


@dataclass(frozen=True)
class TollTicket:
    ticket_id: str
    fingerprint: str
    created_at: float
    timeout_s: float
    options: list[RouteOption]
    default_auto_choice: str
    original_prompt: str = ""
    task_type: str = ""
    complexity: int = 0


def build_route_menu(
    target_fits: list[TargetFit],
    installed_clis: list[str] | None = None,
    analysis: AnalysisResult | None = None,
    rewrite: str = "",
    original_prompt: str = "",
    local_tier_name: str = "qwen3.5:4b",
    pricing: dict[str, tuple[float, float]] | None = None,
    effort_overrides: dict | None = None,
    candidate_targets: list[str] | None = None,
    target_kinds: dict[str, str] | None = None,
    has_tools: bool = False,
    probed_status: dict[str, bool] | None = None,
) -> list[RouteOption]:
    """Constructs route menu offering top 3 installed frontier targets ranked by
    total order (fit desc -> task_type capability match -> price asc) + local anchor."""
    prices = dict(pricing or CLI_PRICING)
    for p_name, p_def in PROVIDER_DEFAULTS.items():
        if p_name not in prices:
            prices[p_name] = (p_def.price_in, p_def.price_out)

    fit_map = {tf.target: tf.fit for tf in (target_fits or [])}
    raw_targets = list(candidate_targets if candidate_targets is not None else (installed_clis or []))
    kinds_map = target_kinds or {}

    surviving = []
    for t in raw_targets:
        # If probed and failed, drop from menu
        if probed_status is not None and probed_status.get(t) is False:
            continue
        t_kind = kinds_map.get(t, "api" if t in ("openrouter", "openai", "anthropic") else "cli")
        # Capability filter: drop CLI targets when request bears tools
        if has_tools and t_kind == "cli":
            continue
        surviving.append(t)

    def rank_key(target: str):
        fit = fit_map.get(target, 0.0)
        role = KNOWN_CLIS.get(target, "architect")
        if analysis and analysis.task_type in ("architecture", "debugging", "compound"):
            cap_score = 0 if role == "architect" else 1
        elif analysis and analysis.task_type in ("docs_lookup", "simple_edit"):
            cap_score = 0 if role == "docs" else 1
        else:
            cap_score = 0

        p_in, p_out = prices.get(target, (3.0, 15.0))
        price_sum = p_in + p_out
        return (-fit, cap_score, price_sum, target)

    ranked_targets = sorted(surviving, key=rank_key)[:3]

    options: list[RouteOption] = []
    tokens_in_est = max(1, len(rewrite) // 4)
    tokens_out_est = max(1, len(rewrite) // 8)

    for target in ranked_targets:
        fit = fit_map.get(target, 0.0)
        effort = resolve_effort(
            complexity=analysis.complexity if analysis else 5,
            task_type=analysis.task_type if analysis else "code",
            target_cli=target,
            overrides=effort_overrides,
        )
        p_in, p_out = prices.get(target, (3.0, 15.0))
        cost = (tokens_in_est * p_in + tokens_out_est * p_out) / 1e6
        t_kind = kinds_map.get(target, "api" if target in ("openrouter", "openai", "anthropic") else "cli")
        if t_kind == "api":
            cash_annot = f"metered: ~${cost:.4f}"
        elif t_kind == "cli":
            cash_annot = "subscription: $0"
        else:
            cash_annot = "$0"

        options.append(
            RouteOption(
                target=target,
                display_name=target.capitalize(),
                fit=fit,
                effort=effort,
                estimated_cost_usd=cost,
                prompt_to_send=rewrite,
                cash_annotation=cash_annot,
                kind=t_kind,
            )
        )

    # 4th option: keep-it-local anchor
    local_effort = resolve_effort(
        complexity=analysis.complexity if analysis else 5,
        task_type=analysis.task_type if analysis else "code",
        target_cli="local",
        overrides=effort_overrides,
    )
    options.append(
        RouteOption(
            target="local",
            display_name=f"Local ({local_tier_name})",
            fit=0.0,
            effort=local_effort,
            estimated_cost_usd=0.0,
            prompt_to_send=original_prompt,
            cash_annotation="$0",
            kind="local",
        )
    )

    return options


def resolve_auto_policy(
    options: list[RouteOption],
    local_serving_capable: bool = True,
) -> str:
    """Resolves default auto-policy route: local-first if serving-capable,
    otherwise highest ranked frontier target."""
    if local_serving_capable:
        return "auto:local"
    frontier_opts = [opt for opt in options if opt.target != "local"]
    if frontier_opts:
        return f"auto:frontier:{frontier_opts[0].target}"
    raise RuntimeError("no capable backend configured to serve request")


class TollboothQueue:
    def __init__(
        self,
        queue_path: Path | None = None,
        presence_path: Path | None = None,
        answers_dir: Path | None = None,
        default_timeout_s: float = 60.0,
        presence_timeout_s: float = 300.0,
        sticky_ttl_s: float = 3600.0,
        enabled: bool = True,
        escalations: EscalationStore | None = None,
        ledger: Ledger | None = None,
    ):
        self.queue_path = Path(queue_path) if queue_path else None
        if presence_path:
            self.presence_path = Path(presence_path)
        elif self.queue_path:
            self.presence_path = self.queue_path.parent / "presence.json"
        else:
            self.presence_path = None

        if answers_dir:
            self.answers_dir = Path(answers_dir)
        elif self.queue_path:
            self.answers_dir = self.queue_path.parent / "toll_answers"
        else:
            self.answers_dir = None

        self.default_timeout_s = default_timeout_s
        self.presence_timeout_s = presence_timeout_s
        self.sticky_ttl_s = sticky_ttl_s
        self.enabled = enabled
        self.escalations = escalations
        self.ledger = ledger

        self._last_presence_ts: float = 0.0
        self._last_surface: str = ""
        self._pending: dict[str, TollTicket] = {}
        self._sync_events: dict[str, threading.Event] = {}
        self._async_events: dict[str, asyncio.Event] = {}
        self._results: dict[str, str] = {}
        self._effort_overrides: dict[str, str | None] = {}
        self._sticky_cache: dict[str, tuple[str, str | None, float]] = {}  # fingerprint -> (choice, effort_override, ts)
        self._counterfactuals: list[dict] = []

        if self.queue_path and self.queue_path.exists():
            try:
                self.queue_path.unlink()
            except OSError:
                pass

    def register_presence(self, surface: str = "tty") -> None:
        self._last_presence_ts = time.time()
        self._last_surface = surface
        if self.presence_path:
            try:
                self.presence_path.parent.mkdir(parents=True, exist_ok=True)
                self.presence_path.write_text(
                    json.dumps({"ts": self._last_presence_ts, "surface": surface})
                )
            except Exception:
                pass

    def has_presence(self, timeout_s: float | None = None) -> bool:
        limit = timeout_s if timeout_s is not None else self.presence_timeout_s
        now = time.time()
        if (now - self._last_presence_ts) <= limit:
            return True
        if self.presence_path and self.presence_path.exists():
            try:
                data = json.loads(self.presence_path.read_text())
                ts = float(data.get("ts", self.presence_path.stat().st_mtime))
                if (now - ts) <= limit:
                    return True
            except Exception:
                try:
                    if (now - self.presence_path.stat().st_mtime) <= limit:
                        return True
                except Exception:
                    pass
        return False

    @staticmethod
    def _normalize_choice(choice: str) -> str:
        if choice.startswith("human:") or choice.startswith("auto:"):
            return choice
        if choice == "local":
            return "human:local"
        return f"human:frontier:{choice}"

    def _check_and_consume_answer_file(self, ticket_id: str) -> bool:
        if not self.answers_dir:
            return False
        ans_path = self.answers_dir / f"{ticket_id}.json"
        if ans_path.exists():
            try:
                data = json.loads(ans_path.read_text())
                ans_path.unlink(missing_ok=True)
                choice = data.get("choice", "")
                effort_canonical = data.get("effort_canonical")
                return self.answer_ticket(ticket_id, choice, effort_canonical=effort_canonical)
            except Exception:
                pass
        return False

    def hold_ticket(self, ticket: TollTicket) -> tuple[str, str, str | None]:
        """Synchronous hold: waits up to ticket.timeout_s on presence, returns (choice, mark, effort_override)."""
        if not self.enabled:
            return ticket.default_auto_choice, "skipped", None

        if ticket.fingerprint in self._sticky_cache:
            choice, effort_override, cached_ts = self._sticky_cache[ticket.fingerprint]
            if time.time() - cached_ts <= self.sticky_ttl_s:
                return choice, "sticky", effort_override
            else:
                del self._sticky_cache[ticket.fingerprint]

        if not self.has_presence():
            self._archive_missed_menu(ticket, choice=ticket.default_auto_choice, reason="no_presence")
            return ticket.default_auto_choice, "expired", None

        event = threading.Event()
        self._pending[ticket.ticket_id] = ticket
        self._sync_events[ticket.ticket_id] = event
        self._write_queue_file()

        deadline = time.time() + ticket.timeout_s
        mark = "expired"
        choice = ticket.default_auto_choice
        effort_override = None

        try:
            while time.time() < deadline:
                if event.is_set():
                    choice = self._results.get(ticket.ticket_id, ticket.default_auto_choice)
                    effort_override = self._effort_overrides.get(ticket.ticket_id)
                    mark = "answered"
                    break
                if self._check_and_consume_answer_file(ticket.ticket_id):
                    choice = self._results.get(ticket.ticket_id, ticket.default_auto_choice)
                    effort_override = self._effort_overrides.get(ticket.ticket_id)
                    mark = "answered"
                    break
                remaining = max(0.0, deadline - time.time())
                slice_wait = min(0.1, remaining)
                if event.wait(timeout=slice_wait):
                    choice = self._results.get(ticket.ticket_id, ticket.default_auto_choice)
                    effort_override = self._effort_overrides.get(ticket.ticket_id)
                    mark = "answered"
                    break

            if mark == "expired":
                self._archive_missed_menu(ticket, choice=choice, reason="timeout")
        finally:
            self._pending.pop(ticket.ticket_id, None)
            self._sync_events.pop(ticket.ticket_id, None)
            self._results.pop(ticket.ticket_id, None)
            self._effort_overrides.pop(ticket.ticket_id, None)
            self._write_queue_file()

        return choice, mark, effort_override

    async def hold_ticket_async(self, ticket: TollTicket) -> tuple[str, str, str | None]:
        """Async hold: awaits up to ticket.timeout_s on presence, returns (choice, mark, effort_override)."""
        if not self.enabled:
            return ticket.default_auto_choice, "skipped", None

        if ticket.fingerprint in self._sticky_cache:
            choice, effort_override, cached_ts = self._sticky_cache[ticket.fingerprint]
            if time.time() - cached_ts <= self.sticky_ttl_s:
                return choice, "sticky", effort_override
            else:
                del self._sticky_cache[ticket.fingerprint]

        if not self.has_presence():
            self._archive_missed_menu(ticket, choice=ticket.default_auto_choice, reason="no_presence")
            return ticket.default_auto_choice, "expired", None

        async_event = asyncio.Event()
        sync_event = threading.Event()
        self._pending[ticket.ticket_id] = ticket
        self._async_events[ticket.ticket_id] = async_event
        self._sync_events[ticket.ticket_id] = sync_event
        self._write_queue_file()

        deadline = time.time() + ticket.timeout_s
        mark = "expired"
        choice = ticket.default_auto_choice
        effort_override = None

        try:
            while time.time() < deadline:
                if async_event.is_set():
                    choice = self._results.get(ticket.ticket_id, ticket.default_auto_choice)
                    effort_override = self._effort_overrides.get(ticket.ticket_id)
                    mark = "answered"
                    break
                if self._check_and_consume_answer_file(ticket.ticket_id):
                    choice = self._results.get(ticket.ticket_id, ticket.default_auto_choice)
                    effort_override = self._effort_overrides.get(ticket.ticket_id)
                    mark = "answered"
                    break
                remaining = max(0.0, deadline - time.time())
                slice_wait = min(0.1, remaining)
                try:
                    await asyncio.wait_for(async_event.wait(), timeout=slice_wait)
                    choice = self._results.get(ticket.ticket_id, ticket.default_auto_choice)
                    effort_override = self._effort_overrides.get(ticket.ticket_id)
                    mark = "answered"
                    break
                except asyncio.TimeoutError:
                    pass

            if mark == "expired":
                self._archive_missed_menu(ticket, choice=choice, reason="timeout")
        finally:
            self._pending.pop(ticket.ticket_id, None)
            self._async_events.pop(ticket.ticket_id, None)
            self._sync_events.pop(ticket.ticket_id, None)
            self._results.pop(ticket.ticket_id, None)
            self._effort_overrides.pop(ticket.ticket_id, None)
            self._write_queue_file()

        return choice, mark, effort_override

    def answer_ticket(
        self,
        ticket_id: str,
        choice: str,
        effort_canonical: str | None = None,
    ) -> bool:
        """Answers a pending ticket. Wakes waiters and caches sticky choice.
        If ticket already expired, records counterfactual and returns False."""
        norm_choice = self._normalize_choice(choice)
        if ticket_id in self._pending:
            ticket = self._pending[ticket_id]
            self._results[ticket_id] = norm_choice
            self._effort_overrides[ticket_id] = effort_canonical
            self._sticky_cache[ticket.fingerprint] = (norm_choice, effort_canonical, time.time())

            if ticket_id in self._sync_events:
                self._sync_events[ticket_id].set()
            if ticket_id in self._async_events:
                self._async_events[ticket_id].set()
            return True

        cf = {
            "ticket_id": ticket_id,
            "ts": time.time(),
            "choice": norm_choice,
            "effort_canonical": effort_canonical,
        }
        self._counterfactuals.append(cf)
        return False

    def _archive_missed_menu(self, ticket: TollTicket, choice: str, reason: str) -> None:
        if not self.escalations:
            return
        record_data = {
            "ticket_id": ticket.ticket_id,
            "fingerprint": ticket.fingerprint,
            "missed_at": time.time(),
            "reason": reason,
            "auto_choice": choice,
            "original_prompt": ticket.original_prompt,
            "complexity": ticket.complexity,
            "task_type": ticket.task_type,
            "options": [
                {
                    "target": opt.target,
                    "display_name": opt.display_name,
                    "fit": opt.fit,
                    "effort": opt.effort.canonical,
                    "cli_flags": opt.effort.cli_flags,
                    "model_override": opt.effort.model_override,
                    "estimated_cost_usd": opt.estimated_cost_usd,
                }
                for opt in ticket.options
            ],
        }
        if hasattr(self.escalations, "_dir"):
            menu_file = self.escalations._dir / f"menu-{ticket.ticket_id}.json"
            self.escalations._dir.mkdir(parents=True, exist_ok=True)
            menu_file.write_text(json.dumps(record_data, indent=2))

    def _write_queue_file(self) -> None:
        if not self.queue_path:
            return
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for t in self._pending.values():
            data = {
                "ticket_id": t.ticket_id,
                "fingerprint": t.fingerprint,
                "created_at": t.created_at,
                "timeout_s": t.timeout_s,
                "default_auto_choice": t.default_auto_choice,
                "original_prompt": t.original_prompt,
                "task_type": t.task_type,
                "complexity": t.complexity,
                "options": [
                    {
                        "target": o.target,
                        "display_name": o.display_name,
                        "fit": o.fit,
                        "effort": o.effort.canonical,
                        "cli_flags": o.effort.cli_flags,
                        "model_override": o.effort.model_override,
                        "estimated_cost_usd": o.estimated_cost_usd,
                        "prompt_to_send": o.prompt_to_send,
                    }
                    for o in t.options
                ],
            }
            lines.append(json.dumps(data))
        self.queue_path.write_text("\n".join(lines) + ("\n" if lines else ""))
