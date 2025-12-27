import { AgentRunner } from './AgentRunner';

/**
 * Scheduler for running agent ticks at regular intervals
 * Implements overlap guard to prevent concurrent tick execution
 */
export class Scheduler {
  private runner: AgentRunner;
  private intervalMs: number;
  private intervalId: NodeJS.Timeout | null = null;
  private isRunning: boolean = false; // Overlap guard (mutex)

  constructor(runner: AgentRunner, intervalSeconds: number = 60) {
    this.runner = runner;
    this.intervalMs = intervalSeconds * 1000;
  }

  /**
   * Start the scheduler
   */
  start(): void {
    if (this.intervalId !== null) {
      console.warn('[Scheduler] Already running, ignoring start()');
      return;
    }

    console.log(`[Scheduler] Starting with interval ${this.intervalMs / 1000}s`);
    
    // Run first tick immediately
    this.runTick();

    // Schedule subsequent ticks
    this.intervalId = setInterval(() => {
      this.runTick();
    }, this.intervalMs);
  }

  /**
   * Stop the scheduler
   */
  stop(): void {
    if (this.intervalId === null) {
      return;
    }

    clearInterval(this.intervalId);
    this.intervalId = null;
    console.log('[Scheduler] Stopped');
  }

  /**
   * Run a single tick with overlap guard
   */
  private async runTick(): Promise<void> {
    // Check overlap guard
    if (this.isRunning) {
      console.warn('[Scheduler] Previous tick still running, skipping this tick');
      return;
    }

    // Set flag
    this.isRunning = true;

    // Dev-only: log tick start
    const isDev = process.env.NODE_ENV !== 'production';
    const tickStartTime = isDev ? Date.now() : undefined;
    if (isDev && tickStartTime !== undefined) {
      console.log(`[Scheduler] 🟢 TICK START at ${new Date().toISOString()}`);
    }

    try {
      await this.runner.tick();
    } catch (error) {
      // Log error but don't crash - continue next tick
      console.error('[Scheduler] Error in tick:', error);
    } finally {
      // Dev-only: log tick end with duration
      if (isDev && tickStartTime !== undefined) {
        const duration = Date.now() - tickStartTime;
        console.log(`[Scheduler] 🔴 TICK END at ${new Date().toISOString()} (duration: ${duration}ms)`);
      }

      // Always release flag
      this.isRunning = false;
    }
  }

  /**
   * Check if scheduler is currently running
   */
  isActive(): boolean {
    return this.intervalId !== null;
  }
}

