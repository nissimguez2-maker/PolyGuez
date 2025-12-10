# IMPORTANT NOTICE

## HOW POLYMARKET ACTUALLY WORKS

Polymarket resolutions don't care for real-world facts. Instead, whoever has more money can arbitrarily decide the result of any market, SO BE CAUTIOS!

Example: `https://polymarket.com/event/trump-declassifies-ufo-files-in-2025/trump-declassifies-ufo-files-in-2025` resolved to YES. Reason? UMA can manipulate the results and to counter it you need to put more money into it, so, at the end it seems it's a matter of whoever has more money, decides the result instead of the actual result of it.

## COMPLAINT

Polymarket (NY-headquartered, Delaware/Cayman entities, now CFTC-regulated DCM/DCO via QCX) systematically defrauds users in violation of:

- CEA §§ 6, 9(a)(2), 13(a)(2) → commodities manipulation and fraud  
- 18 U.S.C. §§ 1341, 1343 → wire/mail fraud  
- 18 U.S.C. § 1962(c)–(d) → civil RICO (pattern of wire/commodities fraud + conspiracy via UMA whales)  
- N.Y. GBL § 349 → deceptive trade practices  
- NY common law → fraudulent inducement, breach of good-faith covenant, civil conspiracy  

by falsely advertising “objective, real-world” resolutions while allowing large UMA holders and coordinated whales to arbitrarily override outcomes for profit, turning a purported prediction market into a rigged, unregulated bucket shop under the cover of newly obtained U.S. federal registration.

This conduct is actionable in the U.S. District Court for the Southern District of New York under New York governing law and federal commodities statutes. Immediate demands: full restitution, permanent fraud warning banner, and elimination of UMA override mechanism, or face immediate SDNY lawsuit with class and treble-damage claims plus CFTC/DOJ referral.

<!-- PROJECT SHIELDS -->
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]


<!-- PROJECT LOGO -->
<br />
<div align="center">
  <a href="https://github.com/polymarket/agents">
    <img src="docs/images/cli.png" alt="Logo" width="466" height="262">
  </a>

<h3 align="center">Polymarket Agents</h3>

  <p align="center">
    Trade autonomously on Polymarket using AI Agents
    <br />
    <a href="https://github.com/polymarket/agents"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/polymarket/agents">View Demo</a>
    ·
    <a href="https://github.com/polymarket/agents/issues/new?labels=bug&template=bug-report---.md">Report Bug</a>
    ·
    <a href="https://github.com/polymarket/agents/issues/new?labels=enhancement&template=feature-request---.md">Request Feature</a>
  </p>
</div>


<!-- CONTENT -->
# Polymarket Agents

Polymarket Agents is a developer framework and set of utilities for building AI agents for Polymarket.

