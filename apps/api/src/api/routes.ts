import { Router, Request, Response } from 'express';
import { z } from 'zod';
import { IStateStore } from '../stores/StateStore';
import { IEquityStore } from '../stores/EquityStore';
import { ILogStore } from '../logging/LogStore';
import { IChatStore } from '../stores/ChatStore';
import { ChatService } from '../services/ChatService';
import { MarketDataService } from '../marketData/MarketDataService';
import {
  AgentIdParamSchema,
  EquityQuerySchema,
  TradesQuerySchema,
  ReplayQuerySchema,
  ControlActionSchema,
  UpdateConfigSchema,
  ChatRequestSchema,
} from './validation';

/**
 * Create API routes
 */
export function createRoutes(
  stateStore: IStateStore,
  equityStore: IEquityStore,
  logStore: ILogStore,
  marketDataService?: MarketDataService,
  chatStore?: IChatStore
): Router {
  const router = Router();

  /**
   * GET /health
   * Health check endpoint
   */
  router.get('/health', (req: Request, res: Response) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
  });

  /**
   * GET /agents
   * List all agents
   */
  router.get('/agents', (req: Request, res: Response) => {
    try {
      const agentIds = stateStore.listAgents();
      const agents = agentIds.map((id) => {
        const state = stateStore.getAgentState(id);
        if (!state) {
          return null;
        }
        // Return minimal agent info (id, name, status)
        return {
          id: state.agentId,
          name: state.name,
          status: state.status,
          strategyType: state.strategyType,
        };
      }).filter((agent) => agent !== null);

      res.json({ agents });
    } catch (error) {
      console.error('[API] Error in GET /agents:', error);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * GET /agents/:id
   * Get agent by ID
   */
  router.get('/agents/:id', (req: Request, res: Response) => {
    try {
      const params = AgentIdParamSchema.parse({ id: req.params.id });
      const state = stateStore.getAgentState(params.id);

      if (!state) {
        return res.status(404).json({ error: `Agent ${params.id} not found` });
      }

      res.json(state);
    } catch (error) {
      if (error instanceof z.ZodError) {
        return res.status(400).json({ error: 'Invalid agent ID', details: error.errors });
      }
      console.error('[API] Error in GET /agents/:id:', error);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * GET /agents/:id/equity
   * Get equity history for an agent
   */
  router.get('/agents/:id/equity', (req: Request, res: Response) => {
    try {
      const params = AgentIdParamSchema.parse({ id: req.params.id });
      const query = EquityQuerySchema.parse(req.query);

      // Verify agent exists
      const state = stateStore.getAgentState(params.id);
      if (!state) {
        return res.status(404).json({ error: `Agent ${params.id} not found` });
      }

      const equity = equityStore.get(params.id, query.from, query.to);
      res.json({ equity });
    } catch (error) {
      if (error instanceof z.ZodError) {
        return res.status(400).json({ error: 'Invalid request', details: error.errors });
      }
      console.error('[API] Error in GET /agents/:id/equity:', error);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * GET /agents/:id/trades
   * Get trades for an agent with pagination
   */
  router.get('/agents/:id/trades', (req: Request, res: Response) => {
    try {
      const params = AgentIdParamSchema.parse({ id: req.params.id });
      const query = TradesQuerySchema.parse(req.query);

      // Verify agent exists
      const state = stateStore.getAgentState(params.id);
      if (!state) {
        return res.status(404).json({ error: `Agent ${params.id} not found` });
      }

      // Get trades with pagination using queryTrades
      const offset = query.cursor ? parseInt(query.cursor, 10) : 0;
      const validOffset = isNaN(offset) || offset < 0 ? 0 : offset;
      
      const tradesResult = logStore.queryTrades(params.id, undefined, undefined, {
        limit: query.limit,
        offset: validOffset,
      });

      const nextCursor = tradesResult.hasMore 
        ? String(validOffset + query.limit) 
        : undefined;

      res.json({
        trades: tradesResult.items,
        pagination: {
          limit: query.limit,
          cursor: query.cursor || '0',
          nextCursor,
          hasMore: tradesResult.hasMore,
          total: tradesResult.total,
        },
      });
    } catch (error) {
      if (error instanceof z.ZodError) {
        return res.status(400).json({ error: 'Invalid request', details: error.errors });
      }
      console.error('[API] Error in GET /agents/:id/trades:', error);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * POST /agents/:id/control
   * Control agent (start/pause)
   */
  router.post('/agents/:id/control', (req: Request, res: Response) => {
    try {
      const params = AgentIdParamSchema.parse({ id: req.params.id });
      const body = ControlActionSchema.parse(req.body);

      // Verify agent exists
      const state = stateStore.getAgentState(params.id);
      if (!state) {
        return res.status(404).json({ error: `Agent ${params.id} not found` });
      }

      // Update status
      const newStatus = body.action === 'start' ? 'running' : 'paused';
      stateStore.setStatus(params.id, newStatus);

      // Return updated state
      const updatedState = stateStore.getAgentState(params.id);
      res.json({ 
        message: `Agent ${params.id} ${body.action}ed`,
        state: updatedState,
      });
    } catch (error) {
      if (error instanceof z.ZodError) {
        return res.status(400).json({ error: 'Invalid request', details: error.errors });
      }
      if (error instanceof Error && error.message.includes('not found')) {
        return res.status(404).json({ error: error.message });
      }
      console.error('[API] Error in POST /agents/:id/control:', error);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * GET /agents/:id/config
   * Get agent configuration
   */
  router.get('/agents/:id/config', (req: Request, res: Response) => {
    try {
      const params = AgentIdParamSchema.parse({ id: req.params.id });

      // Verify agent exists
      const state = stateStore.getAgentState(params.id);
      if (!state) {
        return res.status(404).json({ error: `Agent ${params.id} not found` });
      }

      const strategyConfig = stateStore.getStrategyConfig(params.id);

      res.json({
        agentId: params.id,
        strategyType: state.strategyType,
        strategyConfig: strategyConfig || null,
        maxRiskPerTradePct: state.maxRiskPerTradePct,
        maxExposurePct: state.maxExposurePct,
        name: state.name,
      });
    } catch (error) {
      if (error instanceof z.ZodError) {
        return res.status(400).json({ error: 'Invalid request', details: error.errors });
      }
      console.error('[API] Error in GET /agents/:id/config:', error);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * PATCH /agents/:id/config
   * Update agent configuration
   */
  router.patch('/agents/:id/config', (req: Request, res: Response) => {
    try {
      const params = AgentIdParamSchema.parse({ id: req.params.id });
      const body = UpdateConfigSchema.parse(req.body);

      // Verify agent exists
      const state = stateStore.getAgentState(params.id);
      if (!state) {
        return res.status(404).json({ error: `Agent ${params.id} not found` });
      }

      // Update config
      stateStore.updateConfig(params.id, {
        maxRiskPerTradePct: body.maxRiskPerTradePct,
        maxExposurePct: body.maxExposurePct,
      });

      // Return updated state
      const updatedState = stateStore.getAgentState(params.id);
      res.json({
        message: `Agent ${params.id} config updated`,
        state: updatedState,
      });
    } catch (error) {
      if (error instanceof z.ZodError) {
        return res.status(400).json({ error: 'Invalid request', details: error.errors });
      }
      if (error instanceof Error && error.message.includes('not found')) {
        return res.status(404).json({ error: error.message });
      }
      console.error('[API] Error in PATCH /agents/:id/config:', error);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * GET /replay
   * Get replay data (equity + trades + decisions) for an agent
   */
  router.get('/replay', (req: Request, res: Response) => {
    try {
      const query = ReplayQuerySchema.parse(req.query);

      // Verify agent exists
      const state = stateStore.getAgentState(query.agentId);
      if (!state) {
        return res.status(404).json({ error: `Agent ${query.agentId} not found` });
      }

      // Get equity, trades, and decisions
      const equity = equityStore.get(query.agentId, query.from, query.to);
      const tradesResult = logStore.queryTrades(query.agentId, query.from, query.to);
      const decisionsResult = logStore.queryDecisions(query.agentId, query.from, query.to);
      
      const trades = tradesResult.items;
      const decisions = decisionsResult.items;

      res.json({
        agentId: query.agentId,
        from: query.from || null,
        to: query.to || null,
        equity,
        trades,
        decisions,
      });
    } catch (error) {
      if (error instanceof z.ZodError) {
        return res.status(400).json({ error: 'Invalid request', details: error.errors });
      }
      console.error('[API] Error in GET /replay:', error);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * POST /chat
   * Chat endpoint: Send message to agent and get LLM response
   */
  router.post('/chat', async (req: Request, res: Response) => {
    try {
      const body = ChatRequestSchema.parse(req.body);

      if (!chatStore) {
        return res.status(503).json({
          success: false,
          mode: 'mock',
          errorCode: 'SERVICE_UNAVAILABLE',
          error: 'Chat service not available',
        });
      }

      const chatService = new ChatService(chatStore, stateStore, logStore);
      const response = await chatService.processMessage(
        body.agentId,
        body.message,
        body.clientTimestamp
      );

      // Always return JSON with proper status code (never HTML)
      if (response.success) {
        res.status(200).json(response);
      } else {
        // Map error codes to HTTP status codes
        const statusCode = 
          response.errorCode === 'AGENT_NOT_FOUND' ? 404 :
          response.errorCode === 'INVALID_REQUEST' ? 400 :
          response.errorCode === 'LLM_ERROR' ? 502 :
          500;
        
        res.status(statusCode).json(response);
      }
    } catch (error) {
      if (error instanceof z.ZodError) {
        // Always return JSON (never HTML) on validation errors
        return res.status(400).json({
          success: false,
          mode: 'mock',
          errorCode: 'INVALID_REQUEST',
          error: 'Invalid request',
          details: error.errors,
        });
      }
      console.error('[API] Error in POST /chat:', error);
      // Always return JSON (never HTML) on internal errors
      res.status(500).json({
        success: false,
        mode: 'mock',
        errorCode: 'INTERNAL_ERROR',
        error: 'Internal server error',
      });
    }
  });

  /**
   * GET /debug/markets
   * Debug endpoint: Returns 5 market snapshots with price and orderbook data
   */
  router.get('/debug/markets', async (req: Request, res: Response) => {
    try {
      if (!marketDataService) {
        return res.status(503).json({ error: 'MarketDataService not available' });
      }

      const snapshots = await marketDataService.getAllMarketSnapshots();
      const limited = snapshots.slice(0, 5);

      // Format response with key fields for debugging
      const formatted = limited.map((snapshot) => ({
        id: snapshot.id,
        title: snapshot.title,
        status: snapshot.status,
        yes: {
          price: snapshot.yes.price,
          impliedProb: snapshot.yes.impliedProb,
          bestBid: snapshot.yes.bestBid,
          bestAsk: snapshot.yes.bestAsk,
          lastTradedPrice: snapshot.yes.lastTradedPrice,
        },
        no: {
          price: snapshot.no.price,
          impliedProb: snapshot.no.impliedProb,
          bestBid: snapshot.no.bestBid,
          bestAsk: snapshot.no.bestAsk,
          lastTradedPrice: snapshot.no.lastTradedPrice,
        },
        lastUpdated: snapshot.lastUpdated,
      }));

      res.json({
        count: formatted.length,
        total: snapshots.length,
        markets: formatted,
      });
    } catch (error) {
      console.error('[API] Error in GET /debug/markets:', error);
      res.status(500).json({ error: 'Internal server error', message: error instanceof Error ? error.message : 'Unknown error' });
    }
  });

  return router;
}

