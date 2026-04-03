#!/usr/bin/env node
/**
 * PolyGuez Agent — Real Claude Code back-and-forth
 * 
 * Spawns: claude -p "<instruction>" --output-format stream-json --dangerously-skip-permissions
 * Claude Code reads the repo, edits files, runs pytest, commits, pushes.
 * Every token streams live to your browser via SSE.
 * 
 * Required env vars (Railway):
 *   ANTHROPIC_API_KEY
 *   GITHUB_TOKEN
 *   GITHUB_OWNER
 *   GITHUB_REPO
 *   SUPABASE_URL
 *   SUPABASE_SERVICE_KEY
 *   POLYGUEZ_REPO  (set by entrypoint.sh to /repo/PolyGuez)
 */

const express  = require("express");
const { spawn } = require("child_process");
const { EventEmitter } = require("events");
const path = require("path");
const fs   = require("fs");

// ── Config ───────────────────────────────────────────────────────────────────
const PORT = process.env.PORT || 3333;
const REPO = process.env.POLYGUEZ_REPO || path.join(process.env.HOME || "/root", "PolyGuez");

// ── State ────────────────────────────────────────────────────────────────────
const messages = [];
const queue    = [];
const bus      = new EventEmitter();
bus.setMaxListeners(100);

let agentStatus = "idle";
let currentProc = null;

function log(role, text) {
  const msg = { ts: Date.now(), role, text };
  messages.push(msg);
  if (messages.length > 2000) messages.shift();
  bus.emit("msg", msg);
}

// Startup checks
const hasKey  = !!process.env.ANTHROPIC_API_KEY;
const hasGit  = !!process.env.GITHUB_TOKEN;
const hasSupa = !!process.env.SUPABASE_URL;

log("system", [
  "PolyGuez Agent ready — real Claude Code back-and-forth.",
  "",
  `Repo: ${REPO}`,
  `Anthropic key: ${hasKey ? "✅" : "❌ MISSING — add ANTHROPIC_API_KEY in Railway"}`,
  `GitHub token:  ${hasGit ? "✅" : "❌ MISSING — add GITHUB_TOKEN in Railway"}`,
  `Supabase:      ${hasSupa ? "✅" : "⚠️  not configured"}`,
  "",
  "Type any instruction. Claude Code will read your code, make changes,",
  "run tests, commit, and push — streaming every step live.",
  "",
  "Examples:",
  "  → Show me the last 10 rows from signal_log",
  "  → Increase min_edge from 0.03 to 0.05 and run tests",
  "  → Add Telegram alert when a trade fires",
  "  → Why is velocity_ok blocking all trades?",
  "  → Summarize today's trading performance from Supabase",
].join("\n"));

