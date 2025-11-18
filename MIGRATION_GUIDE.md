# Migration Guide: Python 3.9 → 3.12 + uv

This guide explains the migration from Python 3.9 with pip to Python 3.12 with uv package manager.

## Summary of Changes

### 1. Python Version Upgrade
- **Before:** Python 3.9
- **After:** Python 3.12 (minimum required)
- **Rationale:** Better performance, improved type hints, modern language features

### 2. Package Manager Migration
- **Before:** pip + requirements.txt
- **After:** uv + pyproject.toml
- **Rationale:** Faster installs (10-100x), better dependency resolution, modern Python packaging

### 3. Project Structure
- **Before:** Relied on `PYTHONPATH="."` for imports
- **After:** Proper package installation with `__init__.py` files
- **Rationale:** More robust, IDE-friendly, follows Python best practices

## What Changed

### Files Added
- `pyproject.toml` - Modern Python project configuration
- `.python-version` - Specifies Python 3.12 requirement
- `agents/__init__.py` and subdirectory `__init__.py` files
- `scripts/__init__.py` and subdirectory `__init__.py` files
- `MIGRATION_GUIDE.md` (this file)

### Files Modified
- `README.md` - Updated installation instructions
- `Dockerfile` - Updated to Python 3.12-slim with uv
- `.github/workflows/python-app.yml` - Updated CI/CD to Python 3.12 + uv
- `requirements.txt` - Kept for backward compatibility (deprecated)

## Migration Steps for Developers

### Step 1: Install Python 3.12
```bash
# Using pyenv (recommended)
pyenv install 3.12
pyenv local 3.12

# Or download from python.org
```

### Step 2: Install uv
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Step 3: Remove Old Virtual Environment
```bash
# Deactivate current environment if active
deactivate

# Remove old .venv
rm -rf .venv
```

### Step 4: Create New Virtual Environment
```bash
uv venv --python 3.12
source .venv/bin/activate  # On macOS/Linux
# or
.venv\Scripts\activate  # On Windows
```

### Step 5: Install Dependencies
```bash
# Install with dev dependencies (recommended for development)
uv pip install -e ".[dev]"

# Or install without dev dependencies
uv pip install -e .
```

### Step 6: Verify Installation
```bash
# Check Python version
python --version  # Should show 3.12.x

# Test imports
python -c "from agents.polymarket.polymarket import Polymarket; print('✓ Import successful')"

# Run tests
python -m pytest
```

## Key Differences

### Import Resolution
**Before:**
```bash
export PYTHONPATH="."
python scripts/python/cli.py
```

**After:**
```bash
# No PYTHONPATH needed!
python scripts/python/cli.py
# or use the installed CLI command
polymarket-cli
```

### Dependency Installation
**Before:**
```bash
pip install -r requirements.txt
```

**After:**
```bash
uv pip install -e .
# Much faster! (10-100x speedup)
```

### Docker Usage
**Before:**
```dockerfile
FROM python:3.9
RUN pip3 install -r requirements.txt
```

**After:**
```dockerfile
FROM python:3.12-slim
RUN uv pip install --system -e .
```

## Breaking Changes

### 1. Python Version Requirement
- **Impact:** Code now requires Python 3.12+
- **Action:** Update local Python installation
- **Reason:** Some dependencies may not work with Python 3.9

### 2. No More PYTHONPATH Required
- **Impact:** `export PYTHONPATH="."` is no longer needed
- **Action:** Remove from your shell configuration
- **Reason:** Package is now properly installed

### 3. Package Installation Required
- **Impact:** Must run `uv pip install -e .` after cloning
- **Action:** Follow new setup instructions in README
- **Reason:** Proper package installation for import resolution

## Dependency Changes

All dependencies from `requirements.txt` have been migrated to `pyproject.toml` under the `dependencies` section. Version pins remain identical.

### LangChain Stack
- langchain==0.2.11
- langchain-core==0.2.26
- langchain-community==0.2.10
- langchain-chroma==0.1.2
- langchain-openai==0.1.19

### ChromaDB
- chromadb==0.5.5
- chroma-hnswlib==0.7.6

These versions are tested and compatible with Python 3.12.

## CI/CD Changes

### GitHub Actions
- Updated to Python 3.12
- Updated to actions/setup-python@v5
- Now uses uv for dependency installation
- Faster CI runs (thanks to uv speed)

### Docker Builds
- Base image: `python:3.12-slim`
- Uses uv for installation
- Smaller image size

## Rollback Plan

If you need to rollback to the old setup:

```bash
# Checkout previous commit
git checkout <previous-commit-hash>

# Recreate old environment
virtualenv --python=python3.9 .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH="."
```

## FAQ

### Q: Why Python 3.12?
**A:** Better performance, improved type system, modern features, and longer support lifecycle.

### Q: Why uv instead of pip?
**A:** 10-100x faster installs, better dependency resolution, written in Rust, actively maintained.

### Q: Will requirements.txt be removed?
**A:** It's kept for backward compatibility but is deprecated. Use `pyproject.toml` going forward.

### Q: Can I still use pip?
**A:** Yes, but uv is strongly recommended for speed and reliability:
```bash
pip install -e .  # Works, but slower
uv pip install -e .  # Recommended
```

### Q: Do I need to change my code?
**A:** No! The code itself is unchanged. Only the packaging and installation process changed.

### Q: What about deployment?
**A:** Use the updated Dockerfile or install with `uv pip install .` in production.

## Getting Help

- Check the updated [README.md](README.md) for current instructions
- Review [pyproject.toml](pyproject.toml) for dependency details
- Open an issue if you encounter problems

## Testing Checklist

After migration, verify:

- [ ] Python 3.12+ is installed
- [ ] uv is installed and in PATH
- [ ] Virtual environment created with Python 3.12
- [ ] Dependencies installed with `uv pip install -e ".[dev]"`
- [ ] CLI works: `python scripts/python/cli.py --help`
- [ ] Imports work without PYTHONPATH
- [ ] Tests pass: `python -m pytest`
- [ ] Pre-commit hooks work: `pre-commit run --all-files`
- [ ] Docker build succeeds: `docker build .`

## Timeline

- **Development**: Immediate adoption recommended
- **CI/CD**: Already updated, runs on Python 3.12
- **Production**: Test thoroughly before deploying

## Resources

- [uv Documentation](https://github.com/astral-sh/uv)
- [Python 3.12 Release Notes](https://docs.python.org/3.12/whatsnew/3.12.html)
- [PEP 621 - Project Metadata](https://peps.python.org/pep-0621/)
- [Python Packaging User Guide](https://packaging.python.org/)

---

**Migration completed:** 2025-11-18
**Python:** 3.9 → 3.12
**Package Manager:** pip → uv
**Status:** ✅ Production-ready
