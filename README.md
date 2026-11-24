<div align="center">

# 📖 git-narrator

### *Understand any git diff in 5 seconds.*
**The AI-powered narrative walkthrough, secret-redacting risk radar, and visual architecture flow generator for human and agentic code.**

[![PyPI Version](https://img.shields.io/pypi/v/git-narrator.svg?color=blue)](https://pypi.org/project/git-narrator/)
[![Python Versions](https://img.shields.io/pypi/pyversions/git-narrator.svg)](https://pypi.org/project/git-narrator/)
[![CI Status](https://github.com/GiDanis/git-narrator/actions/workflows/ci.yml/badge.svg)](https://github.com/GiDanis/git-narrator/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Local-First](https://img.shields.io/badge/100%25-Local--First%20(Ollama)-purple.svg)]()

<br/>

```bash
# Test it instantly without installing anything:
uvx git-narrator
```

</div>

---

## ⚡ The 2026 Problem: "Review Burnout"

AI coding assistants (Claude Code, Cursor, Windsurf, Copilot, Cline) generate 500 lines of refactored code in seconds. The new bottleneck in software engineering is no longer *writing code* — it is **understanding, verifying, and reviewing opaque diffs**.

Standard `git diff` leaves you drowning in walls of red and green lines with zero context. Existing AI commit generators merely regurgitate shallow syntax summaries, crash when large lockfiles are staged, and leak raw `.env`/API credentials to cloud endpoints.

**`git-narrator` fixes this.** It acts as an elite Principal Architect and Security Auditor inside your terminal, scrubbing secrets locally, compacting noisy lockfiles, and transforming complex diffs into structured executive stories, negative-space risk radars, and visual system flows.

---

## 🎬 Terminal Walkthrough

```text
╭────────────────────────────────────────────────────────────────────────────╮
│ 📖 GIT NARRATOR  •  🌿 feature/auth-jwt  •  +184 / -38  •  ⚡ ollama/qwen2.5│
╰────────────────────────────────────────────────────────────────────────────╯

💡 The Executive Story
  Replaced legacy stateful Redis session cookies with stateless JWT bearer tokens
  signed using RS256. Authentication middleware now verifies public keys cached in memory,
  eliminating a database round-trip on every authenticated API request.

  Intent: Scale API horizontally without Redis session lock contention.
  Blast Radius: [ HIGH ]  Tags: #auth #jwt #security #performance

🏛️ Architectural Evolution
  ◀ State Before                      ▶ State After
  Monolithic session table in Redis   Decentralized JWT verification using
  queried on every HTTP request.      in-memory RS256 key rotation cache.

🛡️ Deep Risk & Security Radar
  🔴 CRITICAL  CONTRACT_BREAK   src/auth/middleware.py (L45)
      Legacy 'Set-Cookie: session_id' header is no longer accepted.
      Remediation: Provide a 30-day graceful deprecation fallback for mobile clients.

  🟡 MEDIUM    TEST_GAP         src/auth/jwt.py (L112)
      RS256 key refresh fallback when keys expire is not covered in test suite.
      Remediation: Add unit test simulating expired public key cache miss.

  🟢 CLEAN     No unknown, unverified, or hallucinated dependencies detected.

🗺️ Visual Flow
  Client ──[Bearer JWT]──> [AuthMiddleware] ──[Verify RS256]──> Controller
                                  │
                          (Cache Miss: Fetch JWKS)
                                  │
                                  ▼
                          [Auth0 / Key Server]

──────────────────────────────────────────────────────────────────────────────
 [1] The Story │ [2] Risk Radar (2) │ [3] Visual Flow │ [4] Commit & PR
 Shortcuts: [←/→] Tab  [c] Commit  [p] Copy PR  [m] Mermaid  [e] Edit  [q] Quit
```

---

## ✨ Key Capabilities

### 1. 🧠 The Executive Story (Before vs After)
Does not just list files. It identifies architectural intent, compares system invariants before and after, categorizes component mutations, evaluates technical debt, and assigns a discrete **Blast Radius** badge.

### 2. 🛡️ Secret Scrubbing & Negative-Space Risk Radar
Runs zero-latency deterministic checks **before** calling any LLM, plus deep architectural negative-space auditing:
- **Zero-Trust Secret Redaction**: Automatically detects and replaces AWS keys (`AKIA...`), GitHub/OpenAI/Anthropic/Google/Stripe/Slack tokens, JWTs, private PEM keys, and database passwords with `[REDACTED:<TYPE>]` prior to cloud dispatch — surfacing them as `CRITICAL / SECURITY_LEAK` findings.
- **Deterministic Pre-Scans**: Catches unresolved merge conflict markers (`<<<<<<<`) and stray debug breakpoints (`breakpoint()`, `pdb.set_trace()`, `debugger`).
- **`CONTRACT_BREAK` & `TEST_GAP`**: Spots altered public signatures, breaking schemas, or untested exception branches.
- **`PERFORMANCE_REGRESSION` & `CONCURRENCY_RACE`**: Catches N+1 queries, async loop blocks, and shared mutable state hazards.
- **`HALLUCINATED_DEPENDENCY`**: Highlights unvetted or suspicious dependencies.

### 3. 🗺️ Visual Architecture Flows
Synthesizes system mutation flows in terminal-friendly **ASCII** alongside copy-ready **Mermaid diagrams** (`[m]` copies Mermaid directly to clipboard).

### 4. ⚡ Lockfile Delta Compactor & Knapsack Token Optimizer
A 10,000-line diff is usually 90% lockfile noise. `git-narrator` compacts `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lock`, `Cargo.lock`, `poetry.lock`, `uv.lock`, `pdm.lock`, `go.sum`, `composer.lock`, `Gemfile.lock`, and `requirements*.txt` into concise delta summaries (e.g., `[UPGRADE] axios 1.2.0 -> 1.7.9`), then runs a semantic Knapsack optimizer with per-file header budgeting tailored to your model's context window.

### 5. 🔒 100% Local-First & Multi-Provider
- **Local Ollama** (Default): Auto-detected via socket + `/api/tags` to pick the best pulled coding model automatically (`qwen2.5-coder`, `qwen3`, `deepseek`, `llama3`, etc.), setting explicit `num_ctx`.
- **Google Gemini**: Fast structured streaming (`gemini-2.5-flash`).
- **OpenAI / Anthropic / Groq / DeepSeek / OpenRouter**: Raw async `httpx` drivers with strict JSON schemas, automatic retry on `429`/`5xx`, and zero vendor SDK bloat.

### 6. 🚀 Fast Lazy-Import CLI (~30ms startup, 0.17 MB package)
Uses PEP 562 lazy module loading and raw `httpx` without heavyweight official LLM SDKs (~15.6 MB total installed environment including `pydantic` & `rich`, vs ~65–120 MB in Node-based CLIs).

---

## 🚀 Quickstart

### Run with `uvx` (Recommended — Zero Installation)
```bash
uvx git-narrator
```

### Install Globally
```bash
# Via uv:
uv tool install git-narrator

# Via pip:
pip install git-narrator
```

Because Git discovers executables prefixed with `git-` in `$PATH`, you can run it natively as:
```bash
git narrator
```

---

## ⌨️ Common Workflows & Commands

### 1. Auto-Detect Mode (Zero Arguments)
```bash
git narrator
```
Automatically inspects:
1. Staged changes (`--staged`) if present.
2. Unstaged modifications and untracked new files (`--unstaged`) if nothing is staged.
3. Most recent commit (`HEAD`) if working directory is clean.

Force a specific scope or provide custom intent / output language:
```bash
git narrator --staged
git narrator --unstaged
git narrator -x "Migrating off Redis; legacy fallback intentionally removed"
git narrator --lang Italian
```

### 2. Instant Commit Generation & Git Hook
```bash
# Generate Conventional Commit and commit staged changes:
git narrator commit
git narrator commit -y

# Install prepare-commit-msg hook so `git commit` auto-fills messages:
git narrator install-hook
```

### 3. Pull Request Markdown Generator
```bash
git narrator pr
```

### 4. Specific Commits or Branch Ranges
```bash
git narrator diff HEAD~3..HEAD
git narrator diff main..feature
git narrator diff a1b2c3d
```

### 5. Configuration Management
```bash
git narrator config
git narrator config set provider gemini
git narrator config set model gemini-2.5-flash
```

---

## 🛡️ CI/CD Quality Gate (GitHub Actions)

Use `--ci` and `--fail-on-risk` in pull requests to write formatted PR summaries to `$GITHUB_STEP_SUMMARY`, emit native `::error`/`::warning` diff annotations, and block high-risk merges:

```yaml
name: "Architecture & Risk Audit"
on: [pull_request]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run git-narrator Security Gate
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          pip install git-narrator
          git-narrator diff origin/main...HEAD --ci --fail-on-risk HIGH
```

---

## ⚙️ Configuration

`git-narrator` works with zero configuration. Customize via `~/.config/git-narrator/config.json`, a per-repo `.gitnarrator.json`, or `git narrator config set`:

```json
{
  "provider": "ollama",
  "model": "qwen2.5-coder:7b",
  "ollama_base_url": "http://localhost:11434"
}
```

Supported environment variables:
- `GEMINI_API_KEY` (Google Gemini)
- `OPENAI_API_KEY` / `OPENAI_BASE_URL` (OpenAI or compatible endpoints)
- `ANTHROPIC_API_KEY` (Anthropic Claude)
- `GROQ_API_KEY` (Groq)
- `DEEPSEEK_API_KEY` (DeepSeek)
- `OPENROUTER_API_KEY` (OpenRouter)
- `OLLAMA_HOST` (Custom Ollama endpoint)

---

## 🤝 Contributing

```bash
git clone https://github.com/GiDanis/git-narrator.git
cd git-narrator
uv sync --dev
uv run ruff check .
uv run mypy git_narrator tests
uv run pytest -v
```

---

## 📄 License

MIT License © 2026 git-narrator contributors.
