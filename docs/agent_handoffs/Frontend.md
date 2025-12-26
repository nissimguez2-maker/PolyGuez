# Frontend

## Summary (max 5 bullets)
- Implementert dashboard med multi-agent equity chart og leaderboard (name, strategyType, status, bankroll, PnL%, max drawdown)
- Agent detail view med summary, caps editor (edit/save), equity chart og trades table med expandable rows
- Replay view med agent picker, date range inputs og visning av equity/trades/decisions
- API client layer (`src/api/client.ts`) med fetch wrapper og TypeScript-typer for alle endpoints
- Polling hooks (`usePolling`, `useApi`) med abort on unmount og loading/error states

## Files changed
- apps/web/package.json (lagt til recharts dependency)
- apps/web/src/api/client.ts (ny)
- apps/web/src/hooks/usePolling.ts (ny)
- apps/web/src/hooks/useApi.ts (ny)
- apps/web/src/utils/calculations.ts (ny)
- apps/web/src/components/Dashboard.tsx (ny)
- apps/web/src/components/Dashboard.css (ny)
- apps/web/src/components/AgentDetail.tsx (ny)
- apps/web/src/components/AgentDetail.css (ny)
- apps/web/src/components/ReplayView.tsx (ny)
- apps/web/src/components/ReplayView.css (ny)
- apps/web/src/App.tsx (oppdatert med routing)
- apps/web/src/App.css (oppdatert med navigation styles)
- apps/web/VERIFICATION.md (ny)

## How to verify
- `pnpm install` (installerer recharts)
- `pnpm dev:web` (starter på port 3000, proxy til API på 3001)
- Naviger til dashboard: skal vise equity chart og leaderboard, polling hver 8s
- Klikk agent i leaderboard: skal vise AgentDetail med summary, caps, equity chart, trades
- Test caps edit: klikk Edit → endre verdier → Save (kaller `PATCH /agents/:id/config`)
- Test start/pause: klikk Start/Pause knapp (kaller `POST /agents/:id/control`)
- Test trade expand: klikk "+" på trade row (viser reason, modelProb, marketProb, edge, stake)
- Naviger til Replay: velg agent, sett from/to, klikk Load Replay (kaller `GET /replay`)
- Test error handling: stopp API server → skal vise error med retry knapp (ikke blank skjerm)

## Risks / assumptions
- API kjører på port 3001 (proxy konfigurert i `apps/web/vite.config.ts`)
- Recharts pakke installeres via `pnpm install` (lagt til i package.json)
- API endpoints matcher `apps/api/src/api/routes.ts` struktur
- Polling interval er 8s (ikke 500ms som spesifisert i negative examples)
- Empty arrays (trades) håndteres med "No trades found" meldinger

## Open questions / blockers
- Ingen

## Next step (1 konkret)
- Teste fullstendig funksjonalitet mot running API server og verifisere at alle endpoints responderer korrekt

