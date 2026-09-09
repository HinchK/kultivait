"""Energy sanity eval — runs the protocol in protocol.md.

E1-E3, E5-E6 evaluate repo state directly; E4 drives one live rehearsal
dispatch through a real proxy (isolated HOME, port 4514). Writes
gates.json + prints the verdict table.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from kultivait import energy  # noqa: E402
from kultivait.ledger import Ledger  # noqa: E402
from kultivait.cli import format_harvest  # noqa: E402

ORDER = ["1.5b", "3b", "4b", "8b", "14b"]


def gate(name, ok, detail):
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    return ok


def main() -> None:
    results: dict[str, bool] = {}

    # E1 coefficient bounds
    e1 = True
    for cls in ORDER:
        decode = energy.CLASSES[cls][1]
        lo, hi = (0.10, 0.50) if cls == "14b" else (0.003, 0.35)
        e1 = gate(f"E1 {cls} decode {decode:.5f} in [{lo}, {hi}]", lo <= decode <= hi, "") and e1
    results["E1"] = e1

    # E2 monotonicity
    decodes = [energy.CLASSES[c][1] for c in ORDER]
    mono = all(a < b for a, b in zip(decodes, decodes[1:]))
    results["E2"] = gate("E2 decode strictly monotone", mono,
                         " < ".join(f"{d:.3f}" for d in decodes))

    # E3 sum consistency (synthetic ledger mirroring the live schema)
    tmp = HERE / "run"
    tmp.mkdir(exist_ok=True)
    ledger = Ledger(tmp / "ledger.jsonl")
    for row in [
        {"est_wh": 0.0123, "energy_model": energy.TABLE_VERSION},
        {"est_wh": 0.4567, "energy_model": energy.TABLE_VERSION,
         "preprocess_model": "kv-judge-x"},
        {"local": False, "est_wh": 0.0, "energy_model": energy.TABLE_VERSION},
        {"est_wh": 0.1001, "energy_model": "energy-v0-legacy"},
    ]:
        base = dict(tier="llama3.1:8b", local=True, tokens_in=100, tokens_out=50, cost_usd=0.0)
        base.update(row)
        ledger.record(**base)
    e = ledger.harvest()["energy"]
    expected = 0.0123 + 0.4567 + 0.1001
    ok3 = abs(e["est_wh"] - expected) < 1e-9 and e["dispatches"] == 3
    results["E3"] = gate("E3 harvest sum == local rows", ok3,
                         f"{e['est_wh']:.6f} vs {expected:.6f}, dsp {e['dispatches']}")

    # E4 live rehearsal: real proxy, real local dispatch, isolated HOME
    import httpx
    import tempfile
    import os

    home = Path(tempfile.mkdtemp(prefix="kultivait-energy-eval-"))
    home.mkdir(exist_ok=True)
    env = {**os.environ, "HOME": str(home)}
    serve = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "kultivait.server:app"],
        env=env, cwd=str(Path(__file__).resolve().parents[2]),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    # uvicorn needs the factory; fall back to the CLI entry if import fails
    time.sleep(0.5)
    if serve.poll() is not None:
        serve = subprocess.Popen(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'src'); "
             "from kultivait.cli import main; main(['serve', '--port', '4514'])"],
            env=env, cwd=str(Path(__file__).resolve().parents[2]),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    try:
        deadline = time.time() + 30
        ready = False
        while time.time() < deadline and not ready:
            try:
                httpx.get("http://localhost:4514/v1/models", timeout=2)
                ready = True
            except Exception:
                time.sleep(1)
        assert ready, "rehearsal proxy never came up"
        resp = httpx.post(
            "http://localhost:4514/v1/chat/completions",
            json={"model": "kultivait", "max_tokens": 12,
                  "messages": [{"role": "user", "content": "Reply with exactly: ok"}]},
            timeout=120,
        )
        assert resp.status_code == 200, resp.text[:200]
        row_txt = (home / ".kultivait" / "ledger.jsonl").read_text().splitlines()[-1]
        row = json.loads(row_txt)
        live_ok = (
            row.get("est_wh", 0) > 0
            and row.get("energy_model") == energy.TABLE_VERSION
            and row.get("latency_s", 0) > 0
        )
        # E5 render invariants on the live ledger
        live_ledger = Ledger(home / ".kultivait" / "ledger.jsonl")
        out = format_harvest(live_ledger.harvest())
        render_ok = (
            f"energy (estimated · {energy.TABLE_VERSION})" in out
            and "Wh" in out
        )
        results["E4"] = gate("E4 live dispatch carries est_wh/model/latency",
                             live_ok,
                             f"est_wh={row.get('est_wh')}, latency_s={row.get('latency_s')}")
        results["E5"] = gate("E5 render labels + version", render_ok,
                             "header literal present" if render_ok else out[:200])
    finally:
        serve.terminate()
        try:
            serve.wait(timeout=10)
        except Exception:
            serve.kill()

    # E6 dashboard template + payload shape
    tpl = Path("src/kultivait/dashboard/index.html").read_text()
    e6 = ("energy-wh" in tpl and "est." in tpl
          and "setInterval" not in tpl and "setTimeout" not in tpl)
    results["E6"] = gate("E6 dashboard panel + no timers", e6, "")

    (HERE / "gates.json").write_text(json.dumps(results, indent=2))
    print("\nALL GATES PASS" if all(results.values()) else "\nGATE FAILURE(S)")


if __name__ == "__main__":
    main()
