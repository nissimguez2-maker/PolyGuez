import { ReactNode, useState, useEffect } from 'react';
import { tokens } from '../ui/tokens';
import { useHealth } from '../hooks/useHealth';
import { api, AgentsResponse } from '../api/client';
import { Chip } from '../ui/Chip';

interface AppShellProps {
  children: ReactNode;
  currentView: 'dashboard' | 'agents' | 'replay' | 'chat';
  onNavigate: (view: 'dashboard' | 'agents' | 'replay' | 'chat') => void;
}

export function AppShell({ children, currentView, onNavigate }: AppShellProps) {
  const health = useHealth();
  const [currentTime, setCurrentTime] = useState(new Date());
  const [devForceTrades, setDevForceTrades] = useState<'on' | 'off' | 'unknown'>('unknown');
  const [runnerStatus, setRunnerStatus] = useState<'on' | 'off' | 'unknown'>('unknown');
  const [chatMode, setChatMode] = useState<'mock' | 'openai' | null>(null);

  // Update time every second
  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Detect DEV_FORCE_TRADES and Runner status from agents
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const response: AgentsResponse = await api.getAgents();
        // Heuristic: If agent-1 is running and has trades, likely DEV_FORCE_TRADES is on
        const agent1 = response.agents.find((a) => a.id === 'agent-1');
        if (agent1?.status === 'running') {
          try {
            const replayData = await api.getReplay('agent-1');
            // If agent-1 is running and has recent activity, likely DEV mode
            if (replayData.trades.length > 0 || replayData.decisions.length > 0) {
              setDevForceTrades('on');
              setRunnerStatus('on');
            } else {
              setDevForceTrades('off');
              setRunnerStatus('on'); // Runner is on if agent is running
            }
          } catch {
            setDevForceTrades('unknown');
            setRunnerStatus(agent1?.status === 'running' ? 'on' : 'off');
          }
        } else {
          setDevForceTrades('off');
          setRunnerStatus('off');
        }
      } catch {
        setDevForceTrades('unknown');
        setRunnerStatus('unknown');
      }
    };
    checkStatus();
    const interval = setInterval(checkStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  // Detect chat mode from localStorage or recent chat responses
  useEffect(() => {
    const storedMode = localStorage.getItem('chatMode') as 'mock' | 'openai' | null;
    if (storedMode) {
      setChatMode(storedMode);
    }
  }, []);

  const navItems = [
    { id: 'dashboard' as const, label: 'Dashboard', icon: '📊' },
    { id: 'agents' as const, label: 'Agents', icon: '🤖' },
    { id: 'replay' as const, label: 'Replay', icon: '⏮️' },
    { id: 'chat' as const, label: 'Chat', icon: '💬' },
  ];

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100 overflow-hidden">
      {/* Sidebar */}
      <aside className={`${sidebarCollapsed ? 'w-16' : 'w-64'} bg-zinc-900/95 border-r border-zinc-800/50 flex flex-col backdrop-blur-sm transition-all duration-200 shrink-0`}>
        <div className={`p-6 border-b border-zinc-800/50 ${sidebarCollapsed ? 'px-3' : ''}`}>
          {!sidebarCollapsed && (
            <>
              <h1 className="text-xl font-bold text-zinc-100 tracking-tight">Atlas Prediction Lab</h1>
              <p className="text-xs text-zinc-500 mt-1">Trading Operations</p>
            </>
          )}
          {sidebarCollapsed && (
            <div className="text-2xl">⚡</div>
          )}
        </div>
        <nav className="flex-1 p-3 overflow-y-auto">
          <ul className="space-y-1">
            {navItems.map((item) => (
              <li key={item.id}>
                <button
                  onClick={() => onNavigate(item.id)}
                  className={`w-full text-left ${sidebarCollapsed ? 'px-2 justify-center' : 'px-4'} py-2.5 ${tokens.radii.lg} ${tokens.transitions.fast} flex items-center ${tokens.focus.ringZinc} ${
                    currentView === item.id
                      ? 'bg-zinc-800 text-teal-400 shadow-sm'
                      : 'text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-100'
                  }`}
                  title={sidebarCollapsed ? item.label : undefined}
                >
                  <span className={sidebarCollapsed ? '' : 'mr-2'}>{item.icon}</span>
                  {!sidebarCollapsed && <span className="font-medium">{item.label}</span>}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <button
          onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
          className={`m-3 p-2 ${tokens.radii.lg} text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-100 ${tokens.transitions.colors} ${tokens.focus.ringZinc}`}
          title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {sidebarCollapsed ? '→' : '←'}
        </button>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Topbar */}
        <header className={`h-14 bg-zinc-900/95 border-b border-zinc-800/50 backdrop-blur-sm flex items-center justify-between px-6 shrink-0 ${tokens.shadows.sm}`}>
          <div className="flex items-center gap-3">
            <Chip
              label={`API ${health.online ? 'OK' : 'Down'}`}
              status={health.online ? 'success' : 'error'}
              icon={
                <div
                  className={`w-1.5 h-1.5 rounded-full ${
                    health.online ? 'bg-emerald-400' : 'bg-red-400'
                  }`}
                />
              }
            />
            <Chip
              label={`Runner ${runnerStatus === 'on' ? 'ON' : runnerStatus === 'off' ? 'OFF' : '?'}`}
              status={
                runnerStatus === 'on' ? 'success' : runnerStatus === 'off' ? 'neutral' : 'warning'
              }
            />
            {devForceTrades === 'on' && (
              <Chip label="DEV" status="warning" />
            )}
            {chatMode && (
              <Chip
                label={chatMode === 'openai' ? 'OpenAI' : 'Mock'}
                status={chatMode === 'openai' ? 'info' : 'neutral'}
              />
            )}
          </div>
          <div className="flex items-center gap-4">
            <div className={`${tokens.typography.mono} text-zinc-400`}>
              {currentTime.toLocaleTimeString()}
            </div>
          </div>
        </header>

        {/* Content area */}
        <main className="flex-1 overflow-y-auto bg-zinc-950">
          <div className="max-w-7xl mx-auto p-6 lg:p-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
