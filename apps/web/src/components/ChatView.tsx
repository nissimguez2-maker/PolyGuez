import { useState, useEffect } from 'react';
import { api, AgentsResponse, ChatResponse } from '../api/client';
import { useApi } from '../hooks/useApi';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { SectionHeader } from '../ui/SectionHeader';
import { PageHeader } from '../ui/PageHeader';
import { Badge } from '../ui/Badge';
import { EmptyState } from '../ui/EmptyState';
import { ErrorCard } from '../ui/ErrorCard';
import { tokens } from '../ui/tokens';

export function ChatView() {
  const [agents, setAgents] = useState<AgentsResponse['agents']>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string>('');
  const [chatMessage, setChatMessage] = useState('');
  const [chatHistory, setChatHistory] = useState<Array<{ message: string; response: ChatResponse; timestamp: string }>>([]);

  const {
    data: chatResponse,
    loading: chatLoading,
    error: chatError,
    execute: sendChat,
  } = useApi(
    () => {
      if (!selectedAgentId || !chatMessage.trim()) {
        throw new Error('Please select an agent and enter a message');
      }
      return api.chat(selectedAgentId, chatMessage);
    },
    { immediate: false }
  );

  // Fetch agents list
  useEffect(() => {
    api
      .getAgents()
      .then((response) => {
        setAgents(response.agents);
        if (response.agents.length > 0 && !selectedAgentId) {
          setSelectedAgentId(response.agents[0].id);
        }
      })
      .catch((err) => {
        console.error('Failed to fetch agents:', err);
      });
  }, []);

  // Add to history when response arrives
  useEffect(() => {
    if (chatResponse && chatMessage) {
      setChatHistory((prev) => [
        ...prev,
        {
          message: chatMessage,
          response: chatResponse,
          timestamp: new Date().toISOString(),
        },
      ]);
      setChatMessage('');
      // Store chat mode in localStorage
      if (chatResponse.mode) {
        localStorage.setItem('chatMode', chatResponse.mode);
      }
    }
  }, [chatResponse, chatMessage]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedAgentId || !chatMessage.trim()) return;
    try {
      await sendChat();
    } catch (err) {
      // Error handled by useApi
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Chat"
        description="Interact with agents using natural language"
      />
      <Card>
        <SectionHeader title="Chat with Agent" />
        <div className="mb-4">
          <label className={`block ${tokens.typography.label} mb-2`}>Select Agent</label>
          <select
            value={selectedAgentId}
            onChange={(e) => setSelectedAgentId(e.target.value)}
            className={`w-full px-3 py-2 bg-zinc-800/50 border border-zinc-700/50 ${tokens.radii.md} text-zinc-100 placeholder-zinc-500 ${tokens.focus.ringTeal} focus:border-teal-500/50 ${tokens.transitions.fast}`}
          >
            <option value="">Select agent...</option>
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
        </div>
      </Card>

      {/* Chat History */}
      {chatHistory.length > 0 && (
        <Card>
          <SectionHeader title="Chat History" />
          <div className="space-y-4 max-h-[500px] overflow-y-auto">
            {chatHistory.map((entry, index) => (
              <div key={index} className="space-y-2">
                <div className="flex items-center gap-2">
                  <div className="text-sm font-medium text-zinc-300">You:</div>
                  <div className="text-xs text-zinc-500">
                    {new Date(entry.timestamp).toLocaleString()}
                  </div>
                </div>
                <div className="pl-4 text-sm text-zinc-400">{entry.message}</div>
                <div className="flex items-center gap-2 mt-2">
                  <Badge status={entry.response.success ? 'running' : 'error'}>
                    {entry.response.mode}
                  </Badge>
                  {entry.response.timestamp && (
                    <div className="text-xs text-zinc-500">
                      {new Date(entry.response.timestamp).toLocaleString()}
                    </div>
                  )}
                </div>
                {entry.response.message && (
                  <div className="pl-4 mt-1">
                    <Card padding="sm">
                      <p className="text-sm text-zinc-300 whitespace-pre-wrap">
                        {entry.response.message}
                      </p>
                    </Card>
                  </div>
                )}
                {entry.response.error && (
                  <div className="pl-4 mt-1">
                    <ErrorCard message={entry.response.error} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Chat Input */}
      <Card>
        <SectionHeader title="New Message" />
        {chatError && (
          <div className="mb-4">
            <ErrorCard message={chatError.message} />
          </div>
        )}
        {chatHistory.length === 0 && (
          <EmptyState
            title="No messages yet"
            description="Select an agent and send a message to start chatting."
          />
        )}
        <form onSubmit={handleSubmit} className="space-y-4">
          <textarea
            value={chatMessage}
            onChange={(e) => setChatMessage(e.target.value)}
            placeholder="Type your message..."
            className={`w-full px-3 py-2 bg-zinc-800/50 border border-zinc-700/50 ${tokens.radii.md} text-zinc-100 placeholder-zinc-500 ${tokens.focus.ringTeal} focus:border-teal-500/50 resize-none ${tokens.transitions.fast}`}
            rows={6}
            disabled={!selectedAgentId}
          />
          <div className="flex justify-end">
            <Button
              type="submit"
              variant="primary"
              disabled={chatLoading || !chatMessage.trim() || !selectedAgentId}
            >
              {chatLoading ? 'Sending...' : 'Send'}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

