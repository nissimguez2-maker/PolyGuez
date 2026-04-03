import express, { Request, Response } from "express";
import { spawn, ChildProcess } from "child_process";
import { EventEmitter } from "events";
import path from "path";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const PORT = 5000;
const REPO = process.env.POLYGUEZ_REPO || path.join(process.env.HOME || "/root", "PolyGuez");

if (!process.env.ANTHROPIC_API_KEY) {
  console.warn("⚠ ANTHROPIC_API_KEY is not set. Agent will fail until it is exported.");
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const messages: Array<{ ts: number; role: string; text: string }> = [];
const queue: string[] = [];
const bus = new EventEmitter();
bus.setMaxListeners(50);

let agentStatus: "idle" | "running" = "idle";
let childProc: ChildProcess | null = null;

function emit(role: string, text: string) {
  const msg = { ts: Date.now(), role, text };
  messages.push(msg);
  bus.emit("msg", msg);
}

// Welcome message
emit("system", `PolyGuez Agent ready. Type any instruction below and press Send.
Examples:
  → Add a Telegram notification when a trade fires
  → Increase min_edge from 0.03 to 0.05
  → Show me the last 5 rows from signal_log in Supabase
  → Fix the bug where velocity_ok blocks all trades`);

// ---------------------------------------------------------------------------
// Agent runner
// ---------------------------------------------------------------------------
function runInstruction(content: string): Promise<void> {
  return new Promise((resolve) => {
    agentStatus = "running";
    bus.emit("statusUpdate", agentStatus);
    emit("system", `▶ Running instruction...`);

    const prompt = `You are an AI coding agent working on the PolyGuez trading bot repo at ${REPO}.
The bot is an algorithmic trading bot for Polymarket BTC 5-minute markets.
Always work on the main branch. After making any code changes, run pytest tests/ and fix failures, then commit and push to main.

USER INSTRUCTION: ${content}`;

    const args = [
      "-p",
      prompt,
      "--output-format",
      "stream-json",
      "--dangerously-skip-permissions",
      "--allowedTools",
      "Read,Write,Edit,Bash,Glob,Grep",
    ];

    const child = spawn("claude", args, {
      cwd: REPO,
      env: { ...process.env },
      stdio: ["ignore", "pipe", "pipe"],
    });

    childProc = child;
    let buf = "";

    child.stdout?.on("data", (chunk: Buffer) => {
      buf += chunk.toString();
      const lines = buf.split("\n");
      buf = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const evt = JSON.parse(line);
          if (evt.type === "assistant" && evt.message?.content) {
            for (const block of evt.message.content) {
              if (block.type === "text" && block.text) {
                emit("assistant", block.text);
              }
            }
          } else if (evt.type === "content_block_delta" && evt.delta?.text) {
            emit("assistant", evt.delta.text);
          } else if (evt.type === "result" && evt.result) {
            emit("result", typeof evt.result === "string" ? evt.result : JSON.stringify(evt.result));
          }
        } catch {
          if (line.trim()) emit("raw", line.trim());
        }
      }
    });

    child.stderr?.on("data", (chunk: Buffer) => {
      const text = chunk.toString().trim();
      if (text) emit("stderr", text);
    });

    child.on("close", (code) => {
      childProc = null;
      if (code === 0) {
        emit("system", `✓ Done`);
      } else {
        emit("system", `✗ Agent exited with code ${code}`);
      }
      agentStatus = "idle";
      bus.emit("statusUpdate", agentStatus);
      resolve();
      processQueue();
    });

    child.on("error", (err) => {
      childProc = null;
      emit("system", `✗ Agent error: ${err.message}`);
      agentStatus = "idle";
      bus.emit("statusUpdate", agentStatus);
      resolve();
      processQueue();
    });
  });
}

function processQueue() {
  if (agentStatus === "running") return;
  const next = queue.shift();
  if (next) {
    runInstruction(next).catch((e) => emit("system", `Agent crash: ${e.message}`));
  }
}

// ---------------------------------------------------------------------------
// Express app
// ---------------------------------------------------------------------------
const app = express();
app.use(express.json());

// SSE
app.get("/api/stream", (_req: Request, res: Response) => {
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.flushHeaders();

  const onMsg = (msg: any) => {
    res.write(`data: ${JSON.stringify({ type: "message", ...msg })}\n\n`);
  };
  const onStatus = (status: string) => {
    res.write(`data: ${JSON.stringify({ type: "statusUpdate", status })}\n\n`);
  };

  bus.on("msg", onMsg);
  bus.on("statusUpdate", onStatus);

  // Send initial state
  res.write(
    `data: ${JSON.stringify({ type: "init", status: agentStatus, messages: messages.slice(-200) })}\n\n`
  );

  _req.on("close", () => {
    bus.off("msg", onMsg);
    bus.off("statusUpdate", onStatus);
  });
});

app.post("/api/instructions", (req: Request, res: Response) => {
  const content = req.body?.content;
  if (!content) return res.status(400).json({ ok: false, error: "content required" });
  emit("user", content);
  if (agentStatus === "running") {
    queue.push(content);
    emit("system", `Queued — will run after current instruction finishes`);
  } else {
    runInstruction(content).catch((e) => emit("system", `Agent crash: ${e.message}`));
  }
  res.json({ ok: true });
});

