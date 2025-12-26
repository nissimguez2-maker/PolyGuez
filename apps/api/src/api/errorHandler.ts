import { Request, Response, NextFunction } from 'express';

/**
 * Error handling middleware
 * Handles different error types and returns appropriate status codes
 */
export function errorHandler(
  error: Error,
  req: Request,
  res: Response,
  next: NextFunction
): void {
  // Log error
  console.error('[API] Error:', error);

  // Handle specific error types
  if (error.message.includes('not found')) {
    res.status(404).json({ error: error.message });
    return;
  }

  // External API errors (e.g., MarketData fetch failures)
  // These should return 502 (Bad Gateway) or 503 (Service Unavailable)
  if (error.message.includes('fetch') || error.message.includes('network') || error.message.includes('timeout')) {
    res.status(503).json({ 
      error: 'External service unavailable',
      message: 'Failed to fetch data from external service',
    });
    return;
  }

  // Default to 500 for unexpected errors
  res.status(500).json({ 
    error: 'Internal server error',
    message: process.env.NODE_ENV === 'development' ? error.message : undefined,
  });
}

/**
 * Async error wrapper for route handlers
 * Catches async errors and passes them to error handler
 */
export function asyncHandler(
  fn: (req: Request, res: Response, next: NextFunction) => Promise<void>
) {
  return (req: Request, res: Response, next: NextFunction) => {
    Promise.resolve(fn(req, res, next)).catch(next);
  };
}

