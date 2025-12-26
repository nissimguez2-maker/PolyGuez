import OpenAI from 'openai';
import { ChatMessage, IChatStore } from '../stores/ChatStore';
import { IStateStore } from '../stores/StateStore';
import { ILogStore } from '../logging/LogStore';

/**
 * Error codes for chat responses
 */
export enum ChatErrorCode {
  AGENT_NOT_FOUND = 'AGENT_NOT_FOUND',
  LLM_ERROR = 'LLM_ERROR',
  INVALID_REQUEST = 'INVALID_REQUEST',
  INTERNAL_ERROR = 'INTERNAL_ERROR',
}

/**
 * Chat response structure
 */
export interface ChatResponse {
  success: boolean;
  mode: 'mock' | 'openai';
  errorCode?: ChatErrorCode;
  error?: string;
  message?: string;
  timestamp?: string;
  agentId?: string;
}

/**
 * Chat service for handling LLM interactions
 */
export class ChatService {
  private openai: OpenAI | null = null;
  private chatStore: IChatStore;
  private stateStore: IStateStore;
  private logStore: ILogStore;

  constructor(
    chatStore: IChatStore,
    stateStore: IStateStore,
    logStore: ILogStore
  ) {
    this.chatStore = chatStore;
    this.stateStore = stateStore;
    this.logStore = logStore;

    // Initialize OpenAI client if API key is available
    const apiKey = process.env.OPENAI_API_KEY;
    if (apiKey) {
      this.openai = new OpenAI({ apiKey });
    } else {
      console.warn('[ChatService] OPENAI_API_KEY not set, chat will return mock responses');
    }
  }

  /**
   * Build system prompt based on agent state and context
   */
  private buildSystemPrompt(agentId: string): string {
    const state = this.stateStore.getAgentState(agentId);
    if (!state) {
      return `You are an AI assistant helping with agent ${agentId}.`;
    }

    // Get recent decisions and trades for context
    const decisionsResult = this.logStore.queryDecisions(agentId, undefined, undefined, {
      limit: 5,
      offset: 0,
    });
    const tradesResult = this.logStore.queryTrades(agentId, undefined, undefined, {
      limit: 5,
      offset: 0,
    });

    const recentDecisions = decisionsResult.items.slice(-3);
    const recentTrades = tradesResult.items.slice(-3);

    let context = `You are an AI assistant for agent "${state.name}" (${agentId}).
Agent Status: ${state.status}
Strategy Type: ${state.strategyType}
Current Bankroll: $${state.bankroll.toFixed(2)}
Total PnL: $${state.pnlTotal.toFixed(2)}
Open Positions: ${state.openPositions.length}`;

    if (recentDecisions.length > 0) {
      context += `\n\nRecent Decisions:`;
      recentDecisions.forEach((d, i) => {
        context += `\n${i + 1}. ${new Date(d.timestamp).toLocaleString()}: ${d.intents.length} intents, ${d.filledCount} filled, ${d.rejectedCount} rejected`;
      });
    }

    if (recentTrades.length > 0) {
      context += `\n\nRecent Trades:`;
      recentTrades.forEach((t, i) => {
        context += `\n${i + 1}. ${new Date(t.timestamp).toLocaleString()}: ${t.fill.side} ${t.fill.shares} shares @ $${t.fill.price.toFixed(3)}`;
      });
    }

    context += `\n\nHelp the user understand the agent's behavior, performance, and trading decisions.`;

    return context;
  }

  /**
   * Build messages array for LLM (system + history + user message)
   */
  private buildMessages(agentId: string, userMessage: string): Array<{ role: 'system' | 'user' | 'assistant'; content: string }> {
    const systemPrompt = this.buildSystemPrompt(agentId);
    const history = this.chatStore.getMessages(agentId);

    const messages: Array<{ role: 'system' | 'user' | 'assistant'; content: string }> = [
      { role: 'system', content: systemPrompt },
    ];

    // Add history (skip system messages, convert to LLM format)
    for (const msg of history) {
      if (msg.role !== 'system') {
        messages.push({
          role: msg.role,
          content: msg.content,
        });
      }
    }

    // Add current user message
    messages.push({ role: 'user', content: userMessage });

    return messages;
  }

