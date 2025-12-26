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

// Helper to parse date string in multiple formats
// Accepts: "YYYY-MM-DD HH:MM" or "DD/MM/YYYY HH:MM"
function parseDateString(dateStr: string): Date | null {
  if (!dateStr || !dateStr.trim()) return null;

  const trimmed = dateStr.trim();

  // Try format: YYYY-MM-DD HH:MM or YYYY-MM-DDTHH:MM
  const isoMatch = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})[T\s]+(\d{2}):(\d{2})$/);
  if (isoMatch) {
    const [, year, month, day, hours, minutes] = isoMatch;
    const date = new Date(
      parseInt(year),
      parseInt(month) - 1,
      parseInt(day),
      parseInt(hours),
      parseInt(minutes)
    );
    if (!isNaN(date.getTime())) return date;
  }

  // Try format: DD/MM/YYYY HH:MM
  const ddmmyyyyMatch = trimmed.match(/^(\d{2})\/(\d{2})\/(\d{4})[T\s]+(\d{2}):(\d{2})$/);
  if (ddmmyyyyMatch) {
    const [, day, month, year, hours, minutes] = ddmmyyyyMatch;
    const date = new Date(
      parseInt(year),
      parseInt(month) - 1,
      parseInt(day),
      parseInt(hours),
      parseInt(minutes)
    );
    if (!isNaN(date.getTime())) return date;
  }

  // Fallback: try Date constructor
  const fallback = new Date(trimmed);
  if (!isNaN(fallback.getTime())) return fallback;

  return null;
}

// Helper to convert date string to ISO timestamp
function dateStringToISO(dateStr: string): string | undefined {
  if (!dateStr || !dateStr.trim()) return undefined;
  const date = parseDateString(dateStr);
  return date ? date.toISOString() : undefined;
}

// Helper to get default date string in YYYY-MM-DD HH:MM format
function getDefaultDateString(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day} ${hours}:${minutes}`;
}

export function ReplayView() {
  const [agents, setAgents] = useState<AgentsResponse['agents']>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string>('');
  
  // Initialize with default values (last 24 hours)
  const getDefaultFromDate = () => {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    return getDefaultDateString(yesterday);
  };
  
  const getDefaultToDate = () => {
    return getDefaultDateString(new Date());
  };
  
  const [fromDate, setFromDate] = useState<string>(getDefaultFromDate());
  const [toDate, setToDate] = useState<string>(getDefaultToDate());
  const [dateError, setDateError] = useState<string>('');
  const [hasUserEditedDates, setHasUserEditedDates] = useState<boolean>(false);
  
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
      
      // Validate dates
      const fromISO = dateStringToISO(fromDate);
      const toISO = dateStringToISO(toDate);
      
      if (fromDate && !fromISO) {
        setDateError(`Invalid "From" date format. Use YYYY-MM-DD HH:MM or DD/MM/YYYY HH:MM`);
        throw new Error('Invalid date format');
      }
      
      if (toDate && !toISO) {
        setDateError(`Invalid "To" date format. Use YYYY-MM-DD HH:MM or DD/MM/YYYY HH:MM`);
        throw new Error('Invalid date format');
      }
      
      setDateError('');
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

  // Reset dates to default when agent changes ONLY if user hasn't edited them
  useEffect(() => {
    if (selectedAgentId && !hasUserEditedDates) {
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
      setDateError('');
      fetchReplay();
    }
  };

  const handleFromDateChange = (value: string) => {
    setFromDate(value);
    setHasUserEditedDates(true);
    setDateError('');
  };

  const handleToDateChange = (value: string) => {
    setToDate(value);
    setHasUserEditedDates(true);
    setDateError('');
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
            <Button
              variant="primary"
              onClick={handleLoad}
              disabled={!selectedAgentId || loading}
              data-testid="replay-load"
            >
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
              type="text"
              value={fromDate}
              onChange={(e) => handleFromDateChange(e.target.value)}
              placeholder="YYYY-MM-DD HH:MM or DD/MM/YYYY HH:MM"
              data-testid="replay-from"
              className={`w-full px-3 py-2 bg-zinc-800/50 border ${
                dateError && dateError.includes('From') ? 'border-red-500/50' : 'border-zinc-700/50'
              } ${tokens.radii.md} text-zinc-100 placeholder-zinc-500 ${tokens.focus.ringTeal} focus:border-teal-500/50 ${tokens.transitions.fast}`}
            />
          </div>
          <div>
            <label className={`block ${tokens.typography.label} mb-2`}>To</label>
            <input
              type="text"
              value={toDate}
              onChange={(e) => handleToDateChange(e.target.value)}
              placeholder="YYYY-MM-DD HH:MM or DD/MM/YYYY HH:MM"
              data-testid="replay-to"
              className={`w-full px-3 py-2 bg-zinc-800/50 border ${
                dateError && dateError.includes('To') ? 'border-red-500/50' : 'border-zinc-700/50'
              } ${tokens.radii.md} text-zinc-100 placeholder-zinc-500 ${tokens.focus.ringTeal} focus:border-teal-500/50 ${tokens.transitions.fast}`}
            />
          </div>
        </div>
        {dateError && (
          <div className="mt-3">
            <div className="text-sm text-red-400" data-testid="replay-date-error">
              {dateError}
            </div>
          </div>
        )}
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