// ── Agent runner ─────────────────────────────────────────────────────────────
function runInstruction(content) {
  return new Promise((resolve) => {
    agentStatus = "running";
    bus.emit("statusUpdate", agentStatus);
    log("system", "▶ Claude Code starting...");

    // Pull latest before every instruction so we're always on fresh code
    try {
      const pull = require("child_process").spawnSync(
        "git", ["pull", "origin", "main", "--rebase"],
        { cwd: REPO, timeout: 30000, encoding: "utf8" }
      );
      if (pull.stdout) log("system", `git: ${pull.stdout.trim().split("\n")[0]}`);
    } catch (e) { /* non-fatal */ }

    const systemContext = [
      `You are an expert AI coding agent for the PolyGuez trading bot at ${REPO}.`,
      `PolyGuez trades Polymarket BTC 5-minute binary markets using Chainlink oracle prices`,
      `and a logistic terminal-probability model.`,
      ``,
      `RULES:`,
      `- Always work on the main branch`,
      `- After any code change, run: cd ${REPO} && PYTHONPATH=. python -m pytest tests/ -q`,
      `- Fix any test failures before committing`,
      `- Commit with a clear message and push to main`,
      `- When querying Supabase, use SUPABASE_URL=${process.env.SUPABASE_URL || ""} and SUPABASE_SERVICE_KEY from env`,
      `- Be concise in explanations but thorough in changes`,
    ].join("\n");

    const fullPrompt = `${systemContext}\n\nUSER INSTRUCTION: ${content}`;

    const child = spawn("claude", [
      "-p", fullPrompt,
      "--output-format", "stream-json",
      "--dangerously-skip-permissions",
      "--allowedTools", "Read,Write,Edit,Bash,Glob,Grep",
      "--max-turns", "30",
    ], {
      cwd: REPO,
      env: { ...process.env },
      stdio: ["ignore", "pipe", "pipe"],
    });

    currentProc = child;
    let buf = "";

    child.stdout.on("data", (chunk) => {
      buf += chunk.toString();
      const lines = buf.split("\n");
      buf = lines.pop() || "";

      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const evt = JSON.parse(line);

          // Assistant text
          if (evt.type === "assistant" && evt.message?.content) {
            for (const block of evt.message.content) {
              if (block.type === "text" && block.text?.trim()) {
                log("assistant", block.text);
              } else if (block.type === "tool_use") {
                // Show tool calls inline — truncate long inputs
                const inp = JSON.stringify(block.input || {});
                log("system", `🔧 ${block.name}  ${inp.slice(0, 120)}${inp.length > 120 ? "…" : ""}`);
              }
            }
          }

          // Result summary
          if (evt.type === "result") {
            if (evt.subtype === "success") {
              log("result", "✓ Done");
            } else {
              log("stderr", `Finished: ${evt.subtype}`);
            }
          }

        } catch {
          // Plain text line (not JSON)
          if (line.trim() && !line.startsWith("npm warn")) {
            log("raw", line.trim());
          }
        }
      }
    });

    child.stderr.on("data", (chunk) => {
      const text = chunk.toString().trim();
      if (text && !text.includes("npm warn") && !text.includes("ExperimentalWarning")) {
        log("stderr", text.slice(0, 500));
      }
    });

    child.on("close", (code) => {
      currentProc = null;
      if (code !== 0 && code !== null) {
        log("stderr", `Process exited with code ${code}`);
      }
      agentStatus = "idle";
      bus.emit("statusUpdate", agentStatus);
      resolve();

      // Next queued instruction
      const next = queue.shift();
      if (next) {
        log("system", `▶ Running queued instruction...`);
        runInstruction(next).catch(e => log("stderr", e.message));
      }
    });

    child.on("error", (err) => {
      currentProc = null;
      if (err.code === "ENOENT") {
        log("stderr", "claude CLI not found. Is it installed? (npm install -g @anthropic-ai/claude-code)");
      } else {
        log("stderr", `Spawn error: ${err.message}`);
      }
      agentStatus = "idle";
      bus.emit("statusUpdate", agentStatus);
      resolve();
    });
  });
}

// ── Express ──────────────────────────────────────────────────────────────────
const app = express();
app.use(express.json());

app.get("/health", (_req, res) => res.json({
  ok: true,
  status: agentStatus,
  repo: fs.existsSync(REPO) ? "found" : "missing",
  claude: !!process.env.ANTHROPIC_API_KEY,
}));

// SSE
app.get("/api/stream", (req, res) => {
  res.setHeader("Content-Type",  "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection",    "keep-alive");
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.flushHeaders();

  const onMsg    = m => res.write(`data: ${JSON.stringify({ type: "message",      ...m })}\n\n`);
  const onStatus = s => res.write(`data: ${JSON.stringify({ type: "statusUpdate", status: s })}\n\n`);

  bus.on("msg",          onMsg);
  bus.on("statusUpdate", onStatus);

  res.write(`data: ${JSON.stringify({ type: "init", status: agentStatus, messages: messages.slice(-300) })}\n\n`);

  req.on("close", () => {
    bus.off("msg",          onMsg);
    bus.off("statusUpdate", onStatus);
  });
});

app.post("/api/instructions", (req, res) => {
  const content = (req.body?.content || "").trim();
  if (!content) return res.status(400).json({ ok: false, error: "content required" });

  log("user", content);

  if (agentStatus === "running") {
    queue.push(content);
    log("system", `Queued (${queue.length} waiting)`);
    return res.json({ ok: true, queued: true });
  }

  runInstruction(content).catch(e => log("stderr", e.message));
  res.json({ ok: true, queued: false });
});

app.post("/api/stop", (_req, res) => {
  if (currentProc) {
    currentProc.kill("SIGTERM");
    log("system", "⛔ Stopped by operator");
  }
  queue.length = 0;
  agentStatus = "idle";
  bus.emit("statusUpdate", "idle");
  res.json({ ok: true });
});

app.get("/api/messages", (_req, res) => res.json(messages));
app.get("/api/status",   (_req, res) => res.json({ status: agentStatus, queue: queue.length }));

