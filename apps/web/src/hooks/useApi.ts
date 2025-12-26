import { useState, useCallback } from 'react';
import { ApiClientError } from '../api/client';

/**
 * Hook for API calls with loading/error/retry states
 */
export function useApi<T>(
  fetchFn: () => Promise<T>,
  options?: { immediate?: boolean }
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(options?.immediate !== false);
  const [error, setError] = useState<ApiClientError | null>(null);

  const execute = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchFn();
      setData(result);
      return result;
    } catch (err) {
      const apiError =
        err instanceof ApiClientError
          ? err
          : new ApiClientError(500, { error: 'Unknown error' });
      setError(apiError);
      throw apiError;
    } finally {
      setLoading(false);
    }
  }, [fetchFn]);

  const retry = useCallback(() => {
    return execute();
  }, [execute]);

  return { data, loading, error, execute, retry };
}

