import { EquityEntry } from '../logging/types';

/**
 * Interface for equity history storage
 */
export interface IEquityStore {
  /** Append an equity entry */
  append(agentId: string, entry: Omit<EquityEntry, 'agentId'>): void;
  /** Get equity entries for an agent */
  get(agentId: string, from?: string, to?: string): EquityEntry[];
}

/**
 * In-memory implementation of equity store
 */
export class InMemoryEquityStore implements IEquityStore {
  private entries: Map<string, EquityEntry[]> = new Map();

  append(agentId: string, entry: Omit<EquityEntry, 'agentId'>): void {
    const agentEntries = this.entries.get(agentId) || [];
    const newEntry: EquityEntry = {
      ...entry,
      agentId,
    };
    agentEntries.push(newEntry);
    // Keep entries sorted by timestamp
    agentEntries.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    this.entries.set(agentId, agentEntries);
  }

  get(agentId: string, from?: string, to?: string): EquityEntry[] {
    const agentEntries = this.entries.get(agentId) || [];

    if (!from && !to) {
      return [...agentEntries];
    }

    return agentEntries.filter((entry) => {
      const entryTime = new Date(entry.timestamp).getTime();
      const fromTime = from ? new Date(from).getTime() : -Infinity;
      const toTime = to ? new Date(to).getTime() : Infinity;
      return entryTime >= fromTime && entryTime <= toTime;
    });
  }
}

