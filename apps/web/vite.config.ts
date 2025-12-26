import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@domain': path.resolve(__dirname, '../../packages/domain/src'),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 3000,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:3001',
        changeOrigin: true,
        // Rewrite removes /api prefix: /api/agents -> /agents
        // This ensures API routes match backend (no /api prefix in Express routes)
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
});