  /**
   * Generate request ID for logging
   */
  private generateRequestId(): string {
    return `req_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
  }

  /**
   * Log chat interaction (safe by default: dev vs prod)
   */
  private logChatInteraction(
    requestId: string,
    agentId: string,
    latencyMs: number,
    errorCode?: ChatErrorCode,
    userMessageSnippet?: string,
    assistantMessageSnippet?: string
  ): void {
    const isDev = process.env.NODE_ENV !== 'production';
    
    if (isDev) {
      // Dev: log requestId, agentId, latency, errorCode + optional snippets
      const logData: Record<string, unknown> = {
        requestId,
        agentId,
        latencyMs,
      };
      
      if (errorCode) {
        logData.errorCode = errorCode;
      }
      
      if (userMessageSnippet) {
        logData.userMessageSnippet = userMessageSnippet;
      }
      
      if (assistantMessageSnippet) {
        logData.assistantMessageSnippet = assistantMessageSnippet;
      }
      
      console.log('[ChatService]', logData);
    }
    // Prod: no logging (safe by default)
  }

  /**
   * Process chat message and return response
   */
  async processMessage(
    agentId: string,
    message: string,
    clientTimestamp?: string
  ): Promise<ChatResponse> {
    const requestId = this.generateRequestId();
    const startTime = Date.now();

    // Verify agent exists
    const state = this.stateStore.getAgentState(agentId);
    if (!state) {
      const latencyMs = Date.now() - startTime;
      this.logChatInteraction(requestId, agentId, latencyMs, ChatErrorCode.AGENT_NOT_FOUND);
      
      return {
        success: false,
        mode: 'mock',
        errorCode: ChatErrorCode.AGENT_NOT_FOUND,
        error: `Agent ${agentId} not found`,
      };
    }

    // Add user message to history
    const userMessage: ChatMessage = {
      role: 'user',
      content: message,
      timestamp: new Date().toISOString(),
      clientTimestamp,
    };
    this.chatStore.addMessage(agentId, userMessage);

    // Build messages for LLM
    const messages = this.buildMessages(agentId, message);

    let assistantResponse: string;
    let mode: 'mock' | 'openai' = 'mock';

    // Call LLM or return mock response
    if (this.openai) {
      mode = 'openai';
      try {
        const completion = await this.openai.chat.completions.create({
          model: process.env.OPENAI_MODEL || 'gpt-4o-mini',
          messages: messages,
          temperature: 0.7,
          max_tokens: 1000,
        });

        assistantResponse = completion.choices[0]?.message?.content || 'No response from LLM';
        
        // Log tool calls if any (dev only)
        if (process.env.NODE_ENV !== 'production' && completion.choices[0]?.message?.tool_calls) {
          console.log('[ChatService] Tool calls:', JSON.stringify(completion.choices[0].message.tool_calls, null, 2));
        }
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : 'Unknown LLM error';
        const latencyMs = Date.now() - startTime;
        this.logChatInteraction(
          requestId,
          agentId,
          latencyMs,
          ChatErrorCode.LLM_ERROR,
          message.substring(0, 50)
        );
        
        return {
          success: false,
          mode: 'openai',
          errorCode: ChatErrorCode.LLM_ERROR,
          error: `LLM error: ${errorMessage}`,
        };
      }
    } else {
      // Mock response when OpenAI is not configured
      assistantResponse = `I understand you're asking about agent "${state.name}". This is a mock response. Please set OPENAI_API_KEY environment variable to enable real LLM responses.`;
    }

    // Add assistant response to history
    const assistantMessage: ChatMessage = {
      role: 'assistant',
      content: assistantResponse,
      timestamp: new Date().toISOString(),
    };
    this.chatStore.addMessage(agentId, assistantMessage);

    // Log interaction (safe logging)
    const latencyMs = Date.now() - startTime;
    this.logChatInteraction(
      requestId,
      agentId,
      latencyMs,
      undefined,
      message.substring(0, 50),
      assistantResponse.substring(0, 50)
    );

    return {
      success: true,
      mode,
      message: assistantResponse,
      timestamp: assistantMessage.timestamp,
      agentId,
    };
  }
}

