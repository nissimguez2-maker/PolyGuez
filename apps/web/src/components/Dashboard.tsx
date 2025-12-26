import { useState, useEffect, useCallback } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { api, AgentsResponse, EquityEntry, ReplayResponse, TradeLog, DecisionLog } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { StatTile } from '../ui/StatTile';
import { SectionHeader } from '../ui/SectionHeader';
import { PageHeader } from '../ui/PageHeader';
import { Skeleton } from '../ui/Skeleton';
import { EmptyState } from '../ui/EmptyState';
import { ErrorCard } from '../ui/ErrorCard';
import { tokens } from '../ui/tokens';
import { calculatePnLPercent, calculateMaxDrawdown } from '../utils/calculations';

interface AgentWithMetrics {
  id: string;
  name: string;
  strategyType: string;
  status: 'running' | 'paused';
  bankroll: number;
  startBankroll: number;
  pnlPercent: number;
  maxDrawdown: number;
  equity: EquityEntry[];
}

interface RecentActivity {
  type: 'trade' | 'decision';
  timestamp: string;
  agentId: string;
  agentName: string;
  data: TradeLog | DecisionLog;
}

interface DashboardProps {
  onAgentClick?: (agentId: string) => void;
}

export function Dashboard({ onAgentClick }: DashboardProps) {
  const [agents, setAgents] = useState<AgentWithMetrics[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [lastTickTimestamp, setLastTickTimestamp] = useState<string | null>(null);
  const [agent1Equity, setAgent1Equity] = useState<number | null>(null);
  const [recentActivity, setRecentActivity] = useState<RecentActivity[]>([]);
  const [tradesToday, setTradesToday] = useState<number>(0);

  const fetchData = useCallback(async (signal: AbortSignal) => {
    try {
      // Fetch all agents
      const agentsResponse: AgentsResponse = await api.getAgents();
      
      // Fetch equity for each agent
      const agentsWithEquity = await Promise.all(
        agentsResponse.agents.map(async (agent) => {
          try {
            const agentState = await api.getAgent(agent.id);
            const equityResponse = await api.getAgentEquity(agent.id);
            const equity = equityResponse.equity;

            const latestEquity = equity.length > 0 ? equity[equity.length - 1] : null;
            const bankroll = latestEquity?.bankroll ?? agentState.bankroll;
            const startBankroll = agentState.startBankroll;

            // Store agent-1 equity
            if (agent.id === 'agent-1') {
              setAgent1Equity(latestEquity?.equity ?? bankroll);
            }

            return {
              id: agent.id,
              name: agent.name,
              strategyType: agent.strategyType,
              status: agent.status,
              bankroll,
              startBankroll,
              pnlPercent: calculatePnLPercent(bankroll, startBankroll),
              maxDrawdown: calculateMaxDrawdown(equity),
              equity,
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
              maxDrawdown: 0,
              equity: [],
            };
          }
        })
      );

      if (!signal.aborted) {
        setAgents(agentsWithEquity);
        setLoading(false);
        setError(null);
      }
    } catch (err) {
      if (!signal.aborted) {
        setError(err instanceof Error ? err : new Error('Unknown error'));
        setLoading(false);
      }
    }
  }, []);

  // Fetch last tick data and recent activity
  useEffect(() => {
    const fetchActivity = async () => {
      try {
        const agentsResponse = await api.getAgents();
        const agent1 = agentsResponse.agents.find((a) => a.id === 'agent-1');
        if (agent1) {
          const replayData: ReplayResponse = await api.getReplay(agent1.id);
          
          // Get last tick timestamp
          if (replayData.trades.length > 0) {
            const lastTrade = replayData.trades[replayData.trades.length - 1];
            setLastTickTimestamp(new Date(lastTrade.timestamp).toISOString());
          } else if (replayData.decisions.length > 0) {
            const lastDecision = replayData.decisions[replayData.decisions.length - 1];
            setLastTickTimestamp(new Date(lastDecision.timestamp).toISOString());
          }

          // Calculate trades today
          const today = new Date();
          today.setHours(0, 0, 0, 0);
          const todayTrades = replayData.trades.filter(
            (t) => new Date(t.timestamp) >= today
          );
          setTradesToday(todayTrades.length);

          // Build recent activity (last 10 items)
          const activity: RecentActivity[] = [];
          
          // Add recent trades
          replayData.trades
            .slice(-5)
            .forEach((trade) => {
              activity.push({
                type: 'trade',
                timestamp: trade.timestamp,
                agentId: agent1.id,
                agentName: agent1.name,
                data: trade,
              });
            });

          // Add recent decisions
          replayData.decisions
            .slice(-5)
            .forEach((decision) => {
              activity.push({
                type: 'decision',
                timestamp: decision.timestamp,
                agentId: agent1.id,
                agentName: agent1.name,
                data: decision,
              });
            });

          // Sort by timestamp and take last 10
          activity.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
          setRecentActivity(activity.slice(0, 10));
        }
      } catch (err) {
        // Silently fail - this is optional data
      }
    };
    fetchActivity();
    const interval = setInterval(fetchActivity, 8000);
    return () => clearInterval(interval);
  }, []);

  usePolling(fetchData, 8000, true);

  const handleStartPause = async (agentId: string, currentStatus: 'running' | 'paused') => {
    try {
      const action = currentStatus === 'running' ? 'pause' : 'start';
      await api.controlAgent(agentId, action);
      const controller = new AbortController();
      fetchData(controller.signal);
    } catch (err) {
      console.error('Failed to control agent:', err);
      alert('Failed to control agent. Please retry.');
    }
  };

  const runningCount = agents.filter((a) => a.status === 'running').length;
  const totalCount = agents.length;

  if (loading && agents.length === 0) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <Card>
          <Skeleton lines={5} className="h-4" />
        </Card>
      </div>
    );
  }

  if (error && agents.length === 0) {
    return (
      <ErrorCard
        title="Failed to load dashboard"
        message={error.message}
        onRetry={() => {
          setError(null);
          setLoading(true);
          const controller = new AbortController();
          fetchData(controller.signal);
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Overview of all agents, trading activity, and system status"
      />
      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatTile
          label="Agents"
          value={`${runningCount} / ${totalCount}`}
          subtext={`${runningCount} running, ${totalCount - runningCount} paused`}
        />
        <StatTile
          label="Last Tick"
          value={lastTickTimestamp ? new Date(lastTickTimestamp).toLocaleTimeString() : '—'}
          subtext={lastTickTimestamp ? new Date(lastTickTimestamp).toLocaleDateString() : 'No activity'}
        />
        <StatTile
          label="Trades Today"
          value={String(tradesToday)}
          subtext="From agent-1"
        />
        <StatTile
          label="Agent-1 Equity"
          value={agent1Equity !== null ? `$${agent1Equity.toFixed(2)}` : '—'}
          subtext="Current equity"
        />
      </div>

      {/* Equity Chart */}
      <Card>
        <SectionHeader title="Multi-Agent Equity Chart" />
        {(() => {
          const timeMap = new Map<string, Record<string, number | string>>();
          
          agents.forEach((agent) => {
            agent.equity.forEach((entry) => {
              const time = new Date(entry.timestamp).toISOString();
              if (!timeMap.has(time)) {
                timeMap.set(time, { timestamp: time });
              }
              timeMap.get(time)![agent.name] = entry.equity;
            });
          });

          const chartData = Array.from(timeMap.values()).sort(
            (a, b) => new Date(a.timestamp as string).getTime() - new Date(b.timestamp as string).getTime()
          );

          if (chartData.length === 0) {
            return (
              <EmptyState
                title="No equity data"
                description="Equity data will appear here once agents start trading."
              />
            );
          }

          return (
            <div className="h-80 -mx-4">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" opacity={0.3} />
                  <XAxis
                    dataKey="timestamp"
                    tickFormatter={(value) => new Date(value).toLocaleTimeString()}
                    stroke="#71717a"
                    style={{ fontSize: '12px' }}
                  />
                  <YAxis
                    stroke="#71717a"
                    style={{ fontSize: '12px' }}
                    tickFormatter={(value) => `$${value.toFixed(0)}`}
                  />
                  <Tooltip
                    labelFormatter={(value) => new Date(value).toLocaleString()}
                    contentStyle={{
                      backgroundColor: '#18181b',
                      border: '1px solid #3f3f46',
                      borderRadius: '8px',
                    }}
                    formatter={(value: number) => `$${value.toFixed(2)}`}
                  />
                  <Legend
                    wrapperStyle={{ paddingTop: '20px' }}
                    iconType="line"
                  />
                  {agents.map((agent, index) => (
                    <Line
                      key={agent.id}
                      type="monotone"
                      dataKey={agent.name}
                      stroke={`hsl(${(index * 360) / Math.max(agents.length, 1)}, 70%, 50%)`}
                      strokeWidth={2}
                      dot={false}
                      activeDot={{ r: 4 }}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          );
        })()}
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Agents List */}
        <div className="lg:col-span-2">
          <Card>
            <SectionHeader title="Agents" />
            {agents.length === 0 ? (
              <EmptyState
                title="No agents found"
                description="Agents will appear here once they are created and started."
              />
            ) : (
              <div className="space-y-3">
                {agents
                  .sort((a, b) => b.pnlPercent - a.pnlPercent)
                  .map((agent) => (
                    <Card
                      key={agent.id}
                      padding="md"
                      hover
                      className="cursor-pointer"
                      onClick={() => onAgentClick?.(agent.id)}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex-1">
                        <div className="flex items-center gap-3 mb-2">
                          <h3 className="text-base font-semibold text-zinc-100">{agent.name}</h3>
                          <Badge status={agent.status} />
                          <span className="text-xs text-zinc-500 font-mono">{agent.strategyType}</span>
                        </div>
                        <div className="grid grid-cols-3 gap-4 text-sm">
                          <div>
                            <span className="text-zinc-500 text-xs">Bankroll: </span>
                            <span className="text-zinc-100 font-medium">${agent.bankroll.toFixed(2)}</span>
                          </div>
                          <div>
                            <span className="text-zinc-500 text-xs">PnL: </span>
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
                            <span className="text-zinc-500 text-xs">DD: </span>
                            <span className="text-zinc-100 font-medium">{agent.maxDrawdown.toFixed(2)}%</span>
                          </div>
                        </div>
                        </div>
                        <div className="flex items-center gap-2 ml-4">
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleStartPause(agent.id, agent.status);
                            }}
                          >
                            {agent.status === 'running' ? 'Pause' : 'Start'}
                          </Button>
                        </div>
                      </div>
                    </Card>
                  ))}
              </div>
            )}
          </Card>
        </div>

        {/* Recent Activity */}
        <div>
          <Card>
            <SectionHeader title="Recent Activity" />
            {recentActivity.length === 0 ? (
              <EmptyState
                title="No recent activity"
                description="Activity will appear here as agents make decisions and trades."
              />
            ) : (
              <div className="space-y-2 max-h-[600px] overflow-y-auto">
                {recentActivity.map((item, index) => (
                  <div
                    key={`${item.type}-${item.timestamp}-${index}`}
                    className={`p-3 bg-zinc-800/30 ${tokens.radii.md} border border-zinc-800/50 text-xs ${tokens.transitions.fast} hover:bg-zinc-800/40 hover:border-zinc-700/50`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className={`font-medium ${
                        item.type === 'trade' ? 'text-emerald-400' : 'text-cyan-400'
                      }`}>
                        {item.type === 'trade' ? 'Trade' : 'Decision'}
                      </span>
                      <span className="text-zinc-500">
                        {new Date(item.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                    <div className="text-zinc-400 truncate">{item.agentName}</div>
                    {item.type === 'trade' && 'fill' in item.data && (
                      <div className="mt-1 text-zinc-500">
                        {item.data.fill.side} {item.data.fill.shares} @ ${item.data.fill.price.toFixed(4)}
                      </div>
                    )}
                    {item.type === 'decision' && 'filledCount' in item.data && (
                      <div className="mt-1 text-zinc-500">
                        {item.data.filledCount} filled, {item.data.rejectedCount} rejected
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
