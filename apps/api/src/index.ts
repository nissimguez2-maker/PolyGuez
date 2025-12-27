import express from 'express';
import cors from 'cors';
import { MarketDataService } from './marketData/MarketDataService';
import { InMemoryStateStore } from './stores/StateStore';
import { InMemoryEquityStore } from './stores/EquityStore';
import { InMemoryLogStore } from './logging/LogStore';
import { InMemoryChatStore } from './stores/ChatStore';
import { AgentRunner, Scheduler, seedAgents } from './runner';
import { createRoutes } from './api/routes';
import { errorHandler } from './api/errorHandler';

const app = express();
const PORT = process.env.PORT || 3001;

app.use(cors());
app.use(express.json());
// Error handler for JSON parsing errors - always return JSON (never HTML)
app.use((err: unknown, req: express.Request, res: express.Response, next: express.NextFunction) => {
  if (err instanceof SyntaxError && 'body' in err) {
    return res.status(400).json({
      success: false,
      mode: 'mock',
      errorCode: 'INVALID_REQUEST',
      error: 'Invalid JSON in request body',
    });
  }
  next(err);
});

// Initialize stores
const stateStore = new InMemoryStateStore();
const equityStore = new InMemoryEquityStore();
const logStore = new InMemoryLogStore();
const chatStore = new InMemoryChatStore();

// Initialize market data service
const marketDataService = new MarketDataService({
  maxMarkets: 10,
  fetchOrderBooks: true,
  fetchPrices: true,
});

// Initialize agent runner
const agentRunner = new AgentRunner(
  marketDataService,
  stateStore,
  equityStore,
  logStore
);

// Initialize scheduler (60 second intervals)
const scheduler = new Scheduler(agentRunner, 60);

// Seed agents
seedAgents(stateStore);

// Start scheduler if enabled (default: enabled, can disable with RUNNER_ENABLED=false)
const runnerEnabled = process.env.RUNNER_ENABLED !== 'false';
if (runnerEnabled) {
  scheduler.start();
  console.log('[Server] ✅ Runner enabled - scheduler started');
} else {
  console.log('[Server] ⏸️  Runner disabled (RUNNER_ENABLED=false)');
}

// API routes
app.use('/', createRoutes(stateStore, equityStore, logStore, marketDataService, chatStore));

// Error handling middleware (must be last)
app.use(errorHandler);

app.listen(PORT, () => {
  console.log(`API server running on http://localhost:${PORT}`);
  console.log(`Scheduler started with 60s interval`);
});

