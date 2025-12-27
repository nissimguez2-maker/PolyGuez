/**
 * Chat message types
 */
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  clientTimestamp?: string;
}

/**
 * Chat session for an agent
 */
export interface ChatSession {
  agentId: string;
  messages: ChatMessage[];
  createdAt: string;
  updatedAt: string;
}

/**
 * Interface for chat storage
 */
export interface IChatStore {
  /** Get chat session for an agent */
  getSession(agentId: string): ChatSession | undefined;
  /** Add message to chat session */
  addMessage(agentId: string, message: ChatMessage): void;
  /** Get all messages for an agent */
  getMessages(agentId: string): ChatMessage[];
  /** Clear chat history for an agent */
  clearHistory(agentId: string): void;
}

/**
 * In-memory implementation of chat store
 */
export class InMemoryChatStore implements IChatStore {
  private sessions: Map<string, ChatSession> = new Map();
  private readonly MAX_MESSAGES_PER_AGENT = 50;

  getSession(agentId: string): ChatSession | undefined {
    return this.sessions.get(agentId);
  }

  addMessage(agentId: string, message: ChatMessage): void {
    let session = this.sessions.get(agentId);
    
    if (!session) {
      const now = new Date().toISOString();
      session = {
        agentId,
        messages: [],
        createdAt: now,
        updatedAt: now,
      };
      this.sessions.set(agentId, session);
    }

    session.messages.push(message);
    
    // Trim history to max 50 messages (remove oldest)
    if (session.messages.length > this.MAX_MESSAGES_PER_AGENT) {
      const excess = session.messages.length - this.MAX_MESSAGES_PER_AGENT;
      session.messages = session.messages.slice(excess);
    }
    
    session.updatedAt = new Date().toISOString();
  }

  getMessages(agentId: string): ChatMessage[] {
    const session = this.sessions.get(agentId);
    return session?.messages || [];
  }

  clearHistory(agentId: string): void {
    const session = this.sessions.get(agentId);
    if (session) {
      session.messages = [];
      session.updatedAt = new Date().toISOString();
    }
  }
}

