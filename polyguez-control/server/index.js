#!/usr/bin/env node
/**
 * PolyGuez Agent Control Panel
 * Plain JavaScript — no TypeScript, no build step, no tsx needed.
 * Run with: node server/index.js
 */

const express = require("express");
const { spawn } = require("child_process");
const { EventEmitter } = require("events");
const path = require("path");
const fs = require("fs");

// ---------------------------------------------------------------------------
// Load .env from repo root if it exists
// ---------------------------------------------------------------------------
const envPath = path.join(__dirname, "..", "..", ".env");
if (fs.existsSync(envPath)) {
  const lines = fs.readFileSync(envPath, "utf8").split("\n");
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    const val = trimmed.slice(eq + 1).trim().replace(/^["']|["']$/g, "");
    if (!process.env[key]) process.env[key] = val;
  }
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const PORT = 3333;
const REPO = process.env.POLYGUEZ_REPO || path.join(process.env.HOME || "/root", "PolyGuez");

if (!process.env.ANTHROPIC_API_KEY) {
  console.warn("⚠  ANTHROPIC_API_KEY not set — agent will fail. Add it to ~/PolyGuez/.env");
} else {
  console.log("✅ ANTHROPIC_API_KEY loaded");
}

// ---------------------------------------------------------------------------
// State (in-memory)
// ---------------------------------------------------------------------------
const messages = [];
const queue = [];
const bus = new EventEmitter();
bus.setMaxListeners(100);

let agentStatus = "idle";
let childProc = null;

function addMessage(role, text) {
  const msg = { ts: Date.now(), role, text };
  messages.push(msg);
  if (messages.length > 500) messages.shift(); // cap at 500
  bus.emit("msg", msg);
}

// Welcome message shown on load
addMessage("system", [
  "PolyGuez Agent ready. Type any instruction and press Send.",
  "",
  "Examples:",
  "  → Show me the last 5 rows from signal_log in Supabase",
  "  → Increase min_edge from 0.03 to 0.05",
  "  → Add a Telegram alert when a trade fires",
  "  → Why is velocity_ok blocking all trades?",
  "  → What is the current win rate from trade_log?",
].join("\n"));

// ---------------------------------------------------------------------------
// Run one instruction through Claude Code CLI
// ---------------------------------------------------------------------------
function runInstruction(content) {
  return new Promise((resolve) => {
    agentStatus = "running";
    bus.emit("statusUpdate", agentStatus);
    addMessage("system", "▶ Agent working...");

    const prompt =
      `You are an AI coding agent working on the PolyGuez trading bot repo at ${REPO}.\n` +
      `The bot is an algorithmic trading bot for Polymarket BTC 5-minute binary markets.\n` +
      `Always work on the main branch. After any code change, run: PYTHONPATH=. python -m pytest tests/ -q\n` +
      `Fix any test failures before committing. Then commit and push to main.\n` +
      `If the instruction asks for data from Supabase, read the .env file for SUPABASE_URL and SUPABASE_SERVICE_KEY,\n` +
      `then query the database and print the results clearly.\n\n` +
      `USER INSTRUCTION: ${content}`;

    const child = spawn("claude", [
      "-p", prompt,
      "--output-format", "stream-json",
      "--dangerously-skip-permissions",
      "--allowedTools", "Read,Write,Edit,Bash,Glob,Grep",
    ], {
      cwd: REPO,
      env: { ...process.env },
      stdio: ["ignore", "pipe", "pipe"],
    });

    childProc = child;
    let buf = "";

    child.stdout.on("data", (chunk) => {
      buf += chunk.toString();
      const lines = buf.split("\n");
      buf = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const evt = JSON.parse(line);
          if (evt.type === "assistant" && evt.message && evt.message.content) {
            for (const block of evt.message.content) {
              if (block.type === "text" && block.text) {
                addMessage("assistant", block.text);
              } else if (block.type === "tool_use") {
                addMessage("system", `🔧 ${block.name}`);
              }
            }
          } else if (evt.type === "result") {
            const r = evt.result;
            addMessage("result", typeof r === "string" ? r : JSON.stringify(r));
          }
        } catch {
          if (line.trim()) addMessage("raw", line.trim());
        }
      }
    });

    child.stderr.on("data", (chunk) => {
      const text = chunk.toString().trim();
      if (text && !text.startsWith("npm warn")) addMessage("stderr", text);
    });

    child.on("close", (code) => {
      childProc = null;
      addMessage("system", code === 0 ? "✓ Done — agent idle" : `✗ Exited with code ${code}`);
      agentStatus = "idle";
      bus.emit("statusUpdate", agentStatus);
      resolve();
      // Process next queued instruction if any
      const next = queue.shift();
      if (next) {
        addMessage("system", `▶ Running queued instruction...`);
        runInstruction(next).catch((e) => addMessage("system", `Error: ${e.message}`));
      }
    });

    child.on("error", (err) => {
      childProc = null;
      addMessage("stderr", `Failed to spawn claude: ${err.message}`);
      addMessage("system", "Is the claude CLI installed? Run: npm install -g @anthropic-ai/claude-code");
      agentStatus = "idle";
      bus.emit("statusUpdate", agentStatus);
      resolve();
    });
  });
}