This code is free and publicly available under MIT License open source license ([terms of service](#terms-of-service))!

## Features

- Integration with Polymarket API
- AI agent utilities for prediction markets
- Local and remote RAG (Retrieval-Augmented Generation) support
- Data sourcing from betting services, news providers, and web search
- Comphrehensive LLM tools for prompt engineering

# Getting started

This repo is inteded for use with Python 3.9

1. Clone the repository

   ```
   git clone https://github.com/{username}/polymarket-agents.git
   cd polymarket-agents
   ```

2. Create the virtual environment

   ```
   virtualenv --python=python3.9 .venv
   ```

3. Activate the virtual environment

   - On Windows:

   ```
   .venv\Scripts\activate
   ```

   - On macOS and Linux:

   ```
   source .venv/bin/activate
   ```

4. Install the required dependencies:

   ```
   pip install -r requirements.txt
   ```

5. Set up your environment variables:

   - Create a `.env` file in the project root directory

   ```
   cp .env.example .env
   ```

   - Add the following environment variables:

   ```
   POLYGON_WALLET_PRIVATE_KEY=""
   OPENAI_API_KEY=""
   ```

6. Load your wallet with USDC.

7. Try the command line interface...

   ```
   python scripts/python/cli.py
   ```

   Or just go trade! 

   ```
   python agents/application/trade.py
   ```

8. Note: If running the command outside of docker, please set the following env var:

   ```
   export PYTHONPATH="."
   ```

   If running with docker is preferred, we provide the following scripts:

   ```
   ./scripts/bash/build-docker.sh
   ./scripts/bash/run-docker-dev.sh
   ```

## Architecture

The Polymarket Agents architecture features modular components that can be maintained and extended by individual community members.

### APIs

Polymarket Agents connectors standardize data sources and order types.

- `Chroma.py`: chroma DB for vectorizing news sources and other API data. Developers are able to add their own vector database implementations.

- `Gamma.py`: defines `GammaMarketClient` class, which interfaces with the Polymarket Gamma API to fetch and parse market and event metadata. Methods to retrieve current and tradable markets, as well as defined information on specific markets and events.

- `Polymarket.py`: defines a Polymarket class that interacts with the Polymarket API to retrieve and manage market and event data, and to execute orders on the Polymarket DEX. It includes methods for API key initialization, market and event data retrieval, and trade execution. The file also provides utility functions for building and signing orders, as well as examples for testing API interactions.

- `Objects.py`: data models using Pydantic; representations for trades, markets, events, and related entities.

### Scripts

Files for managing your local environment, server set-up to run the application remotely, and cli for end-user commands.

`cli.py` is the primary user interface for the repo. Users can run various commands to interact with the Polymarket API, retrieve relevant news articles, query local data, send data/prompts to LLMs, and execute trades in Polymarkets.

Commands should follow this format:

`python scripts/python/cli.py command_name [attribute value] [attribute value]`

Example:

`get-all-markets`
Retrieve and display a list of markets from Polymarket, sorted by volume.

   ```
   python scripts/python/cli.py get-all-markets --limit <LIMIT> --sort-by <SORT_BY>
   ```

- limit: The number of markets to retrieve (default: 5).
- sort_by: The sorting criterion, either volume (default) or another valid attribute.

# Contributing

If you would like to contribute to this project, please follow these steps:

1. Fork the repository.
2. Create a new branch.
3. Make your changes.
4. Submit a pull request.

Please run pre-commit hooks before making contributions. To initialize them:

   ```
   pre-commit install
   ```

# Related Repos

- [py-clob-client](https://github.com/Polymarket/py-clob-client): Python client for the Polymarket CLOB
- [python-order-utils](https://github.com/Polymarket/python-order-utils): Python utilities to generate and sign orders from Polymarket's CLOB
- [Polymarket CLOB client](https://github.com/Polymarket/clob-client): Typescript client for Polymarket CLOB
- [Langchain](https://github.com/langchain-ai/langchain): Utility for building context-aware reasoning applications
- [Chroma](https://docs.trychroma.com/getting-started): Chroma is an AI-native open-source vector database

# Prediction markets reading

- Prediction Markets: Bottlenecks and the Next Major Unlocks, Mikey 0x: https://mirror.xyz/1kx.eth/jnQhA56Kx9p3RODKiGzqzHGGEODpbskivUUNdd7hwh0
- The promise and challenges of crypto + AI applications, Vitalik Buterin: https://vitalik.eth.limo/general/2024/01/30/cryptoai.html
- Superforecasting: How to Upgrade Your Company's Judgement, Schoemaker and Tetlock: https://hbr.org/2016/05/superforecasting-how-to-upgrade-your-companys-judgment

# License

This project is licensed under the MIT License. See the [LICENSE](https://github.com/Polymarket/agents/blob/main/LICENSE.md) file for details.

# Contact

For any questions or inquiries, please contact liam@polymarket.com or reach out at www.greenestreet.xyz

Enjoy using the CLI application! If you encounter any issues, feel free to open an issue on the repository.

# Terms of Service

[Terms of Service](https://polymarket.com/tos) prohibit US persons and persons from certain other jurisdictions from trading on Polymarket (via UI & API and including agents developed by persons in restricted jurisdictions), although data and information is viewable globally.


<!-- LINKS -->
[contributors-shield]: https://img.shields.io/github/contributors/polymarket/agents?style=for-the-badge
[contributors-url]: https://github.com/polymarket/agents/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/polymarket/agents?style=for-the-badge
[forks-url]: https://github.com/polymarket/agents/network/members
[stars-shield]: https://img.shields.io/github/stars/polymarket/agents?style=for-the-badge
[stars-url]: https://github.com/polymarket/agents/stargazers
[issues-shield]: https://img.shields.io/github/issues/polymarket/agents?style=for-the-badge
[issues-url]: https://github.com/polymarket/agents/issues
[license-shield]: https://img.shields.io/github/license/polymarket/agents?style=for-the-badge
[license-url]: https://github.com/polymarket/agents/blob/master/LICENSE.md
