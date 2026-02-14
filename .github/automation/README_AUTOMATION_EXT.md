Ergänzung: Deploy‑Secrets und Schnellstart

Kurz: Diese Anleitung erklärt, wie du die optionalen Deploy‑Secrets sicher anlegst, damit der Deploy‑Workflow nach Merge funktioniert.

1) SSH‑Key erzeugen (lokal)
   ssh-keygen -t rsa -b 4096 -C "deploy@yourhost" -f ~/.ssh/agents_deploy_key
   - Public:  ~/.ssh/agents_deploy_key.pub
   - Private: ~/.ssh/agents_deploy_key

2) Public key auf Zielserver installieren
   - Melde dich auf dem Zielserver als Deploy‑User an und füge die Public key zu `~/.ssh/authorized_keys`.
   - Setze korrekte Rechte: `chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys`

3) Secrets in GitHub setzen
   Repository → Settings → Secrets and variables → Actions → New repository secret
   Erstelle folgende Secrets (Namen exakt verwenden):
   - DEPLOY_HOST    (z. B. example.com)
   - DEPLOY_USER    (z. B. deployuser)
   - DEPLOY_PORT    (optional, wenn nicht gesetzt: 22)
   - DEPLOY_TARGET  (Zielpfad, z. B. /var/www/agents)
   - DEPLOY_SSH_KEY (Inhalt der privaten Key‑Datei `~/.ssh/agents_deploy_key` — ganze Datei einfügen)

4) Sicherheitshinweise
   - Verwende einen dedizierten Deploy‑User mit minimalen Rechten.
   - Lege keine Secrets in Repo‑Dateien oder Chatnachrichten ab.
   - Rotiere oder widerrufe Keys sofort, falls sie kompromittiert wurden.

5) Testen
   - Merge oder push auf `main` (oder simuliere lokal). Deploy‑Job läuft nur, wenn die oben genannten Secrets vorhanden sind.

Optional: Ich kann ein kurzes Shell‑Testscript hinzufügen, das vor dem ersten Merge die SSH‑Verbindung prüft (ssh -i KEY -p PORT USER@HOST echo ok). Soll ich das zusätzlich anlegen? (ja/nein)

Hinweis zum Testscript:
- Datei: `scripts/test_deploy_ssh.sh` (bereits vorhanden im Repo)
- Beispielaufruf:
  - `./scripts/test_deploy_ssh.sh -h example.com -u deployuser -k ~/.ssh/agents_deploy_key -p 22 -t /var/www/agents`
- Das Script prüft SSH‑Login und optionales SCP eines kleinen Testfiles in das angegebene Zielverzeichnis.

Führe das Script lokal aus, bevor du Secrets in GitHub setzt, um sicherzustellen, dass der Deploy‑User korrekt konfiguriert ist.

