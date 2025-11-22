<div align="center">

[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]

<br />
<a href="https://github.com/polymarket/agents">
  <img src="docs/images/cli.png" alt="Polymarket Agents Logo" width="466" height="262">
</a>

# Polymarket Agents

<p align="center">
  <b>Trade autonomously on Polymarket using AI Agents</b>
  <br />
  <br />
  <a href="https://github.com/polymarket/agents"><strong>Explore the docs »</strong></a>
  <br />
  <a href="https://github.com/polymarket/agents">View Demo</a>
  ·
  <a href="https://github.com/polymarket/agents/issues/new?labels=bug&template=bug-report---.md">Report Bug</a>
  ·
  <a href="https://github.com/polymarket/agents/issues/new?labels=enhancement&template=feature-request---.md">Request Feature</a>
</p>
</div>

---

## 📖 About The Project

**Polymarket Agents** is a robust developer framework and set of utilities designed for building AI agents that interact with Polymarket.

This code is free, open-source, and publicly available under the MIT License ([terms of service](#terms-of-service)).

### ✨ Features

* **Seamless Integration:** Full support for the Polymarket API.
* **AI Utilities:** Specialized tools for prediction markets.
* **RAG Support:** Local and remote Retrieval-Augmented Generation capabilities.
* **Data Sourcing:** Aggregates data from betting services, news providers, and web search.
* **LLM Tooling:** Comprehensive tools for advanced prompt engineering.

---

## 🚀 Getting Started

This project is intended for use with **Python 3.9+**.

### Installation

1.  **Clone the repository**
    ```bash
    git clone [https://github.com/polymarket/agents.git](https://github.com/polymarket/agents.git)
    cd agents
    ```

2.  **Set up the Virtual Environment**
    
    Using the standard library `venv`:

    * **macOS / Linux:**
        ```bash
        python3.9 -m venv .venv
        source .venv/bin/activate
        ```

    * **Windows:**
        ```powershell
        python -m venv .venv
        .\.venv\Scripts\activate
        ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configuration**
    
    Create a `.env` file from the example template:
    ```bash
    cp .env.example .env
    ```
    
    Populate the `.env` file with your credentials:
    ```ini
    POLYGON_WALLET_PRIVATE_KEY="your_private_key_here"
    OPENAI_API_KEY="your_openai_key_here"
    ```

5.  **Fund your Wallet**
    Ensure your wallet is funded with **USDC** (Polygon Network).

### Usage

**Option A: Command Line Interface (CLI)**
Interact with the market using the interactive CLI tool.
```bash
# Ensure the project root is in the python path
export PYTHONPATH="."
python scripts/python/cli.py
