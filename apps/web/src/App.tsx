import { useState, useCallback, Component, ErrorInfo, ReactNode } from 'react';
import { Dashboard } from './components/Dashboard';
import { AgentsView } from './components/AgentsView';
import { ReplayView } from './components/ReplayView';
import { ChatView } from './components/ChatView';
import { AppShell } from './layout/AppShell';
import { DebugInfo } from './components/DebugInfo';

type View = 'dashboard' | 'agents' | 'replay' | 'chat';

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('React Error Boundary caught:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '40px', background: '#1a1a1a', color: '#fff', fontFamily: 'monospace' }}>
          <h1 style={{ color: '#ef4444' }}>⚠️ React Error</h1>
          <pre style={{ background: '#0a0a0a', padding: '20px', borderRadius: '8px', overflow: 'auto' }}>
            {this.state.error?.toString()}
            {'\n\n'}
            {this.state.error?.stack}
          </pre>
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: '20px',
              padding: '10px 20px',
              background: '#3b82f6',
              color: '#fff',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            Reload Page
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

function App() {
  const [view, setView] = useState<View>('dashboard');
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  const handleAgentClick = (agentId: string) => {
    setSelectedAgentId(agentId);
    setView('agents');
  };

  const handleNavigate = (newView: View) => {
    setView(newView);
    if (newView !== 'agents') {
      setSelectedAgentId(null);
    }
  };

  const handleOpenChat = (agentId: string) => {
    setSelectedAgentId(agentId);
    setView('chat');
  };

  const handleOpenDetails = useCallback((agentId: string) => {
    setSelectedAgentId(agentId);
  }, []);

  const handleSelectionChange = useCallback((agentId: string | null) => {
    setSelectedAgentId(agentId);
  }, []);

  // Debug: Log render (only in dev)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  if ((import.meta as any).env?.DEV || (import.meta as any).env?.MODE === 'development') {
    console.log('[App] Rendering, view:', view, 'selectedAgentId:', selectedAgentId);
  }

  try {
    return (
      <ErrorBoundary>
        <AppShell currentView={view} onNavigate={handleNavigate}>
          {view === 'dashboard' && <Dashboard onAgentClick={handleAgentClick} />}
          {view === 'agents' && (
            <AgentsView
              onOpenChat={handleOpenChat}
              onOpenDetails={handleOpenDetails}
              initialSelectedId={selectedAgentId}
              onSelectionChange={handleSelectionChange}
            />
          )}
          {view === 'replay' && <ReplayView />}
          {view === 'chat' && <ChatView />}
        </AppShell>
      </ErrorBoundary>
    );
  } catch (error) {
    console.error('[App] Render error:', error);
    return <DebugInfo />;
  }
}

export default App;
