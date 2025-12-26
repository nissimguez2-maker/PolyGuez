import { useState, useEffect, useCallback } from 'react';
import { api, AgentsResponse, AgentState, EquityEntry, TradeLog, DecisionLog } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { StatTile } from '../ui/StatTile';
import { SectionHeader } from '../ui/SectionHeader';
import { PageHeader } from '../ui/PageHeader';
import { Table, TableHeader, TableHeaderCell, TableBody, TableRow, TableCell } from '../ui/Table';
import { Skeleton } from '../ui/Skeleton';
import { EmptyState } from '../ui/EmptyState';
import { ErrorCard } from '../ui/ErrorCard';
import { tokens } from '../ui/tokens';
import { calculatePnLPercent, calculateMaxDrawdown } from '../utils/calculations';

interface AgentListItem {
  id: string;
  name: string;
  strategyType: string;
  status: 'running' | 'paused';
  bankroll: number;
  startBankroll: number;
  pnlPercent: number;
}

interface AgentsViewProps {
  onOpenChat?: (agentId: string) => void;
  onOpenDetails?: (agentId: string) => void;
  initialSelectedId?: string | null;
  onSelectionChange?: (agentId: string | null) => void;
}

export function AgentsView({ onOpenChat, onOpenDetails, initialSelectedId, onSelectionChange }: AgentsViewProps) {
  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(initialSelectedId || null);

  const handleSelectionChange = (agentId: string | null) => {
    setSelectedAgentId(agentId);
    onSelectionChange?.(agentId);
  };
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'running' | 'paused'>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  // Selected agent detail state
  const [agentState, setAgentState] = useState<AgentState | null>(null);
  const [agentEquity, setAgentEquity] = useState<EquityEntry[]>([]);
  const [agentTrades, setAgentTrades] = useState<TradeLog[]>([]);
  const [agentDecisions, setAgentDecisions] = useState<DecisionLog[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);

  const fetchAgents = useCallback(async (signal: AbortSignal) => {
    try {
      const agentsResponse: AgentsResponse = await api.getAgents();

      const agentsWithMetrics = await Promise.all(
        agentsResponse.agents.map(async (agent) => {
          try {
            const state = await api.getAgent(agent.id);
            const bankroll = state.bankroll;
            const startBankroll = state.startBankroll;

            return {
              id: agent.id,
              name: agent.name,
              strategyType: agent.strategyType,
              status: agent.status,
              bankroll,
              startBankroll,
              pnlPercent: calculatePnLPercent(bankroll, startBankroll),
            };
          } catch (err) {
            console.error(`Failed to fetch data for agent ${agent.id}:`, err);
            return {
              id: agent.id,
              name: agent.name,
              strategyType: agent.strategyType,
              status: agent.status,
              bankroll: 0,
              startBankroll: 0,
              pnlPercent: 0,
            };
          }
        })
      );

      if (!signal.aborted) {
        setAgents(agentsWithMetrics);
        setLoading(false);
        setError(null);

        // Auto-select first agent if none selected and no initial selection
        if (!selectedAgentId && !initialSelectedId && agentsWithMetrics.length > 0) {
          handleSelectionChange(agentsWithMetrics[0].id);
        }
      }
    } catch (err) {
      if (!signal.aborted) {
        setError(err instanceof Error ? err : new Error('Unknown error'));
        setLoading(false);
      }
    }
  }, [selectedAgentId, initialSelectedId]);

  const fetchAgentDetail = useCallback(async (agentId: string) => {
    if (!agentId) return;

    setDetailLoading(true);
    try {
      const [state, equityResponse, tradesResponse, replayData] = await Promise.all([
        api.getAgent(agentId),
        api.getAgentEquity(agentId),
        api.getAgentTrades(agentId, 20),
        api.getReplay(agentId).catch(() => ({ decisions: [] as DecisionLog[] })),
      ]);

      setAgentState(state);
      setAgentEquity(equityResponse.equity);
      setAgentTrades(tradesResponse.trades);
      setAgentDecisions(replayData.decisions || []);
    } catch (err) {
      console.error('Failed to fetch agent detail:', err);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  usePolling(fetchAgents, 8000, true);

  useEffect(() => {
    const controller = new AbortController();
    fetchAgents(controller.signal);
    return () => controller.abort();
  }, [fetchAgents]);

  useEffect(() => {
    if (initialSelectedId !== undefined && initialSelectedId !== selectedAgentId) {
      handleSelectionChange(initialSelectedId);
    }
  }, [initialSelectedId, selectedAgentId]);

  useEffect(() => {
    if (selectedAgentId) {
      fetchAgentDetail(selectedAgentId);
    }
  }, [selectedAgentId, fetchAgentDetail]);

  const handleStartPause = async (agentId: string, currentStatus: 'running' | 'paused') => {
    try {
      const action = currentStatus === 'running' ? 'pause' : 'start';
      await api.controlAgent(agentId, action);
      const controller = new AbortController();
      fetchAgents(controller.signal);
      if (selectedAgentId === agentId) {
        fetchAgentDetail(agentId);
      }
    } catch (err) {
      console.error('Failed to control agent:', err);
      alert('Failed to control agent. Please retry.');
    }
  };

  const filteredAgents = agents.filter((agent) => {
    // Status filter
    if (statusFilter !== 'all' && agent.status !== statusFilter) {
      return false;
    }

    // Search filter
    const query = searchQuery.toLowerCase();
    if (query) {
      return (
        agent.name.toLowerCase().includes(query) ||
        agent.strategyType.toLowerCase().includes(query) ||
        agent.id.toLowerCase().includes(query)
      );
    }

    return true;
  });

  const latestActivity = [
    ...agentTrades.slice(0, 5).map((t) => ({ type: 'trade' as const, timestamp: t.timestamp, data: t })),
    ...agentDecisions.slice(0, 5).map((d) => ({ type: 'decision' as const, timestamp: d.timestamp, data: d })),
  ]
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    .slice(0, 5);

  const latestEquity = agentEquity.length > 0 ? agentEquity[agentEquity.length - 1] : null;
  const maxDrawdown = calculateMaxDrawdown(agentEquity);
  const pnlPercent = agentState
    ? calculatePnLPercent(agentState.bankroll, agentState.startBankroll)
    : 0;

  if (loading && agents.length === 0) {
    return (
      <div className="space-y-6">
        <PageHeader title="Agents" description="Manage and monitor trading agents" />
        <div className="flex gap-6">
          <div className="w-80 shrink-0">
            <Card>
              <Skeleton lines={8} className="h-16" />
            </Card>
          </div>
          <div className="flex-1">
            <Card>
              <Skeleton lines={10} className="h-8" />
            </Card>
          </div>
        </div>
      </div>
    );
  }

  if (error && agents.length === 0) {
    return (
      <ErrorCard
        title="Failed to load agents"
        message={error.message}
        onRetry={() => {
          setError(null);
          setLoading(true);
          const controller = new AbortController();
          fetchAgents(controller.signal);
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Agents" description="Manage and monitor trading agents" />
      <div className="flex gap-6">
        {/* Left Panel: Agent List */}
        <div className="w-80 shrink-0">
          <Card>
          <div className="mb-4 space-y-3">
            <input
              type="text"
              placeholder="Search agents..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`w-full px-3 py-2 ${tokens.radii.md} bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder-zinc-500 ${tokens.focus.ringTeal} focus:border-teal-500/50 ${tokens.transitions.fast}`}
            />
            <div className="flex gap-2">
              <button
                onClick={() => setStatusFilter('all')}
                className={`flex-1 px-3 py-1.5 ${tokens.radii.md} text-xs font-medium ${tokens.transitions.colors} ${
                  statusFilter === 'all'
                    ? 'bg-teal-500/20 text-teal-400 border border-teal-500/30'
                    : 'bg-zinc-800/50 text-zinc-400 border border-zinc-700/50 hover:bg-zinc-800/70 hover:text-zinc-300'
                }`}
              >
                All
              </button>
              <button
                onClick={() => setStatusFilter('running')}
                className={`flex-1 px-3 py-1.5 ${tokens.radii.md} text-xs font-medium ${tokens.transitions.colors} ${
                  statusFilter === 'running'
                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                    : 'bg-zinc-800/50 text-zinc-400 border border-zinc-700/50 hover:bg-zinc-800/70 hover:text-zinc-300'
                }`}
              >
                Running
              </button>
              <button
                onClick={() => setStatusFilter('paused')}
                className={`flex-1 px-3 py-1.5 ${tokens.radii.md} text-xs font-medium ${tokens.transitions.colors} ${
                  statusFilter === 'paused'
                    ? 'bg-zinc-500/20 text-zinc-400 border border-zinc-500/30'
                    : 'bg-zinc-800/50 text-zinc-400 border border-zinc-700/50 hover:bg-zinc-800/70 hover:text-zinc-300'
                }`}
              >
                Paused
              </button>
            </div>
          </div>

          {filteredAgents.length === 0 ? (
            <EmptyState
              title="No agents found"
              description={searchQuery ? 'Try a different search term' : 'No agents available'}
            />
          ) : (
            <div className="space-y-2 max-h-[calc(100vh-300px)] overflow-y-auto">
              {filteredAgents.map((agent) => (
                <Card
                  key={agent.id}
                  padding="sm"
                  className={`cursor-pointer ${tokens.transitions.default} ${
                    selectedAgentId === agent.id
                      ? 'border-teal-500/50 bg-zinc-800/50 shadow-md shadow-teal-500/10'
                      : 'border-zinc-800/50 hover:border-zinc-700/50 hover:bg-zinc-800/30 hover:shadow-md'
                  }`}
                  onClick={() => handleSelectionChange(agent.id)}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1.5">
                        <h3 className={`${tokens.typography.h4} truncate`}>{agent.name}</h3>
                        <Badge status={agent.status} />
                      </div>
                      <div className={`${tokens.typography.bodySmall} text-zinc-400 font-mono mb-2`}>
                        {agent.strategyType}
                      </div>
                      <div className="flex items-center gap-4 text-xs">
                        <div>
                          <span className="text-zinc-500">PnL: </span>
                          <span
                            className={`font-medium ${
                              agent.pnlPercent >= 0 ? 'text-emerald-400' : 'text-red-400'
                            }`}
                          >
                            {agent.pnlPercent >= 0 ? '+' : ''}
                            {agent.pnlPercent.toFixed(2)}%
                          </span>
                        </div>
                        <div>
                          <span className="text-zinc-500">Bankroll: </span>
                          <span className="text-zinc-300 font-medium">
                            ${agent.bankroll.toFixed(2)}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="flex flex-col gap-1.5 shrink-0">
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSelectionChange(agent.id);
                          onOpenDetails?.(agent.id);
                        }}
                        className="whitespace-nowrap"
                      >
                        Details
                      </Button>
                      {onOpenChat && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            onOpenChat(agent.id);
                          }}
                          className="whitespace-nowrap"
                        >
                          Chat
                        </Button>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 mt-3 pt-3 border-t border-zinc-800/50">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleStartPause(agent.id, agent.status);
                      }}
                      className="flex-1"
                    >
                      {agent.status === 'running' ? 'Pause' : 'Start'}
                    </Button>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Right Panel: Agent Detail */}
      <div className="flex-1 min-w-0">
        {!selectedAgentId ? (
          <Card>
            <EmptyState
              title="No agent selected"
              description="Select an agent from the list to view details"
            />
          </Card>
        ) : detailLoading ? (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-28" />
              ))}
            </div>
            <Card>
              <Skeleton lines={5} className="h-4" />
            </Card>
          </div>
        ) : !agentState ? (
          <Card>
            <EmptyState
              title="Failed to load agent"
              description="Unable to fetch agent details"
            />
          </Card>
        ) : (
          <div className="space-y-6">
            {/* KPI Tiles */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <StatTile
                label="Bankroll"
                value={`$${agentState.bankroll.toFixed(2)}`}
                subtext={`Start: $${agentState.startBankroll.toFixed(2)}`}
              />
              <StatTile
                label="PnL"
                value={`${pnlPercent >= 0 ? '+' : ''}${pnlPercent.toFixed(2)}%`}
                subtext={`$${agentState.pnlTotal.toFixed(2)} total`}
                trend={pnlPercent >= 0 ? 'up' : 'down'}
              />
              <StatTile
                label="Equity"
                value={latestEquity ? `$${latestEquity.equity.toFixed(2)}` : '—'}
                subtext="Current equity"
              />
              <StatTile
                label="Max Drawdown"
                value={`${maxDrawdown.toFixed(2)}%`}
                subtext="From peak"
              />
            </div>

            {/* Latest Activity */}
            <Card>
              <SectionHeader title="Latest Activity" />
              {latestActivity.length === 0 ? (
                <EmptyState
                  title="No recent activity"
                  description="Activity will appear here as the agent makes decisions and trades"
                />
              ) : (
                <div className="space-y-2">
                  {latestActivity.map((item, index) => (
                    <div
                      key={`${item.type}-${item.timestamp}-${index}`}
                      className={`p-3 bg-zinc-800/30 ${tokens.radii.md} border border-zinc-800/50 ${tokens.transitions.fast} hover:bg-zinc-800/40 hover:border-zinc-700/50`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span
                          className={`text-xs font-medium ${
                            item.type === 'trade' ? 'text-emerald-400' : 'text-cyan-400'
                          }`}
                        >
                          {item.type === 'trade' ? 'Trade' : 'Decision'}
                        </span>
                        <span className={`${tokens.typography.bodySmall} text-zinc-500`}>
                          {new Date(item.timestamp).toLocaleString()}
                        </span>
                      </div>
                      {item.type === 'trade' && 'fill' in item.data && (
                        <div className={`${tokens.typography.bodySmall} text-zinc-400`}>
                          {item.data.fill.side} {item.data.fill.shares} shares @ $
                          {item.data.fill.price.toFixed(4)}
                        </div>
                      )}
                      {item.type === 'decision' && 'filledCount' in item.data && (
                        <div className={`${tokens.typography.bodySmall} text-zinc-400`}>
                          {item.data.filledCount} filled, {item.data.rejectedCount} rejected
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* Recent Trades Table */}
            <Card>
              <SectionHeader title="Recent Trades" />
              {agentTrades.length === 0 ? (
                <EmptyState
                  title="No trades"
                  description="Trades will appear here once the agent starts trading"
                />
              ) : (
                <Table>
                  <TableHeader>
                    <TableHeaderCell>Timestamp</TableHeaderCell>
                    <TableHeaderCell>Market</TableHeaderCell>
                    <TableHeaderCell>Side</TableHeaderCell>
                    <TableHeaderCell>Outcome</TableHeaderCell>
                    <TableHeaderCell numeric>Shares</TableHeaderCell>
                    <TableHeaderCell numeric>Price</TableHeaderCell>
                    <TableHeaderCell numeric>PnL</TableHeaderCell>
                  </TableHeader>
                  <TableBody>
                    {agentTrades.map((trade, index) => (
                      <TableRow key={`${trade.timestamp}-${index}`}>
                        <TableCell>
                          {new Date(trade.timestamp).toLocaleString()}
                        </TableCell>
                        <TableCell>
                          <span className={tokens.typography.monoSmall}>{trade.fill.marketId}</span>
                        </TableCell>
                        <TableCell>{trade.fill.side}</TableCell>
                        <TableCell>{trade.fill.outcome}</TableCell>
                        <TableCell numeric>{trade.fill.shares}</TableCell>
                        <TableCell numeric>${trade.fill.price.toFixed(4)}</TableCell>
                        <TableCell
                          numeric
                          className={
                            trade.fill.realizedPnlOnFill >= 0 ? 'text-emerald-400' : 'text-red-400'
                          }
                        >
                          {trade.fill.realizedPnlOnFill >= 0 ? '+' : ''}
                          ${trade.fill.realizedPnlOnFill.toFixed(2)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </Card>
          </div>
        )}
      </div>
      </div>
    </div>
  );
}

