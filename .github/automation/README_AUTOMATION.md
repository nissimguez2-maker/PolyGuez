Automations‑Guide (semi‑automatic workflow)

Kurz:
- Workflow `.github/workflows/bot-auto-pr.yml` erstellt automatisch einen Draft‑PR (`automation/bot-auto-pr`) nachdem Lint/Tests gelaufen sind.
- Du reviewst den PR manuell und mergest nach Freigabe.

Empfohlene Einstellungen:
1) Branch‑Protection auf `main`
   - Require pull request reviews before merging (1 reviewer)
   - Require status checks to pass (CI)
   - Include administrators (optional)

2) Secrets / Tokens
- Der Workflow nutzt das automatisch bereitgestellte `GITHUB_TOKEN` — kein PAT nötig für PR‑Erstellung.
- Falls du später Aktionen brauchst, die externen Zugriff benötigen (z.B. Deployment), erstelle einen separaten PAT mit minimalen Scopes und lege ihn in Repository → Settings → Secrets → Actions.
  Empfohlene minimale Scopes für Deploy (wenn nötig):
  - repo (only if pushing tags/branches required)
  - workflow (if triggering workflows)
  - Weitere Scopes nur bei Bedarf.

3) Review‑Prozess
- PR wird als Entwurf erstellt. Prüfe Änderungen lokal oder in GitHub UI, führe Tests aus und merge erst nach Review.

4) Sicherheit
- Niemals Tokens in Code oder Issue‑Vorlagen einchecken.
- Revoke/drehe Tokens sofort, falls sie versehentlich veröffentlicht wurden.

Wenn du möchtest, kann ich:
- eine einfache Deploy‑Action (nur beim Merge) anlegen, die nach Merge automatisch in ein staging Verzeichnis deployed (benötigt Secret).  
- oder zusätzliche PR‑Templates/labels für automatisierte PRs erstellen.

