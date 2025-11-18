# Dependencies Management

## Overview

This project uses a modular dependency management approach with separate files for different environments and use cases.

## Files

### `requirements-core.txt`
Contains the minimal set of dependencies required to run the Polymarket Agents application. These are the direct dependencies that the application code actually imports and uses.

**Installation:**
```bash
pip install -r requirements-core.txt
```

### `requirements-dev.txt`
Contains development and testing dependencies in addition to the core requirements.

**Installation:**
```bash
pip install -r requirements-dev.txt
```

### `requirements.txt`
Points to the core requirements for backwards compatibility.

## Python Version Requirements

- **Required:** Python 3.9.x
- **Tested on:** Python 3.9.25 (macOS ARM64)
- **Not compatible:** Python 3.12.x (due to LangChain version constraints)

## Environment Setup

### 1. Create Python 3.9 Environment
```bash
# Using conda (recommended)
conda create -n polymarket-agents python=3.9 -y
conda activate polymarket-agents

# OR using virtualenv
virtualenv --python=python3.9 .venv
source .venv/bin/activate  # macOS/Linux
```

### 2. Install Dependencies
```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements-core.txt
```

### 3. Set PYTHONPATH
```bash
export PYTHONPATH="$(pwd)"
```

## Key Dependencies

### Core Categories

#### Polymarket & Blockchain
- `py-clob-client==0.28.0`: Polymarket CLOB client
- `py-order-utils==0.3.2`: Order utilities for Polymarket
- `web3==7.14.0`: Ethereum/Web3.py library
- `poly-eip712-structs==0.0.1`: EIP-712 structured data for Polymarket

#### AI & LangChain
- `langchain==0.3.27`: LangChain core (Python 3.9 compatible)
- `langchain-community==0.3.24`: Community integrations
- `langchain-openai==0.3.35`: OpenAI integration
- `openai==2.8.1`: OpenAI API client

#### Data & Storage
- `chromadb==0.5.23`: Vector database (Python 3.9 compatible)
- `langchain-chroma==0.1.4`: Chroma integration for LangChain

#### APIs & Search
- `newsapi-python==0.2.7`: News API client
- `tavily-python==0.7.13`: Web search API
- `exa-py==2.0.0`: Exa search API
- `kagiapi==0.2.1`: Kagi search API

#### Web Framework
- `fastapi>=0.115.0,<1.0.0`: Web framework
- `uvicorn[standard]>=0.36.0,<1.0.0`: ASGI server
- `typer>=0.19.0,<1.0.0`: CLI framework

#### Utilities
- `pydantic>=2.12.0,<3.0.0`: Data validation
- `python-dotenv>=1.0.0,<2.0.0`: Environment variables
- `scheduler==0.8.8`: Task scheduling
- `devtools>=0.12.0,<1.0.0`: Development utilities

## Version Constraints

### Why Specific Versions?
- **Python 3.9 compatibility**: Many packages (especially LangChain) require specific versions for Python 3.9 support
- **Stability**: Pinned versions prevent unexpected breaking changes
- **Compatibility**: Versions are chosen to work together without conflicts

### Version Ranges
Some packages use version ranges (e.g., `fastapi>=0.115.0,<1.0.0`) to allow patch updates while preventing breaking changes.

## Known Issues & Workarounds

### Web3 Middleware Import
**Issue:** `geth_poa_middleware` moved in web3.py v6+
**Fix:** Updated to use `ExtraDataToPOAMiddleware` from `web3.middleware.proof_of_authority`

### LangChain Python 3.9 Support
**Issue:** Latest LangChain versions require Python 3.10+
**Fix:** Use LangChain 0.3.x series which supports Python 3.9

### ChromaDB Version Compatibility
**Issue:** Latest ChromaDB requires newer Python
**Fix:** Use ChromaDB 0.5.23 which is compatible with Python 3.9

## Testing Dependencies

The following packages are included in `requirements-dev.txt`:
- `pytest>=9.0.0,<10.0.0`: Testing framework
- `black==24.4.2`: Code formatting
- `pre-commit>=4.0.0,<5.0.0`: Pre-commit hooks

## Dependency Updates

### Regular Updates
- Review and update dependencies quarterly
- Test thoroughly before updating production versions
- Update `requirements-core.txt` and `requirements-dev.txt` accordingly

### Security Updates
- Monitor for security vulnerabilities in dependencies
- Update immediately for critical security issues
- Test functionality after security updates

## Troubleshooting

### Import Errors
1. Ensure Python 3.9 environment is activated
2. Check `PYTHONPATH` is set correctly
3. Verify all dependencies are installed: `pip install -r requirements-core.txt`

### Version Conflicts
1. Check `pip check` for conflicts
2. Consider using `pip-tools` for complex dependency resolution
3. May need to adjust version constraints

### Platform-Specific Issues
- macOS ARM64: Some packages may have build issues
- Linux/Windows: Generally more compatible
- Docker: Use Python 3.9 base image as specified in Dockerfile

## Contributing

When adding new dependencies:
1. Add to appropriate requirements file
2. Test installation on Python 3.9
3. Update this documentation
4. Ensure no conflicts with existing dependencies