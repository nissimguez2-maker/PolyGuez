# Local Development Quickstart

This document describes a minimal setup for running Polymarket agents locally.

## 1. Create a virtual environment

    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate

## 2. Install dependencies

    pip install -r requirements.txt

## 3. Configure environment

Copy the example env file:

    cp .env.example .env

Then edit `.env` and set your API key and wallet private key.

## 4. Run tests and a sample agent

    pytest

Then start one of the sample agents described in the README.

Keep this document updated if the local development workflow changes.