app.get("/api/messages", (_req: Request, res: Response) => {
  res.json(messages);
});

// ---------------------------------------------------------------------------
// Dashboard HTML
// ---------------------------------------------------------------------------
const DASHBOARD_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PolyGuez Agent</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0a;color:#d4d4d8;font-family:'IBM Plex Mono',monospace;height:100vh;display:flex;flex-direction:column;overflow:hidden}
a{color:#22d3ee}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:#18181b}
::-webkit-scrollbar-thumb{background:#3f3f46;border-radius:3px}

.header{display:flex;align-items:center;justify-content:space-between;padding:12px 20px;border-bottom:1px solid #27272a;background:#0f0f0f;flex-shrink:0}
.logo{font-size:16px;font-weight:700;color:#22d3ee;letter-spacing:1px}
.logo span{color:#a1a1aa}
.status-badge{padding:4px 12px;border-radius:4px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px}
.status-idle{background:#27272a;color:#a1a1aa}
.status-running{background:rgba(59,130,246,0.15);color:#60a5fa;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}

.terminal-wrap{flex:1;display:flex;flex-direction:column;min-width:0;overflow:hidden}
.terminal{flex:1;overflow-y:auto;padding:16px 20px;font-size:12px;line-height:1.7}
.log-line{white-space:pre-wrap;word-break:break-all}
.log-line .ts{color:#52525b;margin-right:8px}
.role-system{color:#a78bfa}
.role-assistant{color:#d4d4d8}
.role-result{color:#4ade80}
.role-stderr{color:#f87171}
.role-raw{color:#71717a}
.role-user{color:#22d3ee}

.input-bar{display:flex;gap:8px;padding:12px 20px;border-top:1px solid #27272a;background:#0f0f0f;flex-shrink:0}
.input-bar textarea{flex:1;background:#18181b;border:1px solid #3f3f46;border-radius:4px;color:#d4d4d8;font-family:inherit;font-size:12px;padding:8px 12px;resize:none;outline:none;min-height:36px;max-height:80px}
.input-bar textarea:focus{border-color:#22d3ee}
.btn{padding:6px 14px;border:1px solid #3f3f46;border-radius:4px;background:#18181b;color:#d4d4d8;font-family:inherit;font-size:11px;cursor:pointer;font-weight:600;text-transform:uppercase;letter-spacing:.5px;transition:all .15s}
.btn:hover{background:#27272a;border-color:#52525b}
.btn-primary{border-color:#22d3ee;color:#22d3ee}
.btn-primary:hover{background:rgba(34,211,238,0.1)}
.input-bar .btn{align-self:flex-end}
</style>
</head>
<body>

<div class="header">
  <div class="logo">POLYGUEZ <span>AGENT</span></div>
  <div id="statusBadge" class="status-badge status-idle">IDLE</div>
</div>

<div class="terminal-wrap">
  <div class="terminal" id="terminal"></div>
  <div class="input-bar">
    <textarea id="inputBox" placeholder="Type an instruction for the agent..." rows="1"
      onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendInstruction()}"></textarea>
    <button class="btn btn-primary" onclick="sendInstruction()">SEND</button>
  </div>
</div>

<script>
const terminal = document.getElementById('terminal');
const statusBadge = document.getElementById('statusBadge');
const inputBox = document.getElementById('inputBox');

function setStatus(s) {
  statusBadge.textContent = s.toUpperCase();
  statusBadge.className = 'status-badge status-' + s;
}

function appendLog(msg) {
  const div = document.createElement('div');
  div.className = 'log-line role-' + (msg.role || 'raw');
  const ts = new Date(msg.ts).toLocaleTimeString('en-US',{hour12:false});
  div.innerHTML = '<span class="ts">'+ts+'</span>' + esc(msg.text);
  terminal.appendChild(div);
  terminal.scrollTop = terminal.scrollHeight;
}

function esc(s) {
  const d = document.createElement('span');
  d.textContent = s;
  return d.innerHTML;
}

async function sendInstruction() {
  const content = inputBox.value.trim();
  if (!content) return;
  inputBox.value = '';
  await fetch('/api/instructions', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({content})
  });
}

const es = new EventSource('/api/stream');
es.onmessage = (e) => {
  try {
    const data = JSON.parse(e.data);
    if (data.type === 'init') {
      setStatus(data.status);
      (data.messages || []).forEach(appendLog);
    } else if (data.type === 'message') {
      appendLog(data);
    } else if (data.type === 'statusUpdate') {
      setStatus(data.status);
    }
  } catch {}
};
es.onerror = () => { console.log('SSE reconnecting...'); };
</script>
</body>
</html>`;

app.get("/", (_req: Request, res: Response) => {
  res.setHeader("Content-Type", "text/html");
  res.send(DASHBOARD_HTML);
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
app.listen(PORT, () => {
  console.log(`✅ PolyGuez Agent running at http://localhost:${PORT}`);
});
