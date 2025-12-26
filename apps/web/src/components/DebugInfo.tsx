/**
 * Debug component to verify React is rendering
 */
export function DebugInfo() {
  return (
    <div style={{ padding: '20px', background: '#1a1a1a', color: '#fff', fontFamily: 'monospace' }}>
      <h1>Debug: React is rendering</h1>
      <p>If you see this, React is working.</p>
      <p>Time: {new Date().toISOString()}</p>
    </div>
  );
}

