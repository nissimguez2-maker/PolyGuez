import { useState, useEffect } from 'react';
import { api, HealthResponse } from '../api/client';

interface HealthStatus {
  online: boolean;
  timestamp?: string;
}

export function useHealth(pollInterval = 10000) {
  const [status, setStatus] = useState<HealthStatus>({ online: false });

  const checkHealth = async () => {
    try {
      const data: HealthResponse = await api.health();
      setStatus({ online: true, timestamp: data.timestamp });
    } catch {
      setStatus({ online: false });
    }
  };

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, pollInterval);
    return () => clearInterval(interval);
  }, [pollInterval]);

  return status;
}

