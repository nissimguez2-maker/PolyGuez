import { MarketSnapshot } from '@domain';
import { MarketDataService } from '../marketData/MarketDataService';
import { IStateStore } from '../stores/StateStore';
import { IEquityStore } from '../stores/EquityStore';
import { ILogStore } from '../logging/LogStore';
import { AgentRegistry } from '../agents/AgentRegistry';
import { applyOrderIntents } from '../engine/engine';
import { TradeFill } from '../engine/types';
import { OrderIntent } from '@domain';

/**
 * AgentRunner orchestrates the tick loop for all agents
 */
export class AgentRunner {
  private marketDataService: MarketDataService;
  private stateStore: IStateStore;
  private equityStore: IEquityStore;
  private logStore: ILogStore;

  constructor(
    marketDataService: MarketDataService,
    stateStore: IStateStore,
    equityStore: IEquityStore,
    logStore: ILogStore
  ) {
    this.marketDataService = marketDataService;
    this.stateStore = stateStore;
    this.equityStore = equityStore;
    this.logStore = logStore;
  }

  /**
   * Execute one tick: fetch market data and process all agents
   */
  async tick(): Promise<void> {
    // 1. Fetch all market snapshots
    let snapshots: MarketSnapshot[];
    try {
      snapshots = await this.marketDataService.getAllMarketSnapshots();
    } catch (error) {
      // If MarketData fails: log and continue (don't crash)
      console.error('[AgentRunner] Failed to fetch market snapshots:', error);
      return; // Skip this tick, continue next tick
    }

    // If snapshots are empty, log and continue
    if (snapshots.length === 0) {
      console.warn('[AgentRunner] No market snapshots available, skipping tick');
      return;
    }

    // 2. Process each agent
    const agentIds = this.stateStore.listAgents();

    for (const agentId of agentIds) {
      try {
        await this.processAgent(agentId, snapshots);
      } catch (error) {
        // Isolate agent errors: don't let one agent failure stop others
        console.error(`[AgentRunner] Error processing agent ${agentId}:`, error);
        // Continue with next agent
      }
    }
  }

  /**
   * Process a single agent: get state, create strategy, decide, apply intents, update stores
   */
  private async processAgent(agentId: string, markets: MarketSnapshot[]): Promise<void> {
    // Get agent state
    const state = this.stateStore.getAgentState(agentId);
    if (!state) {
      console.warn(`[AgentRunner] Agent ${agentId} not found in StateStore`);
      return;
    }

    // Skip if paused
    if (state.status === 'paused') {
      return;
    }

    // Get strategy config
    const strategyConfig = this.stateStore.getStrategyConfig(agentId);
    if (!strategyConfig) {
      console.warn(`[AgentRunner] No strategy config found for agent ${agentId}`);
      return;
    }

    // Create strategy from registry
    let strategy;
    try {
      strategy = AgentRegistry.createStrategy(
        state.strategyType as 'flatValue' | 'fractionalKelly' | 'randomBaseline',
        strategyConfig
      );
    } catch (error) {
      console.error(`[AgentRunner] Failed to create strategy for agent ${agentId}:`, error);
      return;
    }

    // Get order intents from strategy
    let intents: OrderIntent[];
    try {
      intents = strategy.decide({ state, markets });
    } catch (error) {
      console.error(`[AgentRunner] Strategy.decide() failed for agent ${agentId}:`, error);
      return;
    }

    // Apply order intents to get new state and fills
    const result = applyOrderIntents(state, markets, intents);

    // Update state store
    this.stateStore.setAgentState(agentId, result.newState);

    // Calculate equity (bankroll + unrealized PnL)
    const totalUnrealizedPnl = result.newState.openPositions.reduce(
      (sum, pos) => sum + pos.unrealizedPnl,
      0
    );
    const equity = result.newState.bankroll + totalUnrealizedPnl;

    // Append to equity store
    this.equityStore.append(agentId, {
      timestamp: result.newState.timestamp,
      equity,
      bankroll: result.newState.bankroll,
      pnlTotal: result.newState.pnlTotal,
    });

    // Log decision
    const numberOfMarketsConsidered = markets.length;
    const numberOfIntents = intents.length;
    const summary = intents.length > 0 
      ? `${intents.length} intent(s), ${result.fills.length} filled, ${result.rejected.length} rejected`
      : 'No intents';

    this.logStore.addDecision({
      agentId,
      timestamp: result.newState.timestamp,
      intents,
      filledCount: result.fills.length,
      rejectedCount: result.rejected.length,
      metadata: {
        numberOfMarketsConsidered,
        numberOfIntents,
        summary,
      },
    });

    // Log each fill with explainability from matching intent
    for (const fill of result.fills) {
      const matchingIntent = intents.find(
        (intent) =>
          intent.marketId === fill.marketId &&
          intent.outcome === fill.outcome &&
          intent.side === fill.side
      );

      this.logStore.addTrade({
        agentId,
        timestamp: fill.timestamp,
        fill,
        reason: matchingIntent?.reason,
        modelProb: matchingIntent?.modelProb,
        marketProb: matchingIntent?.marketProb,
        edgePct: matchingIntent?.edgePct,
        stakePct: matchingIntent?.stakePct,
      });
    }
  }
}

