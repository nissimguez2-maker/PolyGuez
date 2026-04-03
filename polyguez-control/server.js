#!/usr/bin/env node
/**
 * PolyGuez Agent — Railway deployment
 * 
 * Architecture:
 * - Claude API (claude-opus-4-5) with tool use — the "brain"
 * - GitHub API (Octokit) — reads/writes files, commits, pushes
 * - Express + SSE — streams every token to the browser in real time
 * - No claude CLI needed, no local repo needed, runs 100% on Railway
 * 
 * Required env vars (set in Railway):
 *   ANTHROPIC_API_KEY
 *   GITHUB_TOKEN          (Personal Access Token with repo scope)
 *   GITHUB_OWNER          (e.g. nissimguez2-maker)
 *   GITHUB_REPO           (e.g. PolyGuez)
 *   SUPABASE_URL
 *   SUPABASE_SERVICE_KEY
 */

const express = require("express");
const Anthropic = require("@anthropic-ai/sdk");
const { Octokit } = require("@octokit/rest");
const { EventEmitter } = require("events");

// ── Config ──────────────────────────────────────────────────────────────────
const PORT     = process.env.PORT || 3333;
const OWNER    = process.env.GITHUB_OWNER || "nissimguez2-maker";
const REPO     = process.env.GITHUB_REPO  || "PolyGuez";
const BRANCH   = "main";

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const octokit   = new Octokit({ auth: process.env.GITHUB_TOKEN });

// ── In-memory state ─────────────────────────────────────────────────────────
const messages = [];   // log history shown in dashboard
const queue    = [];   // pending instructions
const bus      = new EventEmitter();
bus.setMaxListeners(100);

let agentStatus = "idle";

function log(role, text) {
  const msg = { ts: Date.now(), role, text };
  messages.push(msg);
  if (messages.length > 1000) messages.shift();
  bus.emit("msg", msg);
}

log("system", [
  "PolyGuez Agent ready.",
  "",
  "I have full access to your GitHub repo. I can:",
  "  • Read any file in the codebase",
  "  • Edit files and commit + push changes",
  "  • Query your Supabase tables",
  "  • Explain what the bot is doing and why",
  "",
  "Just type what you want. Examples:",
  "  → Show me the last 10 rows from signal_log",
  "  → Increase min_edge from 0.03 to 0.05",
  "  → Add Telegram alerts when a trade fires",
  "  → Why is velocity_ok blocking all my trades?",
  "  → Summarize the current bot config",
].join("\n"));

// ── GitHub tools ─────────────────────────────────────────────────────────────
const TOOLS = [
  {
    name: "read_file",
    description: "Read a file from the PolyGuez GitHub repo.",
    input_schema: {
      type: "object",
      properties: {
        path: { type: "string", description: "File path relative to repo root, e.g. agents/utils/objects.py" }
      },
      required: ["path"]
    }
  },
  {
    name: "list_files",
    description: "List files in a directory of the PolyGuez GitHub repo.",
    input_schema: {
      type: "object",
      properties: {
        path: { type: "string", description: "Directory path, e.g. agents/strategies or empty string for root" }
      },
      required: ["path"]
    }
  },
  {
    name: "write_file",
    description: "Create or update a file in the PolyGuez GitHub repo and commit it to main branch.",
    input_schema: {
      type: "object",
      properties: {
        path:    { type: "string", description: "File path relative to repo root" },
        content: { type: "string", description: "Full new file content" },
        message: { type: "string", description: "Commit message" }
      },
      required: ["path", "content", "message"]
    }
  },
  {
    name: "search_code",
    description: "Search for a string or pattern across all Python files in the repo.",
    input_schema: {
      type: "object",
      properties: {
        query: { type: "string", description: "Text to search for" }
      },
      required: ["query"]
    }
  },
  {
    name: "query_supabase",
    description: "Run a SELECT query against the PolyGuez Supabase database.",
    input_schema: {
      type: "object",
      properties: {
        sql: { type: "string", description: "SQL SELECT query to run, e.g. SELECT * FROM signal_log ORDER BY ts DESC LIMIT 10" }
      },
      required: ["sql"]
    }
  },
  {
    name: "get_recent_logs",
    description: "Get recent Railway deployment logs summary. Returns the last 50 log lines from Supabase polybot_reports if available.",
    input_schema: {
      type: "object",
      properties: {},
      required: []
    }
  }
];

