import { z } from 'zod';

/**
 * Validation schemas for API requests
 */

// Query parameter schemas
export const AgentIdParamSchema = z.object({
  id: z.string().min(1),
});

export const EquityQuerySchema = z.object({
  from: z.string().datetime().optional(),
  to: z.string().datetime().optional(),
});

export const TradesQuerySchema = z.object({
  limit: z.coerce.number().int().min(1).max(1000).default(50),
  cursor: z.string().optional(), // Index-based cursor (number as string)
});

export const ReplayQuerySchema = z.object({
  agentId: z.string().min(1),
  from: z.string().datetime().optional(),
  to: z.string().datetime().optional(),
});

// Request body schemas
export const ControlActionSchema = z.object({
  action: z.enum(['start', 'pause']),
});

export const UpdateConfigSchema = z.object({
  maxRiskPerTradePct: z.number().min(0).max(100).optional(),
  maxExposurePct: z.number().min(0).max(100).optional(),
});

export const ChatRequestSchema = z.object({
  agentId: z.string().min(1),
  message: z.string().min(1),
  clientTimestamp: z.string().datetime().optional(),
});

