# uv Migration & Python 3.12 Upgrade - Action Plan

> **Status:** 🟡 80% Ready  
> **Review Date:** November 18, 2025  
> **Full Review:** See `UV_MIGRATION_REVIEW.md`

---

## Quick Summary

Your migration is **architecturally sound** but has **critical gaps** that must be fixed before adoption:

1. **pyproject.toml is empty** - Dependencies are still in `requirements-core.txt` (DRY violation)
2. **PYTHONPATH is fragile** - Relies on helper scripts; won't work with direct `uv run`
3. **CI/CD outdated** - Still uses Python 3.9 + pip (contradicts your migration)
4. **Dockerfile outdated** - Still uses Python 3.9 base image
5. **Version downgrades untested** - LangChain 0.3.27 and chromadb 0.5.23 need end-to-end validation

---

## Phase 1: Critical Fixes (2 hours)

Complete these before using uv as your standard workflow:

### 1. Delete Duplicate Import (5 min)
**File:** `scripts/python/cli.py`  
**Action:** Remove line 1 (`import typer` - it's imported again on line 9)

```python
# ❌ DELETE THIS LINE:
import typer

# KEEP THESE:
import pathlib
import sys
# ... rest of file
```

---

### 2. Migrate Dependencies to pyproject.toml (30 min)

**File:** `pyproject.toml`  
**Action:** Replace the empty `[project]` section with:

```toml
[project]
name = "agents"
version = "0.1.0"
description = "Decentralized AI Agent for Polymarket"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "py-clob-client==0.28.0",
    "py-order-utils==0.3.2",
    "web3==7.14.0",
    "poly-eip712-structs==0.0.1",
    "langchain==0.3.27",
    "langchain-community==0.3.24",
    "langchain-chroma==0.1.4",
    "openai==2.8.1",
    "chromadb==0.5.23",
    "newsapi-python==0.2.7",
    "tavily-python==0.7.13",
    "exa-py==2.0.0",
    "kagiapi==0.2.1",
    "fastapi>=0.115.0,<1.0.0",
    "uvicorn[standard]>=0.36.0,<1.0.0",
    "httpx>=0.28.0,<1.0.0",
    "requests>=2.32.0,<3.0.0",
    "typer>=0.19.0,<1.0.0",
    "devtools>=0.12.0,<1.0.0",
    "python-dotenv>=1.0.0,<2.0.0",
    "pydantic>=2.12.0,<3.0.0",
    "scheduler==0.8.8",
]

[project.optional-dependencies]
dev = [
    "pytest>=9.0.0,<10.0.0",
    "black==24.4.2",
    "pre-commit>=4.0.0,<5.0.0",
]

[project.scripts]
agents = "scripts.python.cli:app"
```

**Afterward:**
- Keep `requirements-core.txt` as optional fallback (or delete)
- Update CI/CD to use `pyproject.toml` as source of truth

---

### 3. Test Package Installation (15 min)

```bash
cd /Users/swong/dev/agents
source polymarket-3.12/bin/activate

# Install the package in development mode
uv pip install -e .

# Test imports work WITHOUT manual PYTHONPATH
python -c "from agents.polymarket.polymarket import Polymarket; print('✅ Import successful')"

# Test CLI works
uv run python scripts/python/cli.py --help
```

**Expected:** No `ModuleNotFoundError`

---

### 4. Remove PYTHONPATH Workaround from cli.py (5 min)

**File:** `scripts/python/cli.py`  
**Action:** Delete lines 5-7:

```python
# ❌ DELETE THESE LINES:
ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
```

The imports should work without this once you install the package with `uv pip install -e .`.

---

### 5. Update GitHub Actions Workflow (30 min)

**File:** `.github/workflows/python-app.yml`  
**Action:** Replace entire file with:

```yaml
name: Python application (Python 3.12 + uv)

on:
  push:
    branches: [ "main" ]
  pull_request:
    branches: [ "main" ]

permissions:
  contents: read

jobs:
  build:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Set up Python 3.12
      uses: actions/setup-python@v4
      with:
        python-version: "3.12"
    
    - name: Install uv
      run: |
        pip install --upgrade pip
        pip install uv
    
    - name: Install dependencies
      run: uv pip install -e .[dev]
    
    - name: Lint with black
      run: uv run black --check agents/ scripts/ tests/
    
    - name: Run tests
      run: uv run pytest tests/ -v
    
    - name: Smoke test CLI
      run: uv run python scripts/python/cli.py --help
```

**Why:** CI now validates Python 3.12 compatibility and uses uv.

---

### 6. Update Dockerfile (15 min)

**File:** `Dockerfile`  
**Action:** Replace with:

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY . /app

RUN pip install --upgrade pip && \
    pip install uv && \
    uv pip install -e .

CMD ["uv", "run", "python", "scripts/python/cli.py"]
```

**Why:** Aligns with Python 3.12 target and uv-first approach.

---

### 7. End-to-End Test Key Workflows (30 min)

Test that the LangChain 0.3.27 and chromadb 0.5.23 downgrades actually work:

```bash
source polymarket-3.12/bin/activate

# Test CLI imports
uv run python scripts/python/cli.py --help

# Test a market query
uv run python scripts/python/cli.py get-all-markets --limit 1

# Test LLM integration (if API keys set)
uv run python scripts/python/cli.py ask-llm "What is 2+2?"

# Test RAG (chromadb)
uv run python scripts/python/cli.py create-local-markets-rag /tmp/test_rag
uv run python scripts/python/cli.py query-local-markets-rag /tmp/test_rag "Bitcoin"
```

**Document any issues** in `UV_MIGRATION_REVIEW.md` under known issues.

---

## Phase 2: Polish & Release (3 hours)

Complete these before marking migration as "stable":

### 8. Improve Helper Script Robustness (30 min)

**File:** `scripts/activate_uv.sh`  
**Action:** Replace with improved version that has better error handling:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
UV_ENV_DIR="${PROJECT_ROOT}/polymarket-3.12"

if [[ ! -d "$UV_ENV_DIR" ]]; then
  echo "❌ uv environment not found at $UV_ENV_DIR" >&2
  echo "Create it with: uv venv polymarket-3.12 --python python3.12" >&2
  exit 1
fi

# Check if already activated
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  echo "⚠️  Virtual environment already active: $VIRTUAL_ENV" >&2
  echo "Run 'deactivate' first if switching environments." >&2
fi

# shellcheck source=/dev/null
source "$UV_ENV_DIR/bin/activate"
export PYTHONPATH="$PROJECT_ROOT"

PYTHON_VERSION=$(python --version 2>&1)
echo "✅ Activated polymarket-3.12 ($PYTHON_VERSION)"
echo "📍 PYTHONPATH=$PROJECT_ROOT"
```

---

### 9. Generate Lock Files (15 min)

```bash
cd /Users/swong/dev/agents
source polymarket-3.12/bin/activate

# Generate lock files for reproducible installs
uv pip compile pyproject.toml -o requirements.lock
uv pip compile pyproject.toml -o requirements-dev.lock --extra dev

# Commit to git
git add requirements.lock requirements-dev.lock
git commit -m "chore: add lock files for reproducible installs"
```

---

### 10. Create Makefile (30 min)

**File:** `Makefile` (create new)  
**Action:**

```makefile
.PHONY: help env install install-dev test lint format run-cli

help:
	@echo "Polymarket Agents - Development Commands"
	@echo "========================================"
	@echo ""
	@echo "Setup:"
	@echo "  make env          Create uv virtual environment"
	@echo "  make install      Install core dependencies"
	@echo "  make install-dev  Install with dev dependencies"
	@echo ""
	@echo "Development:"
	@echo "  make test         Run test suite"
	@echo "  make lint         Check code formatting (black)"
	@echo "  make format       Auto-format code (black)"
	@echo "  make run-cli      Launch interactive CLI"
	@echo ""

env:
	uv venv polymarket-3.12 --python python3.12
	@echo "✅ Environment created. Activate with: source polymarket-3.12/bin/activate"

install:
	uv pip install -e .

install-dev:
	uv pip install -e .[dev]

test:
	uv run pytest tests/ -v

lint:
	uv run black --check agents/ scripts/ tests/

format:
	uv run black agents/ scripts/ tests/

run-cli:
	uv run python scripts/python/cli.py
```

**Usage:** `make install && make test`

---

### 11. Update DEPENDENCIES.md (30 min)

**File:** `DEPENDENCIES.md`

**Changes:**
1. Update Python version requirement (lines 30-32):
   ```markdown
   ## Python Version Requirements
   
   - **Required:** Python 3.12.x
   - **Target:** Python 3.12+ (for future compatibility)
   - **Migration Status:** Python 3.9 support deprecated as of November 2025
   ```

2. Add new section after version requirements:
   ```markdown
   ## uv Dependency Manager
   
   This project uses [uv](https://github.com/astral-sh/uv) for fast, reliable dependency management.
   
   ### Quick Start
   
   ```bash
   # Create environment
   make env
   
   # Install dependencies
   make install-dev
   
   # Run tests
   make test
   ```
   
   ### uv Installation
   
   If you don't have uv installed globally:
   ```bash
   pip install uv
   ```
   ```

3. Add version trade-offs section:
   ```markdown
   ## Python 3.12 Migration: Version Trade-offs
   
   ### LangChain: 0.3.27 (not 1.0.7)
   
   **Why the downgrade?**
   - LangChain 1.0.x requires Python 3.10+ (actually 3.11+ for some features)
   - Version 0.3.27 is the latest that fully supports Python 3.12
   - Trade-off: Some newer LangChain features unavailable, but core functionality intact
   
   **Tested Functionality:**
   - ✅ LLM chain execution
   - ✅ RAG with Chroma vector store
   - ✅ Market data processing
   - ⚠️ Some integrations may have API differences
   
   **Future Upgrade Path:** [Link to GitHub issue tracking upgrade to 1.0.x]
   
   ### chromadb: 0.5.23 (not 1.3.4)
   
   **Why?** Similar compatibility constraints with Python 3.12.
   
   **Tested:**
   - ✅ Vector embedding and storage
   - ✅ Similarity search queries
   - ✅ Persistence to disk
   ```

---

### 12. Add Migration Guide to CONTRIBUTING.md (20 min)

**File:** `CONTRIBUTING.md`  
**Action:** Add new section:

```markdown
## Migration from pip to uv (Python 3.12)

### For Existing Contributors

If you were using Python 3.9 + pip, you'll need to migrate:

#### Step 1: Clean up old environment
```bash
deactivate  # If currently activated
rm -rf .venv polymarket-3.12
```

#### Step 2: Create new uv environment
```bash
make env
source polymarket-3.12/bin/activate
```

#### Step 3: Install dependencies
```bash
make install-dev
```

#### Step 4: Verify installation
```bash
python -c "from agents.polymarket.polymarket import Polymarket; print('✅ Ready!')"
```

### Troubleshooting

**Issue:** `command not found: uv`  
**Fix:** Install uv globally: `pip install uv`

**Issue:** `ModuleNotFoundError: No module named 'agents'`  
**Fix:** Ensure package is installed: `uv pip install -e .`

**Issue:** `python: No module named pytest`  
**Fix:** Install dev dependencies: `uv pip install -e .[dev]`

### Common Commands

```bash
# Activate environment
source polymarket-3.12/bin/activate

# Run CLI
python scripts/python/cli.py --help

# Run tests
make test

# Format code
make format
```

See `DEPENDENCIES.md` for more details.
```

---

### 13. Test on Fresh Environment (20 min)

Simulate a fresh developer setup:

```bash
# In a temporary directory
mkdir /tmp/test-polymarket-agents
cd /tmp/test-polymarket-agents

# Copy your project or clone from git
cp -r /Users/swong/dev/agents .
cd agents

# Start from scratch
make env
make install-dev
make test
```

**Expected:** Everything works without manual interventions.

---

## Phase 3: Optional (Track for Future)

These are nice-to-have improvements:

- [ ] Create GitHub issue: "Track LangChain 1.0.x upgrade for Python 3.12"
- [ ] Add mypy type checking to CI/CD and dev dependencies
- [ ] Add compatibility layer (`agents/utils/langchain_compat.py`) for future LangChain 1.0.x
- [ ] Document local development troubleshooting in README.md

---

## Final Verification Checklist

Before declaring migration "complete," verify all of these:

- [ ] `uv pip install -e .` successfully installs all dependencies
- [ ] `uv run python scripts/python/cli.py --help` works without PYTHONPATH
- [ ] `uv run pytest tests/` runs all tests successfully
- [ ] CI/CD pipeline passes on Python 3.12
- [ ] Docker builds successfully with Python 3.12 base image
- [ ] `make install`, `make test`, `make run-cli` all work
- [ ] DEPENDENCIES.md updated with Python 3.12 and uv info
- [ ] CONTRIBUTING.md has migration guide for existing developers
- [ ] Lock files committed to git
- [ ] No duplicate imports or sys.path manipulation in source code
- [ ] README.md acknowledges LangChain 0.3.27 vs 1.0.x trade-off

---

## Timeline

| Phase | Time | Priority | Status |
|-------|------|----------|--------|
| Phase 1 (Critical) | 2 hours | 🔴 Must Do | ⏳ Not Started |
| Phase 2 (Polish) | 3 hours | 🟡 Should Do | ⏳ Not Started |
| Phase 3 (Optional) | TBD | 🟢 Nice to Have | ⏳ Backlog |

**Recommendation:** Complete Phase 1 this week, Phase 2 next week.

---

## Questions?

Refer to the full review in `UV_MIGRATION_REVIEW.md` for:
- Detailed reasoning behind each recommendation
- Risk assessment and mitigation strategies
- Positive feedback on your approach
- Architectural analysis

---

**Review Status:** ✅ Submitted November 18, 2025  
**Next Review:** After Phase 1 completion