// ── Tool executors ────────────────────────────────────────────────────────────
async function executeTool(name, input) {
  try {
    if (name === "read_file") {
      const { data } = await octokit.repos.getContent({
        owner: OWNER, repo: REPO, path: input.path, ref: BRANCH
      });
      if (data.type !== "file") return `${input.path} is not a file`;
      const content = Buffer.from(data.content, "base64").toString("utf8");
      return content.slice(0, 8000); // cap at 8k chars
    }

    if (name === "list_files") {
      const { data } = await octokit.repos.getContent({
        owner: OWNER, repo: REPO, path: input.path || "", ref: BRANCH
      });
      if (Array.isArray(data)) {
        return data.map(f => `${f.type === "dir" ? "📁" : "📄"} ${f.path}`).join("\n");
      }
      return "Not a directory";
    }

    if (name === "write_file") {
      // Get current SHA if file exists
      let sha;
      try {
        const { data } = await octokit.repos.getContent({
          owner: OWNER, repo: REPO, path: input.path, ref: BRANCH
        });
        sha = data.sha;
      } catch { /* file doesn't exist yet, sha stays undefined */ }

      await octokit.repos.createOrUpdateFileContents({
        owner: OWNER, repo: REPO,
        path: input.path,
        message: input.message,
        content: Buffer.from(input.content).toString("base64"),
        branch: BRANCH,
        ...(sha ? { sha } : {}),
        committer: { name: "PolyGuez Agent", email: "agent@polyguez.bot" },
        author:    { name: "PolyGuez Agent", email: "agent@polyguez.bot" },
      });
      return `✅ Committed: ${input.path} — "${input.message}"`;
    }

    if (name === "search_code") {
      // Use GitHub search API
      const { data } = await octokit.search.code({
        q: `${input.query} repo:${OWNER}/${REPO}`,
        per_page: 10
      });
      if (!data.items.length) return `No results for: ${input.query}`;
      return data.items.map(i => `${i.path}:${i.name}`).join("\n");
    }

    if (name === "query_supabase") {
      const url  = process.env.SUPABASE_URL;
      const key  = process.env.SUPABASE_SERVICE_KEY;
      if (!url || !key) return "SUPABASE_URL or SUPABASE_SERVICE_KEY not set in environment";

      // Use PostgREST for simple SELECT queries
      // Parse table name and limit from SQL for PostgREST
      const sql = input.sql.trim();
      const tableMatch = sql.match(/FROM\s+(\w+)/i);
      if (!tableMatch) return "Could not parse table name from SQL";
      const table = tableMatch[1];

      const limitMatch = sql.match(/LIMIT\s+(\d+)/i);
      const limit = limitMatch ? parseInt(limitMatch[1]) : 20;

      const orderMatch = sql.match(/ORDER BY\s+(\w+)\s*(DESC|ASC)?/i);
      const orderCol = orderMatch ? orderMatch[1] : "id";
      const orderDir = orderMatch && orderMatch[2] === "ASC" ? "" : ".desc";

      const qUrl = `${url}/rest/v1/${table}?order=${orderCol}${orderDir}&limit=${limit}`;
      const resp = await fetch(qUrl, {
        headers: {
          "apikey": key,
          "Authorization": `Bearer ${key}`,
          "Accept": "application/json"
        }
      });
      const rows = await resp.json();
      if (!Array.isArray(rows)) return JSON.stringify(rows).slice(0, 2000);
      if (!rows.length) return `${table} is empty`;
      return JSON.stringify(rows, null, 2).slice(0, 4000);
    }

    if (name === "get_recent_logs") {
      const url = process.env.SUPABASE_URL;
      const key = process.env.SUPABASE_SERVICE_KEY;
      if (!url || !key) return "Supabase not configured";
      const resp = await fetch(`${url}/rest/v1/polybot_reports?order=saved_at.desc&limit=1`, {
        headers: { "apikey": key, "Authorization": `Bearer ${key}` }
      });
      const rows = await resp.json();
      if (!rows.length) return "No reports found";
      return rows[0].html ? rows[0].html.replace(/<[^>]+>/g, "").slice(0, 3000) : "Empty report";
    }

    return `Unknown tool: ${name}`;
  } catch (err) {
    return `Error executing ${name}: ${err.message}`;
  }
}

