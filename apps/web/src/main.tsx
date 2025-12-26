import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

// Debug: Verify root element exists
const rootElement = document.getElementById('root');
if (!rootElement) {
  console.error('[main.tsx] Root element not found!');
  document.body.innerHTML = '<div style="padding: 40px; color: red; font-family: monospace;"><h1>Error: Root element not found</h1><p>Expected &lt;div id="root"&gt;&lt;/div&gt; in index.html</p></div>';
} else {
  console.log('[main.tsx] Root element found, mounting React...');
  try {
    ReactDOM.createRoot(rootElement).render(
      <React.StrictMode>
        <App />
      </React.StrictMode>
    );
    console.log('[main.tsx] React mounted successfully');
  } catch (error) {
    console.error('[main.tsx] Failed to mount React:', error);
    rootElement.innerHTML = `
      <div style="padding: 40px; background: #1a1a1a; color: #fff; font-family: monospace;">
        <h1 style="color: #ef4444;">React Mount Error</h1>
        <pre style="background: #0a0a0a; padding: 20px; border-radius: 8px; overflow: auto;">
          ${error instanceof Error ? error.toString() : String(error)}
          ${error instanceof Error ? '\n\n' + error.stack : ''}
        </pre>
      </div>
    `;
  }
}

