import { describe, it, expect, beforeEach } from 'vitest';
import express, { Express } from 'express';
import request from 'supertest';
import { InMemoryStateStore } from '../stores/StateStore';
import { InMemoryEquityStore } from '../stores/EquityStore';
import { InMemoryLogStore } from '../logging/LogStore';
import { InMemoryChatStore } from '../stores/ChatStore';
import { createRoutes } from './routes';
import { AgentState } from '@domain';

describe('POST /chat', () => {
  let app: Express;
  let stateStore: InMemoryStateStore;
  let chatStore: InMemoryChatStore;

  beforeEach(() => {
    stateStore = new InMemoryStateStore();
    const equityStore = new InMemoryEquityStore();
    const logStore = new InMemoryLogStore();
    chatStore = new InMemoryChatStore();

    // Create a test agent
    const testAgent: AgentState = {
      agentId: 'agent-1',
      name: 'Test Agent',
      strategyType: 'flatValue',
      bankroll: 100,
      startBankroll: 100,
      pnlTotal: 0,
      openPositions: [],
      maxRiskPerTradePct: 5,
      maxExposurePct: 20,
      status: 'running',
      timestamp: new Date().toISOString(),
    };
    stateStore.setAgentState('agent-1', testAgent);

    app = express();
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
    app.use('/', createRoutes(stateStore, equityStore, logStore, undefined, chatStore));
  });

  describe('returns JSON error codes (never HTML) on invalid body', () => {
    it('should return JSON error for missing agentId', async () => {
      const response = await request(app)
        .post('/chat')
        .send({ message: 'Hello' })
        .expect(400);

      expect(response.headers['content-type']).toMatch(/application\/json/);
      expect(response.body).toHaveProperty('success', false);
      expect(response.body).toHaveProperty('errorCode', 'INVALID_REQUEST');
      expect(response.body).toHaveProperty('mode', 'mock');
      expect(typeof response.body).toBe('object');
    });

    it('should return JSON error for missing message', async () => {
      const response = await request(app)
        .post('/chat')
        .send({ agentId: 'agent-1' })
        .expect(400);

      expect(response.headers['content-type']).toMatch(/application\/json/);
      expect(response.body).toHaveProperty('success', false);
      expect(response.body).toHaveProperty('errorCode', 'INVALID_REQUEST');
      expect(response.body).toHaveProperty('mode', 'mock');
      expect(typeof response.body).toBe('object');
    });

    it('should return JSON error for empty message', async () => {
      const response = await request(app)
        .post('/chat')
        .send({ agentId: 'agent-1', message: '' })
        .expect(400);

      expect(response.headers['content-type']).toMatch(/application\/json/);
      expect(response.body).toHaveProperty('success', false);
      expect(response.body).toHaveProperty('errorCode', 'INVALID_REQUEST');
      expect(response.body).toHaveProperty('mode', 'mock');
      expect(typeof response.body).toBe('object');
    });

    it('should return JSON error for invalid JSON body', async () => {
      const response = await request(app)
        .post('/chat')
        .set('Content-Type', 'application/json')
        .send('invalid json')
        .expect(400);

      // Should always return JSON (never HTML) even for invalid JSON
      expect(response.headers['content-type']).toMatch(/application\/json/);
      expect(response.body).toHaveProperty('success', false);
      expect(response.body).toHaveProperty('errorCode', 'INVALID_REQUEST');
      expect(response.body).toHaveProperty('mode', 'mock');
      expect(typeof response.body).toBe('object');
    });
  });
});

