import { EquityEntry } from '../api/client';

/**
 * Calculate PnL percentage from start bankroll
 */
export function calculatePnLPercent(
  currentBankroll: number,
  startBankroll: number
): number {
  if (startBankroll === 0) return 0;
  return ((currentBankroll - startBankroll) / startBankroll) * 100;
}

/**
 * Calculate max drawdown from equity entries
 */
export function calculateMaxDrawdown(equity: EquityEntry[]): number {
  if (equity.length === 0) return 0;

  let maxEquity = equity[0].equity;
  let maxDrawdown = 0;

  for (const entry of equity) {
    if (entry.equity > maxEquity) {
      maxEquity = entry.equity;
    }
    const drawdown = ((maxEquity - entry.equity) / maxEquity) * 100;
    if (drawdown > maxDrawdown) {
      maxDrawdown = drawdown;
    }
  }

  return maxDrawdown;
}

/**
 * Get latest equity entry
 */
export function getLatestEquity(equity: EquityEntry[]): EquityEntry | null {
  if (equity.length === 0) return null;
  return equity[equity.length - 1];
}

