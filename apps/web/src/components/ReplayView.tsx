import React, { useState, useEffect } from 'react';
import { api, AgentsResponse, TradeLog, DecisionLog } from '../api/client';
import { useApi } from '../hooks/useApi';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { SectionHeader } from '../ui/SectionHeader';
import { PageHeader } from '../ui/PageHeader';
import { Skeleton } from '../ui/Skeleton';
import { EmptyState } from '../ui/EmptyState';
import { ErrorCard } from '../ui/ErrorCard';
import { Table, TableHeader, TableHeaderCell, TableBody, TableRow, TableCell } from '../ui/Table';
import { tokens } from '../ui/tokens';

// Helper to convert datetime-local string to ISO timestamp
function datetimeLocalToISO(datetimeLocal: string): string {
  if (!datetimeLocal) return '';
  // datetime-local format: YYYY-MM-DDTHH:mm
  // Convert to ISO: YYYY-MM-DDTHH:mm:ss.sssZ
  return new Date(datetimeLocal).toISOString();
}

// Helper to get datetime-local string from Date
function dateToDatetimeLocal(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

export function ReplayView() {
  const [agents, setAgents] = useState<AgentsResponse['agents']>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string>('');
  
  // Initialize with default values (last 24 hours)
  const getDefaultFromDate = () => {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    return dateToDatetimeLocal(yesterday);
  };
  
  const getDefaultToDate = () => {
    return dateToDatetimeLocal(new Date());
  };
  
  const [fromDate, setFromDate] = useState<string>(getDefaultFromDate());
  const [toDate, setToDate] = useState<string>(getDefaultToDate());
  
  const [trades, setTrades] = useState<TradeLog[]>([]);
  const [decisions, setDecisions] = useState<DecisionLog[]>([]);
  const [selectedItem, setSelectedItem] = useState<{ type: 'trade' | 'decision'; data: TradeLog | DecisionLog } | null>(null);
  const [expandedTrade, setExpandedTrade] = useState<string | null>(null);

  const {
    data: replayData,
    loading,
    error,
    execute: fetchReplay,
    retry,
  } = useApi(
    () => {
      if (!selectedAgentId) {
        throw new Error('Please select an agent');
      }
      // Convert datetime-local strings to ISO timestamps for API
      const fromISO = fromDate ? datetimeLocalToISO(fromDate) : undefined;
      const toISO = toDate ? datetimeLocalToISO(toDate) : undefined;
      return api.getReplay(selectedAgentId, fromISO, toISO);
    },
    { immediate: false }
  );

  // Fetch agents list
  useEffect(() => {
    api
      .getAgents()
      .then((response) => {
        setAgents(response.agents);
        if (response.agents.length > 0 && !selectedAgentId) {
          setSelectedAgentId(response.agents[0].id);
        }
      })
      .catch((err) => {
        console.error('Failed to fetch agents:', err);
      });
  }, []);

  // Reset dates to default when agent changes
  useEffect(() => {
    if (selectedAgentId) {
      setFromDate(getDefaultFromDate());
      setToDate(getDefaultToDate());
    }
  }, [selectedAgentId]);

  // Update data when replay data changes
  useEffect(() => {
    if (replayData) {
      setTrades(replayData.trades);
      setDecisions(replayData.decisions);
      setSelectedItem(null);
    }
  }, [replayData]);

  const handleLoad = () => {
    if (selectedAgentId) {
      fetchReplay();
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text).then(() => {
      // Could add a toast notification here
    });
  };

  // Combine and sort all items by timestamp for timeline
  const timelineItems = [
    ...trades.map((t) => ({ type: 'trade' as const, timestamp: t.timestamp, data: t })),
    ...decisions.map((d) => ({ type: 'decision' as const, timestamp: d.timestamp, data: d })),
  ].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());

  return (
    <div className="space-y-6">
      <PageHeader
        title="Replay"
        description="Review historical trading decisions and execution data"
      />
      {/* Controls */}
      <Card>
        <SectionHeader
          title="Replay Controls"
          actions={
            <Button variant="primary" onClick={handleLoad} disabled={!selectedAgentId || loading}>
              {loading ? 'Loading...' : 'Load Replay'}
            </Button>
          }
        />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className={`block ${tokens.typography.label} mb-2`}>Agent</label>
            <select
              value={selectedAgentId}
              onChange={(e) => setSelectedAgentId(e.target.value)}
              className={`w-full px-3 py-2 bg-zinc-800/50 border border-zinc-700/50 ${tokens.radii.md} text-zinc-100 placeholder-zinc-500 ${tokens.focus.ringTeal} focus:border-teal-500/50 ${tokens.transitions.fast}`}
            >
              <option value="">Select agent...</option>
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={`block ${tokens.typography.label} mb-2`}>From</label>
            <input
              type="datetime-local"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
              className={`w-full px-3 py-2 bg-zinc-800/50 border border-zinc-700/50 ${tokens.radii.md} text-zinc-100 placeholder-zinc-500 ${tokens.focus.ringTeal} focus:border-teal-500/50 ${tokens.transitions.fast}`}
            />
          </div>
          <div>
            <label className={`block ${tokens.typography.label} mb-2`}>To</label>
            <input
              type="datetime-local"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
              className={`w-full px-3 py-2 bg-zinc-800/50 border border-zinc-700/50 ${tokens.radii.md} text-zinc-100 placeholder-zinc-500 ${tokens.focus.ringTeal} focus:border-teal-500/50 ${tokens.transitions.fast}`}
            />
          </div>
        </div>
      </Card>

      {/* Error state */}
      {error && (
        <ErrorCard
          title="Failed to load replay data"
          message={error.message}
          onRetry={retry}
        />
      )}

      {/* Loading state */}
      {loading && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <Skeleton className="h-96" />
          </div>
          <div>
            <Skeleton className="h-96" />
          </div>
        </div>
      )}

      {/* Content: Split layout */}
      {!loading && !error && (trades.length > 0 || decisions.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left: Timeline */}
          <div className="lg:col-span-1">
            <Card>
              <SectionHeader title={`Timeline (${timelineItems.length})`} />
              {timelineItems.length === 0 ? (
                <EmptyState title="No items found" />
              ) : (
                <div className="space-y-2 max-h-[700px] overflow-y-auto">
                  {timelineItems.map((item, index) => {
                    const isSelected =
                      selectedItem?.type === item.type &&
                      selectedItem?.data === item.data;
                    return (
                      <div
                        key={`${item.type}-${item.timestamp}-${index}`}
                        onClick={() => setSelectedItem({ type: item.type, data: item.data })}
                        className={`p-3 rounded-lg border cursor-pointer transition-all duration-150 ${
                          isSelected
                            ? 'bg-zinc-800 border-teal-500/50 shadow-lg shadow-teal-500/10'
                            : 'bg-zinc-800/30 border-zinc-800/50 hover:border-zinc-700/50 hover:bg-zinc-800/40'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span
                            className={`text-xs font-medium ${
                              item.type === 'trade' ? 'text-emerald-400' : 'text-cyan-400'
                            }`}
                          >
                            {item.type === 'trade' ? 'Trade' : 'Decision'}
                          </span>
                          <span className="text-xs text-zinc-500">
                            {new Date(item.timestamp).toLocaleTimeString()}
                          </span>
                        </div>
                        <div className="text-xs text-zinc-400">
                          {new Date(item.timestamp).toLocaleDateString()}
                        </div>
                        {item.type === 'trade' && 'fill' in item.data && (
                          <div className="mt-2 text-xs text-zinc-500">
                            {item.data.fill.side} {item.data.fill.shares} shares
                          </div>
                        )}
                        {item.type === 'decision' && 'filledCount' in item.data && (
                          <div className="mt-2 text-xs text-zinc-500">
                            {item.data.filledCount} filled, {item.data.rejectedCount} rejected
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>
          </div>

          {/* Right: Detail Panel */}
          <div className="lg:col-span-2 space-y-6">
            {selectedItem ? (
              <>
                {/* JSON Viewer */}
                <Card>
                  <SectionHeader
                    title={`${selectedItem.type === 'trade' ? 'Trade' : 'Decision'} Details`}
                    actions={
                      <Button
                        variant="ghost"
                        onClick={() =>
                          copyToClipboard(JSON.stringify(selectedItem.data, null, 2))
                        }
                      >
                        Copy JSON
                      </Button>
                    }
                  />
                  <div className="max-h-[500px] overflow-y-auto">
                    <pre className="text-xs text-zinc-400 whitespace-pre-wrap font-mono bg-zinc-950 p-4 rounded border border-zinc-800">
                      {JSON.stringify(selectedItem.data, null, 2)}
                    </pre>
                  </div>
                </Card>

                {/* Trades Table (if selected item is a trade) */}
                {selectedItem.type === 'trade' && (
                  <Card>
                    <SectionHeader title="Trade Information" />
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-zinc-500">Timestamp:</span>
                        <span className="text-zinc-100">
                          {new Date((selectedItem.data as TradeLog).timestamp).toLocaleString()}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-zinc-500">Market:</span>
                        <span className="text-zinc-100">{(selectedItem.data as TradeLog).fill.marketId}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-zinc-500">Side:</span>
                        <span className="text-zinc-100">{(selectedItem.data as TradeLog).fill.side}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-zinc-500">Outcome:</span>
                        <span className="text-zinc-100">{(selectedItem.data as TradeLog).fill.outcome}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-zinc-500">Shares:</span>
                        <span className="text-zinc-100">{(selectedItem.data as TradeLog).fill.shares}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-zinc-500">Price:</span>
                        <span className="text-zinc-100">
                          ${(selectedItem.data as TradeLog).fill.price.toFixed(4)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-zinc-500">Realized PnL:</span>
                        <span
                          className={
                            (selectedItem.data as TradeLog).fill.realizedPnlOnFill >= 0
                              ? 'text-emerald-400'
                              : 'text-red-400'
                          }
                        >
                          ${(selectedItem.data as TradeLog).fill.realizedPnlOnFill.toFixed(2)}
                        </span>
                      </div>
                    </div>
                  </Card>
                )}
              </>
            ) : (
              <Card>
                <EmptyState
                  title="Select an item"
                  description="Click on an item from the timeline to view details."
                />
              </Card>
            )}

            {/* All Trades Table */}
            {trades.length > 0 && (
              <Card>
                <SectionHeader title={`All Trades (${trades.length})`} />
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
                    {trades.map((trade, index) => {
                      const tradeId = `${trade.timestamp}-${index}`;
                      const isExpanded = expandedTrade === tradeId;
                      return (
                        <React.Fragment key={tradeId}>
                          <TableRow
                            onClick={() => setExpandedTrade(isExpanded ? null : tradeId)}
                          >
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
                          </TableRow>
                          {isExpanded && (
                            <TableRow>
                              <TableCell colSpan={7} className="bg-zinc-800/30">
                                <pre className="text-xs text-zinc-400 font-mono whitespace-pre-wrap">
                                  {JSON.stringify(trade, null, 2)}
                                </pre>
                              </TableCell>
                            </TableRow>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </TableBody>
                </Table>
              </Card>
            )}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && trades.length === 0 && decisions.length === 0 && (
        <EmptyState
          title="No replay data"
          description={
            selectedAgentId
              ? 'Click "Load Replay" to view data'
              : 'Please select an agent and click "Load Replay"'
          }
        />
      )}
    </div>
  );
}
