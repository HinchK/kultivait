# Distillation targets: the whole preprocessor contract on one model, toll-rate headline, two-base bake-off

V1 distills the **entire preprocessor single-call contract as one model** — judge (target fits + confidence, the fields verdicts derive from), analyzer (task_type, complexity, signals), and rewriter together — not the judge alone, not a routing classifier, not separate specialists. The single-call analyze→rewrite→judge shape (ADR-era decision #7) is preserved verbatim; the distillate serves the same JSON contract at the same seam, so deployment is a `preprocess_model` swap and the flywheel proves out on the smallest serving surface that still covers the whole observed weakness. The headline success metric is **toll-rate reduction against the incumbent on a held-out eval set** (verdict_eval methodology): a better-calibrated judge should populate the contested band honestly rather than starve it — live traffic (1 contested in 24 preprocessed) and #14's clustering both show the band is mis-populated today. Contract invariants stay pass/fail prerequisites rather than headline metrics — zero dangerous misroutes, parse discipline, and the latency budget (p50 ≤ 8s, cap 15s) — with the full numeric protocol owned by the eval-protocol ticket. The base is a **two-base bake-off**: the incumbent simple tier (`qwen3.5:4b`, known latency/parse profile, behavior delta attributable to training) plus **one fresh challenger base** (named once the training-method constraints are visible), both trained per iteration, eval picks the winner — accepted double compute for a honest architecture-vs-training attribution. The multi-model curriculum question (one model vs separate specialists) is deliberately **left in fog** — it sharpens after the corpus and method decisions land.

## Considered Options

- **Judge-only distillation** (fits + confidence; analyzer rides free in the same JSON): rejected — the whole contract is the target; deferring the rewriter saves label cost but the herd chose the complete behavior. Consequence accepted: rewriter training labels need a quality source the harvest lacks natively (what is a *good* rewrite?) — the corpus and teacher tickets inherit this.
- **Dedicated routing classifier** (embedding-router replacement): rejected — the router is not the observed weakness, and it adds a serving surface before the flywheel is proven.
- **Verdict-agreement headline metric**: rejected as the headline — an agreeable average can hide calibration and toll-band pathologies; toll-rate reduction is the observable the whole architecture exists to tune. Known risk recorded: toll rate is gameable by clustering fits away from the contested band — the eval-protocol ticket owns the guard.
- **Single base (incumbent only)**: rejected — two bases give clean attribution (architecture vs training) and a real choice; the double-compute price is accepted.
- **Resolve the curriculum fog now** (scope v1 to one model forever): rejected — the fog genuinely hangs on corpus/method outcomes and stays standing.

## Consequences

- The corpus ticket's label scope now covers every contract field: fits, confidence, task_type, complexity, signals, **and rewrites** — rewrite labels most plausibly come from a frontier teacher (the teacher ticket's question sharpens).
- The eval-protocol ticket owns: the toll-rate-reduction headline protocol, the bake-off between the two bases, the anti-gaming guard, and the invariant gates (zero dangerous misroutes, parse, latency).
- Training iterations cost double (two bases) on the M4 Pro budgets from the fine-tuning landscape findings; the corpus→LoRA probe runs whichever base is cheaper first.
- Deployment/shadow rollout must distinguish generations of distillates AND bases in the ledger.
- The challenger base for the bake-off stays fog ("which fresh base") until the training-method decision makes family support visible.
- Term canonized in CONTEXT.md: **Distillate**.