// ── Agent loop ────────────────────────────────────────────────────────────────
async function runInstruction(content) {
  agentStatus = "running";
  bus.emit("statusUpdate", agentStatus);

  const systemPrompt = `You are an expert AI coding agent for the PolyGuez trading bot.
PolyGuez is an algorithmic trading bot for Polymarket's 5-minute BTC binary markets.
It uses Chainlink oracle prices, Binance WebSocket feeds, and a logistic terminal-probability model to find mispricings.
The repo is ${OWNER}/${REPO} on GitHub, main branch.

You have tools to:
- read_file: read any file in the repo
- list_files: explore directory structure  
- write_file: edit files and commit them directly to main (Railway auto-deploys)
- search_code: search across all files
- query_supabase: query signal_log, trade_log, trade_archive, rolling_stats tables
- get_recent_logs: get recent bot activity

RULES:
- Always read a file before editing it
- When editing Python, preserve exact indentation
- After writing a file, confirm what changed and why
- When showing data, format it clearly
- If the user asks about performance, query signal_log and trade_log
- Be concise but thorough`;

  const apiMessages = [{ role: "user", content }];
  let iteration = 0;
  const MAX_ITER = 20;

  while (iteration < MAX_ITER) {
    iteration++;

    let response;
    try {
      response = await anthropic.messages.create({
        model: "claude-opus-4-5-20251101",
        max_tokens: 4096,
        system: systemPrompt,
        tools: TOOLS,
        messages: apiMessages,
      });
    } catch (err) {
      log("stderr", `API error: ${err.message}`);
      break;
    }

    // Stream text blocks as they come
    for (const block of response.content) {
      if (block.type === "text" && block.text.trim()) {
        log("assistant", block.text);
      }
    }

    // Done — no more tool calls
    if (response.stop_reason === "end_turn") break;

    // Handle tool calls
    if (response.stop_reason === "tool_use") {
      apiMessages.push({ role: "assistant", content: response.content });

      const toolResults = [];
      for (const block of response.content) {
        if (block.type !== "tool_use") continue;

        log("system", `🔧 ${block.name}(${JSON.stringify(block.input).slice(0, 100)})`);
        const result = await executeTool(block.name, block.input);

        // Show short preview of result
        const preview = result.toString().slice(0, 200);
        if (preview.trim()) log("system", `   → ${preview}${result.length > 200 ? "..." : ""}`);

        toolResults.push({
          type: "tool_result",
          tool_use_id: block.id,
          content: result.toString(),
        });
      }

      apiMessages.push({ role: "user", content: toolResults });
    }
  }

  log("system", "✓ Done");
  agentStatus = "idle";
  bus.emit("statusUpdate", agentStatus);

  // Process next queued instruction
  const next = queue.shift();
  if (next) {
    log("system", "▶ Running next queued instruction...");
    runInstruction(next).catch(e => log("stderr", e.message));
  }
}

// ── Express app ──────────────────────────────────────────────────────────────
const app = express();
app.use(express.json());

// Health check for Railway
app.get("/health", (_req, res) => res.json({ ok: true, status: agentStatus }));

// SSE stream
app.get("/api/stream", (req, res) => {
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.flushHeaders();

  const onMsg    = m  => res.write(`data: ${JSON.stringify({ type: "message",      ...m })}\n\n`);
  const onStatus = s  => res.write(`data: ${JSON.stringify({ type: "statusUpdate", status: s })}\n\n`);

  bus.on("msg",          onMsg);
  bus.on("statusUpdate", onStatus);

  // Send full history on connect
  res.write(`data: ${JSON.stringify({ type: "init", status: agentStatus, messages: messages.slice(-300) })}\n\n`);

  req.on("close", () => {
    bus.off("msg",          onMsg);
    bus.off("statusUpdate", onStatus);
  });
});

// Send instruction
app.post("/api/instructions", (req, res) => {
  const content = (req.body && req.body.content || "").trim();
  if (!content) return res.status(400).json({ ok: false, error: "content required" });

  log("user", content);

  if (agentStatus === "running") {
    queue.push(content);
    log("system", "Queued — will run after current instruction finishes");
    return res.json({ ok: true, queued: true });
  }

  runInstruction(content).catch(e => log("stderr", e.message));
  res.json({ ok: true, queued: false });
});

app.get("/api/status",   (_req, res) => res.json({ status: agentStatus, queue: queue.length }));
app.get("/api/messages", (_req, res) => res.json(messages));

app.post("/api/stop", (_req, res) => {
  agentStatus = "idle";
  queue.length = 0;
  bus.emit("statusUpdate", "idle");
  log("system", "⛔ Stopped by user");
  res.json({ ok: true });
});