// ---------------------------------------------------------------------------
// Express server
// ---------------------------------------------------------------------------
const app = express();
app.use(express.json());

// SSE — live event stream
app.get("/api/stream", (req, res) => {
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.flushHeaders();

  const onMsg = (msg) => res.write(`data: ${JSON.stringify({ type: "message", ...msg })}\n\n`);
  const onStatus = (s) => res.write(`data: ${JSON.stringify({ type: "statusUpdate", status: s })}\n\n`);

  bus.on("msg", onMsg);
  bus.on("statusUpdate", onStatus);

  // Send full current state on connect
  res.write(`data: ${JSON.stringify({ type: "init", status: agentStatus, messages: messages.slice(-200) })}\n\n`);

  req.on("close", () => {
    bus.off("msg", onMsg);
    bus.off("statusUpdate", onStatus);
  });
});

// Send instruction
app.post("/api/instructions", (req, res) => {
  const content = (req.body && req.body.content || "").trim();
  if (!content) return res.status(400).json({ ok: false, error: "content required" });

  addMessage("user", content);

  if (agentStatus === "running") {
    queue.push(content);
    addMessage("system", "Queued — will run after current instruction finishes");
  } else {
    runInstruction(content).catch((e) => addMessage("system", `Error: ${e.message}`));
  }

  res.json({ ok: true, queued: agentStatus === "running" });
});

app.get("/api/messages", (_req, res) => res.json(messages));
app.get("/api/status", (_req, res) => res.json({ status: agentStatus, queue: queue.length }));

// Stop current agent
app.post("/api/stop", (_req, res) => {
  if (childProc) {
    childProc.kill("SIGTERM");
    addMessage("system", "⛔ Stopped by user");
  }
  res.json({ ok: true });
});

