# Contributing to kultivait

Thank you for your interest in kultivait. We welcome contributions, bug reports, and improvements from developers and contributors.

---

## Canonical Home & Issues

The canonical repository lives at **[Standard-Pentest/kultivait](https://github.com/Standard-Pentest/kultivait)**.

- All active development, issue tracking, and pull requests happen on **upstream**.
- Forks (such as working development forks) have issues disabled; please file tickets and open PRs against `Standard-Pentest/kultivait`.
- Pull requests from community forks are warmly welcomed. All automated CI checks must pass before merging.

---

## Development Environment & Gate

kultivait is built for **Python 3.12+** with a primary target of **macOS** (especially Apple Silicon for local model runtime support).

### 1. Setup

Install dependencies and development tools using [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

### 2. The Verification Gate

Before submitting a pull request, verify that the entire hermetic test suite passes completely green:

```bash
uv run pytest -q
```

All 713+ unit and integration tests must pass without errors or regressions.

---

## Commit Conventions

We follow the [Conventional Commits](https://www.conventionalcommits.org/) standard. Prefix commit messages with the appropriate type:

- `feat:` new capabilities or CLI commands
- `fix:` bug fixes, regression patches, or link corrections
- `docs:` documentation updates, ADRs, runbooks, or index refreshes
- `chore:` maintenance tasks, dependency bumps, or release metadata updates

Please keep commit messages concise, clear, and focused on atomic changes.
