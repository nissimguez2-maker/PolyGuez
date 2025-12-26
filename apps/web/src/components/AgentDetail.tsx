import React, { useState, useEffect, useCallback } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { api, AgentState, EquityEntry, TradeLog, DecisionLog, ReplayResponse, ChatResponse } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { useApi } from '../hooks/useApi';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { SectionHeader } from '../ui/SectionHeader';
import { PageHeader } from '../ui/PageHeader';
import { Tabs } from '../ui/Tabs';
import { Skeleton } from '../ui/Skeleton';
import { EmptyState } from '../ui/EmptyState';
import { ErrorCard } from '../ui/ErrorCard';
import { Table, TableHeader, TableHeaderCell, TableBody, TableRow, TableCell } from '../ui/Table';
import { tokens } from '../ui/tokens';

interface AgentDetailProps {
  agentId: string;
  onBack: () => void;
}

type TabId = 'overview' | 'trades' | 'decisions' | 'chat';

export function AgentDetail({ agentId, onBack }: AgentDetailProps) {
  const [agentState, setAgentState] = useState<AgentState | null>(null);
  const [equity, setEquity] = useState<EquityEntry[]>([]);
  const [trades, setTrades] = useState<TradeLog[]>([]);
  const [decisions, setDecisions] = useState<DecisionLog[]>([]);
  const [expandedTrade, setExpandedTrade] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [editingCaps, setEditingCaps] = useState(false);
  const [maxRisk, setMaxRisk] = useState(0);
  const [maxExposure, setMaxExposure] = useState(0);
  const [saving, setSaving] = useState(false);
  const [chatMessage, setChatMessage] = useState('');
  const [chatResponse, setChatResponse] = useState<ChatResponse | null>(null);
  const [chatLoading, setChatLoading] = useState(false);

  const {
    data: config,
    loading: configLoading,
    error: configError,
    retry: retryConfig,
  } = useApi(() => api.getAgentConfig(agentId), { immediate: true });

  const fetchData = useCallback(async (signal: AbortSignal) => {
    try {
      const [state, equityResponse, tradesResponse] = await Promise.all([
        api.getAgent(agentId),
        api.getAgentEquity(agentId),
        api.getAgentTrades(agentId, 100),
      ]);

      if (!signal.aborted) {
        setAgentState(state);
        setEquity(equityResponse.equity);
        setTrades(tradesResponse.trades);
      }
    } catch (err) {
      if (!signal.aborted) {
        console.error('Failed to fetch agent data:', err);
      }
    }
  }, [agentId]);

  // Fetch decisions when decisions tab is active
  useEffect(() => {
    if (activeTab === 'decisions') {
      api
        .getReplay(agentId)
        .then((data: ReplayResponse) => {
          setDecisions(data.decisions);
        })
        .catch((err) => {
          console.error('Failed to fetch decisions:', err);
        });
    }
  }, [activeTab, agentId]);

  usePolling(fetchData, 8000, true);

  useEffect(() => {
    const controller = new AbortController();
    fetchData(controller.signal);
    return () => controller.abort();
  }, [agentId, fetchData]);

  useEffect(() => {
    if (config) {
      setMaxRisk(config.maxRiskPerTradePct);
      setMaxExposure(config.maxExposurePct);
    }
  }, [config]);

  const handleStartPause = async () => {
    if (!agentState) return;
    try {
      const action = agentState.status === 'running' ? 'pause' : 'start';
      const response = await api.controlAgent(agentId, action);
      setAgentState(response.state);
    } catch (err) {
      console.error('Failed to control agent:', err);
      alert('Failed to control agent. Please retry.');
    }
  };

  const handleSaveCaps = async () => {
    setSaving(true);
    try {
      await api.updateAgentConfig(agentId, {
        maxRiskPerTradePct: maxRisk,
        maxExposurePct: maxExposure,
      });
      setEditingCaps(false);
      retryConfig();
    } catch (err) {
      console.error('Failed to update config:', err);
      alert('Failed to update config. Please retry.');
    } finally {
      setSaving(false);
    }
  };

  const handleChatSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatMessage.trim()) return;

    setChatLoading(true);
    try {
      const response = await api.chat(agentId, chatMessage);
      setChatResponse(response);
      setChatMessage('');
      // Store chat mode in localStorage
      if (response.mode) {
        localStorage.setItem('chatMode', response.mode);
      }
    } catch (err) {
      console.error('Failed to send chat:', err);
      setChatResponse({
        success: false,
        mode: 'mock',
        error: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setChatLoading(false);
    }
  };

  const chartData = equity.map((entry) => ({
    timestamp: entry.timestamp,
    equity: entry.equity,
    bankroll: entry.bankroll,
  }));

  if (!agentState) {
    return (
      <div className="space-y-6">
        <PageHeader title="Agent Details" />
        <div className="space-y-4">
          <Skeleton className="h-8 w-64" />
          <Skeleton lines={3} className="h-4" />
        </div>
      </div>
    );
  }

  const tabs = [
    { id: 'overview' as TabId, label: 'Overview' },
    { id: 'trades' as TabId, label: 'Trades' },
    { id: 'decisions' as TabId, label: 'Decisions' },
    { id: 'chat' as TabId, label: 'Chat' },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title={agentState.name}
        description={agentState.strategyType}
        actions={
          <div className="flex items-center gap-3">
            <Badge status={agentState.status} />
            <Button variant="secondary" onClick={handleStartPause}>
              {agentState.status === 'running' ? 'Pause' : 'Start'}
            </Button>
            <Button variant="ghost" onClick={onBack}>
              ← Back
            </Button>
          </div>
        }
      />

      {/* Key stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <div className="text-xs text-zinc-500 uppercase tracking-wide mb-1">Bankroll</div>
          <div className="text-2xl font-semibold text-zinc-100">
            ${agentState.bankroll.toFixed(2)}
          </div>
          <div className="text-xs text-zinc-400 mt-1">
            Start: ${agentState.startBankroll.toFixed(2)}
          </div>
        </Card>
        <Card>
          <div className="text-xs text-zinc-500 uppercase tracking-wide mb-1">Total PnL</div>
          <div
            className={`text-2xl font-semibold ${
              agentState.pnlTotal >= 0 ? 'text-emerald-400' : 'text-red-400'
            }`}
          >
            {agentState.pnlTotal >= 0 ? '+' : ''}${agentState.pnlTotal.toFixed(2)}
          </div>
        </Card>
        <Card>
          <div className="text-xs text-zinc-500 uppercase tracking-wide mb-1">Open Positions</div>
          <div className="text-2xl font-semibold text-zinc-100">
            {agentState.openPositions.length}
          </div>
        </Card>
      </div>

      {/* Tabs */}
      <Card>
        <Tabs tabs={tabs} activeTab={activeTab} onTabChange={setActiveTab}>
          {/* Overview Tab */}
          {activeTab === 'overview' && (
            <div className="space-y-6">
              {/* Risk Caps */}
              <div>
                <SectionHeader
                  title="Risk Caps"
                  actions={
                    !editingCaps ? (
                      <Button variant="ghost" onClick={() => setEditingCaps(true)}>
                        Edit
                      </Button>
                    ) : null
                  }
                />
                {configLoading ? (
                  <Skeleton className="h-20" />
                ) : configError ? (
                  <ErrorCard
                    message={configError.message}
                    onRetry={retryConfig}
                  />
                ) : config ? (
                  editingCaps ? (
                    <div className="space-y-4">
                      <div>
                        <label className={`block ${tokens.typography.label} mb-2`}>
                          Max Risk Per Trade (%)
                        </label>
                        <input
                          type="number"
                          min="0"
                          max="100"
                          step="0.1"
                          value={maxRisk}
                          onChange={(e) => setMaxRisk(Number(e.target.value))}
                          className={`w-full px-3 py-2 bg-zinc-800 border border-zinc-700 ${tokens.radii.md} text-zinc-100 ${tokens.focus.ringTeal} ${tokens.transitions.fast}`}
                        />
                      </div>
                      <div>
                        <label className={`block ${tokens.typography.label} mb-2`}>Max Exposure (%)</label>
                        <input
                          type="number"
                          min="0"
                          max="100"
                          step="0.1"
                          value={maxExposure}
                          onChange={(e) => setMaxExposure(Number(e.target.value))}
                          className={`w-full px-3 py-2 bg-zinc-800 border border-zinc-700 ${tokens.radii.md} text-zinc-100 ${tokens.focus.ringTeal} ${tokens.transitions.fast}`}
                        />
                      </div>
                      <div className="flex gap-2">
                        <Button variant="primary" onClick={handleSaveCaps} disabled={saving}>
                          {saving ? 'Saving...' : 'Save'}
                        </Button>
                        <Button
                          variant="secondary"
                          onClick={() => {
                            setEditingCaps(false);
                            if (config) {
                              setMaxRisk(config.maxRiskPerTradePct);
                              setMaxExposure(config.maxExposurePct);
                            }
                          }}
                          disabled={saving}
                        >
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <div className="text-sm">
                        <span className="text-zinc-500">Max Risk Per Trade: </span>
                        <span className="text-zinc-100">{config.maxRiskPerTradePct}%</span>
                      </div>
                      <div className="text-sm">
                        <span className="text-zinc-500">Max Exposure: </span>
                        <span className="text-zinc-100">{config.maxExposurePct}%</span>
                      </div>
                    </div>
                  )
                ) : null}
              </div>

              {/* Equity Chart */}
              {chartData.length > 0 && (
                <div>
                  <SectionHeader title="Equity Chart" />
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
                        <XAxis
                          dataKey="timestamp"
                          tickFormatter={(value) => new Date(value).toLocaleTimeString()}
                          stroke="#71717a"
                        />
                        <YAxis stroke="#71717a" />
                        <Tooltip
                          labelFormatter={(value) => new Date(value).toLocaleString()}
                          contentStyle={{ backgroundColor: '#18181b', border: '1px solid #3f3f46' }}
                        />
                        <Line
                          type="monotone"
                          dataKey="equity"
                          stroke="#14b8a6"
                          strokeWidth={2}
                          dot={false}
                          name="Equity"
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Trades Tab */}
          {activeTab === 'trades' && (
            <div>
              <SectionHeader title={`Trades (${trades.length})`} />
              {trades.length === 0 ? (
                <EmptyState title="No trades found" />
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
                    <TableHeaderCell align="center"></TableHeaderCell>
                  </TableHeader>
                  <TableBody>
                    {trades.map((trade, index) => {
                      const tradeId = `${trade.timestamp}-${index}`;
                      const isExpanded = expandedTrade === tradeId;
                      return (
                        <React.Fragment key={tradeId}>
                          <TableRow onClick={() => setExpandedTrade(isExpanded ? null : tradeId)}>
                            <TableCell className="text-zinc-400">
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
                                trade.fill.realizedPnlOnFill >= 0
                                  ? 'text-emerald-400'
                                  : 'text-red-400'
                              }
                            >
                              ${trade.fill.realizedPnlOnFill.toFixed(2)}
                            </TableCell>
                            <TableCell align="center">
                              <Button
                                variant="ghost"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setExpandedTrade(isExpanded ? null : tradeId);
                                }}
                                className="text-xs"
                              >
                                {isExpanded ? '−' : '+'}
                              </Button>
                            </TableCell>
                          </TableRow>
                          {isExpanded && (
                            <TableRow>
                              <TableCell colSpan={8} className="bg-zinc-800/30">
                                <div className="space-y-1 text-xs text-zinc-400">
                                  {trade.reason && (
                                    <div>
                                      <strong>Reason:</strong> {trade.reason}
                                    </div>
                                  )}
                                  {trade.modelProb !== undefined && (
                                    <div>
                                      <strong>Model Prob:</strong> {trade.modelProb.toFixed(2)}%
                                    </div>
                                  )}
                                  {trade.marketProb !== undefined && (
                                    <div>
                                      <strong>Market Prob:</strong> {trade.marketProb.toFixed(2)}%
                                    </div>
                                  )}
                                  {trade.edgePct !== undefined && (
                                    <div>
                                      <strong>Edge:</strong> {trade.edgePct.toFixed(2)}%
                                    </div>
                                  )}
                                  {trade.stakePct !== undefined && (
                                    <div>
                                      <strong>Stake:</strong> {trade.stakePct.toFixed(2)}%
                                    </div>
                                  )}
                                </div>
                              </TableCell>
                            </TableRow>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </div>
          )}

          {/* Decisions Tab */}
          {activeTab === 'decisions' && (
            <div>
              <SectionHeader title={`Decisions (${decisions.length})`} />
              {decisions.length === 0 ? (
                <EmptyState title="No decisions found" />
              ) : (
                <div className="space-y-3">
                  {decisions.map((decision, index) => (
                    <Card key={`${decision.timestamp}-${index}`} padding="sm">
                      <div className="flex items-center justify-between mb-2">
                        <div className="text-sm font-medium text-zinc-300">
                          {new Date(decision.timestamp).toLocaleString()}
                        </div>
                        <div className="text-xs text-zinc-500">
                          {decision.filledCount} filled, {decision.rejectedCount} rejected
                        </div>
                      </div>
                      {decision.metadata && (
                        <div className="text-xs text-zinc-400 mt-2">
                          {JSON.stringify(decision.metadata, null, 2)}
                        </div>
                      )}
                      {decision.intents.length > 0 && (
                        <div className="mt-2 space-y-1">
                          <div className="text-xs font-medium text-zinc-500">Intents:</div>
                          {decision.intents.map((intent, i) => (
                            <div key={i} className="text-xs text-zinc-400 pl-2">
                              {intent.side} {intent.outcome} {intent.shares} shares @{' '}
                              {intent.marketId}
                              {intent.reason && ` - ${intent.reason}`}
                            </div>
                          ))}
                        </div>
                      )}
                    </Card>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Chat Tab */}
          {activeTab === 'chat' && (
            <div>
              <SectionHeader title="Chat" />
              {chatResponse && (
                <div className="mb-4">
                  <div className="flex items-center gap-2 mb-2">
                    <Badge
                      status={chatResponse.success ? 'running' : 'error'}
                    >
                      {chatResponse.mode}
                    </Badge>
                    {chatResponse.timestamp && (
                      <span className="text-xs text-zinc-500">
                        {new Date(chatResponse.timestamp).toLocaleString()}
                      </span>
                    )}
                  </div>
                  {chatResponse.message && (
                    <Card padding="sm">
                      <p className="text-sm text-zinc-300 whitespace-pre-wrap">
                        {chatResponse.message}
                      </p>
                    </Card>
                  )}
                  {chatResponse.error && (
                    <ErrorCard message={chatResponse.error} />
                  )}
                </div>
              )}
              <form onSubmit={handleChatSubmit} className="space-y-2">
              <textarea
                value={chatMessage}
                onChange={(e) => setChatMessage(e.target.value)}
                placeholder="Type your message..."
                className={`w-full px-3 py-2 bg-zinc-800 border border-zinc-700 ${tokens.radii.md} text-zinc-100 ${tokens.focus.ringTeal} resize-none ${tokens.transitions.fast}`}
                rows={4}
              />
                <Button type="submit" variant="primary" disabled={chatLoading || !chatMessage.trim()}>
                  {chatLoading ? 'Sending...' : 'Send'}
                </Button>
              </form>
            </div>
          )}
        </Tabs>
      </Card>
    </div>
  );
}