// ---------------------------------------------------------------------------
// Dashboard HTML
// ---------------------------------------------------------------------------
const HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PolyGuez Agent</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;overflow:hidden}
body{background:#0a0a0a;color:#d4d4d8;font-family:'IBM Plex Mono',monospace;display:flex;flex-direction:column}
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#333;border-radius:3px}

.header{flex-shrink:0;display:flex;align-items:center;justify-content:space-between;padding:10px 20px;border-bottom:1px solid #1f1f1f;background:#0d0d0d}
.logo{font-size:14px;font-weight:700;letter-spacing:2px;color:#22d3ee}
.logo em{color:#52525b;font-style:normal}
.badge{font-size:10px;font-weight:700;letter-spacing:1px;padding:3px 10px;border-radius:3px;text-transform:uppercase}
.badge.idle{background:#1a1a1a;color:#52525b;border:1px solid #262626}
.badge.running{background:rgba(59,130,246,.12);color:#60a5fa;border:1px solid rgba(59,130,246,.3);animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

.log{flex:1;overflow-y:auto;padding:14px 20px 8px;font-size:12px;line-height:1.75}
.line{white-space:pre-wrap;word-break:break-word}
.ts{color:#333;margin-right:6px;font-size:10px}
.system{color:#7c6af7}
.assistant{color:#d4d4d8}
.result{color:#4ade80}
.stderr{color:#f87171}
.raw{color:#444}
.user{color:#22d3ee;font-weight:700}

.bottom{flex-shrink:0;border-top:1px solid #1a1a1a;background:#0d0d0d;padding:10px 16px;display:flex;gap:8px;align-items:flex-end}
textarea{flex:1;background:#141414;border:1px solid #262626;border-radius:4px;color:#e4e4e7;font-family:inherit;font-size:12px;padding:8px 12px;resize:none;outline:none;line-height:1.5;min-height:38px;max-height:100px}
textarea:focus{border-color:#22d3ee}
button{background:#0d1f22;border:1px solid #22d3ee;color:#22d3ee;font-family:inherit;font-size:11px;font-weight:700;letter-spacing:1px;padding:8px 16px;border-radius:4px;cursor:pointer;white-space:nowrap;transition:background .15s}
button:hover{background:rgba(34,211,238,.12)}
button:disabled{opacity:.3;cursor:default}
.stop-btn{border-color:#f87171;color:#f87171;background:transparent}
.stop-btn:hover{background:rgba(248,113,113,.1)}
</style>
</head>
<body>
<div class="header">
  <div class="logo">POLYGUEZ <em>AGENT</em></div>
  <span id="badge" class="badge idle">IDLE</span>
</div>
<div class="log" id="log"></div>
<div class="bottom">
  <textarea id="box" placeholder="Type an instruction and press Enter..." rows="1"
    onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}"></textarea>
  <button id="sendBtn" onclick="send()">SEND</button>
  <button class="stop-btn" onclick="stop()">STOP</button>
</div>

<script>
const log = document.getElementById('log');
const box = document.getElementById('box');
const badge = document.getElementById('badge');
const sendBtn = document.getElementById('sendBtn');

function esc(s){ const d=document.createElement('span'); d.textContent=s; return d.innerHTML; }

function appendLine(msg){
  const d = document.createElement('div');
  d.className = 'line ' + (msg.role||'raw');
  const t = new Date(msg.ts).toLocaleTimeString('en-US',{hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});
  d.innerHTML = '<span class="ts">'+t+'</span>'+esc(msg.text);
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
}

function setStatus(s){
  badge.textContent = s.toUpperCase();
  badge.className = 'badge ' + s;
  sendBtn.disabled = (s === 'running');
}

async function send(){
  const content = box.value.trim();
  if (!content) return;
  box.value = '';
  await fetch('/api/instructions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content})});
}

async function stop(){
  await fetch('/api/stop',{method:'POST'});
}

// Auto-resize textarea
box.addEventListener('input',()=>{
  box.style.height='38px';
  box.style.height=Math.min(box.scrollHeight,100)+'px';
});

// SSE
const es = new EventSource('/api/stream');
es.onmessage = e => {
  try {
    const d = JSON.parse(e.data);
    if(d.type==='init'){ setStatus(d.status); (d.messages||[]).forEach(appendLine); }
    else if(d.type==='message'){ appendLine(d); }
    else if(d.type==='statusUpdate'){ setStatus(d.status); }
  } catch{}
};
es.onerror = () => setTimeout(()=>location.reload(), 3000);
</script>
</body>
</html>`;

app.get("/", (_req, res) => {
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.send(HTML);
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
app.listen(PORT, "0.0.0.0", () => {
  console.log(`\n✅ PolyGuez Agent running at:\n   http://localhost:${PORT}\n   http://127.0.0.1:${PORT}\n`);
});