// ── Dashboard ─────────────────────────────────────────────────────────────────
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
::-webkit-scrollbar{width:5px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:#2a2a2a;border-radius:3px}

.header{flex-shrink:0;display:flex;align-items:center;justify-content:space-between;padding:10px 20px;border-bottom:1px solid #1c1c1c;background:#0d0d0d}
.logo{font-size:13px;font-weight:700;letter-spacing:2px;color:#22d3ee}
.logo em{color:#3f3f46;font-style:normal;font-weight:400}
.right{display:flex;align-items:center;gap:10px}
.badge{font-size:10px;font-weight:700;letter-spacing:1px;padding:3px 10px;border-radius:3px;text-transform:uppercase}
.badge.idle{background:#141414;color:#3f3f46;border:1px solid #222}
.badge.running{background:rgba(34,211,238,.08);color:#22d3ee;border:1px solid rgba(34,211,238,.2);animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.stop{background:transparent;border:1px solid #2a2a2a;color:#3f3f46;font-family:inherit;font-size:10px;font-weight:700;letter-spacing:1px;padding:3px 10px;border-radius:3px;cursor:pointer;text-transform:uppercase;transition:all .15s}
.stop:hover{border-color:#f87171;color:#f87171}

.log{flex:1;overflow-y:auto;padding:14px 20px 6px;font-size:12px;line-height:1.85}
.line{white-space:pre-wrap;word-break:break-word;padding:1px 0}
.ts{color:#262626;margin-right:8px;font-size:10px;user-select:none}
.system{color:#6d5fd5}
.assistant{color:#e4e4e7}
.result{color:#4ade80;font-weight:700}
.stderr{color:#f87171}
.raw{color:#3f3f46}
.user{color:#22d3ee;font-weight:700}

.bottom{flex-shrink:0;border-top:1px solid #1a1a1a;background:#0d0d0d;padding:10px 16px;display:flex;gap:8px;align-items:flex-end}
textarea{flex:1;background:#111;border:1px solid #222;border-radius:4px;color:#e4e4e7;font-family:inherit;font-size:12px;padding:8px 12px;resize:none;outline:none;line-height:1.6;min-height:38px;max-height:120px;transition:border-color .15s}
textarea:focus{border-color:#22d3ee}
textarea::placeholder{color:#2a2a2a}
.send{background:#0d2226;border:1px solid #22d3ee;color:#22d3ee;font-family:inherit;font-size:11px;font-weight:700;letter-spacing:1px;padding:9px 18px;border-radius:4px;cursor:pointer;white-space:nowrap;transition:background .15s}
.send:hover{background:rgba(34,211,238,.15)}
.send:disabled{opacity:.2;cursor:default}
</style>
</head>
<body>
<div class="header">
  <div class="logo">POLYGUEZ <em>AGENT</em></div>
  <div class="right">
    <span id="badge" class="badge idle">IDLE</span>
    <button class="stop" onclick="stopAgent()">STOP</button>
  </div>
</div>
<div class="log" id="log"></div>
<div class="bottom">
  <textarea id="box" placeholder="Give the agent an instruction..." rows="1"
    onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}"></textarea>
  <button class="send" id="sendBtn" onclick="send()">SEND</button>
</div>
<script>
const log=document.getElementById('log'),box=document.getElementById('box'),badge=document.getElementById('badge'),sendBtn=document.getElementById('sendBtn');
function esc(s){const d=document.createElement('span');d.textContent=s;return d.innerHTML}
function appendLine(m){
  const d=document.createElement('div');
  d.className='line '+(m.role||'raw');
  const t=new Date(m.ts).toLocaleTimeString('en-US',{hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});
  d.innerHTML='<span class="ts">'+t+'</span>'+esc(m.text);
  log.appendChild(d);
  log.scrollTop=log.scrollHeight;
}
function setStatus(s){
  badge.textContent=s.toUpperCase();
  badge.className='badge '+s;
  sendBtn.disabled=(s==='running');
}
async function send(){
  const c=box.value.trim();
  if(!c)return;
  box.value='';
  box.style.height='38px';
  await fetch('/api/instructions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:c})});
}
async function stopAgent(){
  await fetch('/api/stop',{method:'POST'});
}
box.addEventListener('input',()=>{box.style.height='38px';box.style.height=Math.min(box.scrollHeight,120)+'px'});
const es=new EventSource('/api/stream');
es.onmessage=e=>{
  try{
    const d=JSON.parse(e.data);
    if(d.type==='init'){setStatus(d.status);(d.messages||[]).forEach(appendLine);}
    else if(d.type==='message'){appendLine(d);}
    else if(d.type==='statusUpdate'){setStatus(d.status);}
  }catch{}
};
es.onerror=()=>setTimeout(()=>location.reload(),3000);
</script>
</body>
</html>`;

app.get("/", (_req, res) => {
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.send(HTML);
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`\n✅ PolyGuez Agent on port ${PORT}`);
  console.log(`   Repo:    ${REPO}`);
  console.log(`   Claude:  ${process.env.ANTHROPIC_API_KEY ? "✅" : "❌ MISSING"}`);
  console.log(`   GitHub:  ${process.env.GITHUB_TOKEN ? "✅" : "❌ MISSING"}\n`);
});