// ── Dashboard HTML ───────────────────────────────────────────────────────────
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
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.stop-btn{background:transparent;border:1px solid #2a2a2a;color:#52525b;font-family:inherit;font-size:10px;font-weight:700;letter-spacing:1px;padding:3px 10px;border-radius:3px;cursor:pointer;text-transform:uppercase;transition:all .15s}
.stop-btn:hover{border-color:#f87171;color:#f87171}
.log{flex:1;overflow-y:auto;padding:14px 20px 6px;font-size:12px;line-height:1.8}
.line{white-space:pre-wrap;word-break:break-word;padding:1px 0}
.ts{color:#262626;margin-right:8px;font-size:10px;user-select:none}
.system{color:#6d5fd5}
.assistant{color:#d4d4d8}
.result{color:#4ade80}
.stderr{color:#f87171}
.raw{color:#3f3f46}
.user{color:#22d3ee;font-weight:700}
.bottom{flex-shrink:0;border-top:1px solid #1a1a1a;background:#0d0d0d;padding:10px 16px;display:flex;gap:8px;align-items:flex-end}
textarea{flex:1;background:#111;border:1px solid #222;border-radius:4px;color:#e4e4e7;font-family:inherit;font-size:12px;padding:8px 12px;resize:none;outline:none;line-height:1.6;min-height:38px;max-height:120px;transition:border-color .15s}
textarea:focus{border-color:#22d3ee}
textarea::placeholder{color:#333}
.send{background:#0d2226;border:1px solid #22d3ee;color:#22d3ee;font-family:inherit;font-size:11px;font-weight:700;letter-spacing:1px;padding:9px 18px;border-radius:4px;cursor:pointer;white-space:nowrap;transition:background .15s}
.send:hover{background:rgba(34,211,238,.15)}
.send:disabled{opacity:.25;cursor:default}
</style>
</head>
<body>
<div class="header">
  <div class="logo">POLYGUEZ <em>AGENT</em></div>
  <div class="right">
    <span id="badge" class="badge idle">IDLE</span>
    <button class="stop-btn" onclick="stop()">STOP</button>
  </div>
</div>
<div class="log" id="log"></div>
<div class="bottom">
  <textarea id="box" placeholder="Ask anything or give an instruction..." rows="1"
    onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}"></textarea>
  <button class="send" id="sendBtn" onclick="send()">SEND</button>
</div>
<script>
const log=document.getElementById('log'),box=document.getElementById('box'),badge=document.getElementById('badge'),sendBtn=document.getElementById('sendBtn');
function esc(s){const d=document.createElement('span');d.textContent=s;return d.innerHTML}
function appendLine(m){
  const d=document.createElement('div');d.className='line '+(m.role||'raw');
  const t=new Date(m.ts).toLocaleTimeString('en-US',{hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});
  d.innerHTML='<span class="ts">'+t+'</span>'+esc(m.text);
  log.appendChild(d);log.scrollTop=log.scrollHeight;
}
function setStatus(s){badge.textContent=s.toUpperCase();badge.className='badge '+s;sendBtn.disabled=(s==='running')}
async function send(){const c=box.value.trim();if(!c)return;box.value='';box.style.height='38px';await fetch('/api/instructions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:c})})}
async function stop(){await fetch('/api/stop',{method:'POST'})}
box.addEventListener('input',()=>{box.style.height='38px';box.style.height=Math.min(box.scrollHeight,120)+'px'});
const es=new EventSource('/api/stream');
es.onmessage=e=>{try{const d=JSON.parse(e.data);if(d.type==='init'){setStatus(d.status);(d.messages||[]).forEach(appendLine)}else if(d.type==='message'){appendLine(d)}else if(d.type==='statusUpdate'){setStatus(d.status)}}catch{}};
es.onerror=()=>setTimeout(()=>location.reload(),3000);
</script>
</body>
</html>`;

app.get("/", (_req, res) => {
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.send(HTML);
});

// ── Start ─────────────────────────────────────────────────────────────────────
app.listen(PORT, "0.0.0.0", () => {
  console.log(`\n✅ PolyGuez Agent running on port ${PORT}`);
  console.log(`   Anthropic: ${process.env.ANTHROPIC_API_KEY ? "✅" : "❌ MISSING"}`);
  console.log(`   GitHub:    ${process.env.GITHUB_TOKEN      ? "✅" : "❌ MISSING"}`);
  console.log(`   Supabase:  ${process.env.SUPABASE_URL      ? "✅" : "❌ MISSING"}\n`);
});
