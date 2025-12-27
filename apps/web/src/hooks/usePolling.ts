import { useEffect, useRef } from 'react';

/**
 * Hook for polling with abort on unmount
 */
export function usePolling<T>(
  fetchFn: (signal: AbortSignal) => Promise<T>,
  intervalMs: number,
  enabled = true
): void {
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!enabled) return;

    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;

    const poll = async () => {
      try {
        await fetchFn(signal);
      } catch (error) {
        if (error instanceof Error && error.name === 'AbortError') {
          return; // Expected on unmount
        }
        console.error('Polling error:', error);
      }
    };

    // Initial fetch
    poll();

    // Set up interval
    const intervalId = setInterval(() => {
      if (!signal.aborted) {
        poll();
      }
    }, intervalMs);

    return () => {
      clearInterval(intervalId);
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [fetchFn, intervalMs, enabled]);
}

