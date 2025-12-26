/**
 * API client with fetch wrapper and retry functionality
 */

export interface ApiError {
  error: string;
  details?: unknown;
}

export class ApiClientError extends Error {
  constructor(
    public status: number,
    public data: ApiError,
    message?: string
  ) {
    super(message || data.error || `API error: ${status}`);
    this.name = 'ApiClientError';
  }
}

/**
 * Fetch wrapper with error handling
 */
async function apiFetch<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(`/api${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  // Check Content-Type to ensure we got JSON, not HTML
  const contentType = response.headers.get('content-type');
  if (!contentType || !contentType.includes('application/json')) {
    const text = await response.text();
    const snippet = text.substring(0, 200);
    const errorMsg = `Expected JSON but got ${contentType || 'unknown'}. This usually means the API proxy is misconfigured or the API server is not running. Response preview: ${snippet}`;
    console.error('[API Client]', errorMsg);
    console.error('[API Client]', `Requested URL: /api${endpoint}`);
    throw new ApiClientError(
      response.status,
      { error: errorMsg },
      `Invalid response type: ${contentType || 'unknown'}`
    );
  }

  const data = await response.json();

  if (!response.ok) {
    throw new ApiClientError(response.status, data as ApiError);
  }

  return data as T;
}

/**
 * Agent list response
 */
export interface AgentListItem {
  id: string;
  name: string;
  status: 'running' | 'paused';
  strategyType: string;
}

export interface AgentsResponse {
  agents: AgentListItem[];
}

/**
 * Agent state (full)
 */
export interface AgentState {
  agentId: string;
  name: string;
  strategyType: string;
  bankroll: number;
  startBankroll: number;
  pnlTotal: number;
  openPositions: Array<{
    marketId: string;
    outcome: 'YES' | 'NO';
    shares: number;
    avgEntryPrice: number;
    realizedPnl: number;
    unrealizedPnl: number;
  }>;
  maxRiskPerTradePct: number;
  maxExposurePct: number;
  status: 'running' | 'paused';
  timestamp: string;
}

/**
 * Equity entry
 */
export interface EquityEntry {
  agentId: string;
  timestamp: string;
  equity: number;
  bankroll: number;
  pnlTotal: number;
}

export interface EquityResponse {
  equity: EquityEntry[];
}

/**
 * Trade log
 */
export interface TradeLog {
  agentId: string;
  timestamp: string;
  fill: {
    agentId: string;
    marketId: string;
    side: 'BUY' | 'SELL';
    outcome: 'YES' | 'NO';
    shares: number;
    price: number;
    timestamp: string;
    realizedPnlOnFill: number;
  };
  reason?: string;
  modelProb?: number;
  marketProb?: number;
  edgePct?: number;
  stakePct?: number;
}

export interface TradesResponse {
  trades: TradeLog[];
  pagination: {
    limit: number;
    cursor: string;
    nextCursor?: string;
    hasMore: boolean;
    total: number;
  };
}

/**
 * Agent config
 */
export interface AgentConfig {
  agentId: string;
  strategyType: string;
  strategyConfig: unknown | null;
  maxRiskPerTradePct: number;
  maxExposurePct: number;
  name: string;
}

export interface UpdateConfigRequest {
  maxRiskPerTradePct?: number;
  maxExposurePct?: number;
}

export interface ControlActionRequest {
  action: 'start' | 'pause';
}

export interface ControlActionResponse {
  message: string;
  state: AgentState;
}

/**
 * Decision log
 */
export interface DecisionLog {
  agentId: string;
  timestamp: string;
  intents: Array<{
    marketId: string;
    side: 'BUY' | 'SELL';
    outcome: 'YES' | 'NO';
    shares: number;
    limitPrice?: number;
    reason?: string;
    modelProb?: number;
    marketProb?: number;
    edgePct?: number;
    stakePct?: number;
  }>;
  filledCount: number;
  rejectedCount: number;
  metadata?: Record<string, unknown>;
}

export interface ReplayResponse {
  agentId: string;
  from: string | null;
  to: string | null;
  equity: EquityEntry[];
  trades: TradeLog[];
  decisions: DecisionLog[];
}

/**
 * Chat response
 */
export interface ChatResponse {
  success: boolean;
  mode: 'mock' | 'openai';
  errorCode?: string;
  error?: string;
  message?: string;
  timestamp?: string;
  agentId?: string;
}

/**
 * Health check response
 */
export interface HealthResponse {
  status: 'ok';
  timestamp: string;
}

/**
 * API client functions
 */
export const api = {
  /**
   * Health check
   */
  health: (): Promise<HealthResponse> => apiFetch('/health'),

  /**
   * Get all agents
   */
  getAgents: (): Promise<AgentsResponse> => apiFetch('/agents'),

  /**
   * Get agent by ID
   */
  getAgent: (id: string): Promise<AgentState> => apiFetch(`/agents/${id}`),

  /**
   * Get agent equity history
   */
  getAgentEquity: (
    id: string,
    from?: string,
    to?: string
  ): Promise<EquityResponse> => {
    const params = new URLSearchParams();
    if (from) params.set('from', from);
    if (to) params.set('to', to);
    const query = params.toString();
    return apiFetch(`/agents/${id}/equity${query ? `?${query}` : ''}`);
  },

  /**
   * Get agent trades
   */
  getAgentTrades: (
    id: string,
    limit = 50,
    cursor?: string
  ): Promise<TradesResponse> => {
    const params = new URLSearchParams();
    params.set('limit', String(limit));
    if (cursor) params.set('cursor', cursor);
    return apiFetch(`/agents/${id}/trades?${params.toString()}`);
  },

  /**
   * Get agent config
   */
  getAgentConfig: (id: string): Promise<AgentConfig> =>
    apiFetch(`/agents/${id}/config`),

  /**
   * Update agent config
   */
  updateAgentConfig: (
    id: string,
    config: UpdateConfigRequest
  ): Promise<ControlActionResponse> =>
    apiFetch(`/agents/${id}/config`, {
      method: 'PATCH',
      body: JSON.stringify(config),
    }),

  /**
   * Control agent (start/pause)
   */
  controlAgent: (
    id: string,
    action: 'start' | 'pause'
  ): Promise<ControlActionResponse> =>
    apiFetch(`/agents/${id}/control`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    }),

  /**
   * Get replay data
   */
  getReplay: (
    agentId: string,
    from?: string,
    to?: string
  ): Promise<ReplayResponse> => {
    const params = new URLSearchParams();
    params.set('agentId', agentId);
    if (from) params.set('from', from);
    if (to) params.set('to', to);
    return apiFetch(`/replay?${params.toString()}`);
  },

  /**
   * Send chat message to agent
   */
  chat: (
    agentId: string,
    message: string,
    clientTimestamp?: string
  ): Promise<ChatResponse> => {
    return apiFetch('/chat', {
      method: 'POST',
      body: JSON.stringify({
        agentId,
        message,
        clientTimestamp,
      }),
    });
  },
};

