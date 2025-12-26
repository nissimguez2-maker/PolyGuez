import { describe, it, expect } from 'vitest';
import { InMemoryChatStore } from './ChatStore';
import type { ChatMessage } from './ChatStore';

describe('ChatStore', () => {
  describe('stores and returns history', () => {
    it('should store messages and return them in order', () => {
      const store = new InMemoryChatStore();
      const agentId = 'agent-1';

      const msg1: ChatMessage = {
        role: 'user',
        content: 'Hello',
        timestamp: '2024-01-01T00:00:00Z',
      };

      const msg2: ChatMessage = {
        role: 'assistant',
        content: 'Hi there!',
        timestamp: '2024-01-01T00:00:01Z',
      };

      store.addMessage(agentId, msg1);
      store.addMessage(agentId, msg2);

      const messages = store.getMessages(agentId);
      expect(messages).toHaveLength(2);
      expect(messages[0].content).toBe('Hello');
      expect(messages[1].content).toBe('Hi there!');
    });
  });

  describe('trims history correctly', () => {
    it('should trim to max 50 messages, removing oldest first', () => {
      const store = new InMemoryChatStore();
      const agentId = 'agent-1';

      // Add 55 messages
      for (let i = 0; i < 55; i++) {
        store.addMessage(agentId, {
          role: 'user',
          content: `Message ${i}`,
          timestamp: new Date().toISOString(),
        });
      }

      const messages = store.getMessages(agentId);
      expect(messages).toHaveLength(50);
      expect(messages[0].content).toBe('Message 5'); // First 5 removed
      expect(messages[49].content).toBe('Message 54'); // Last one kept
    });

    it('should keep all messages when under limit', () => {
      const store = new InMemoryChatStore();
      const agentId = 'agent-1';

      // Add 30 messages
      for (let i = 0; i < 30; i++) {
        store.addMessage(agentId, {
          role: 'user',
          content: `Message ${i}`,
          timestamp: new Date().toISOString(),
        });
      }

      const messages = store.getMessages(agentId);
      expect(messages).toHaveLength(30);
      expect(messages[0].content).toBe('Message 0');
      expect(messages[29].content).toBe('Message 29');
    });
  });
});

