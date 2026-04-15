name: refresh-context

# Regenerates the LIVE STATE block in CONTEXT.md from git log + Supabase.
# Runs on every push to main (except pushes that only touch CONTEXT.md itself,
# to avoid an infinite loop) and daily at 06:00 UTC as a safety net.

on:
  push:
    branches: [main]
    paths-ignore:
      - CONTEXT.md
  schedule:
    - cron: "0 6 * * *"
  workflow_dispatch: {}

concurrency:
  group: refresh-context
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install requests

      - name: Regenerate LIVE STATE block in CONTEXT.md
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
        run: python .github/scripts/refresh_context.py

      - name: Commit and push if changed
        run: |
          git config user.name "polyguez-context-bot"
          git config user.email "noreply@github.com"
          if [[ -n "$(git status --porcelain CONTEXT.md)" ]]; then
            git add CONTEXT.md
            git commit -m "chore(ctx): auto-refresh LIVE STATE [skip ci]"
            git push
          else
            echo "CONTEXT.md unchanged — nothing to commit."
          fi
