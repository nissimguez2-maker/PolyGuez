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
  console.warn("⚠ ANTHROPIC_API_KEY is not set. Agent tasks will fail until it is exported.");
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
interface TaskDef {
  id: number;
  title: string;
  prompt: string;
  status: "waiting" | "running" | "done" | "failed";
  startedAt?: number;
  finishedAt?: number;
}

const TASKS: TaskDef[] = [
  {
    id: 1,
    title: "Create missing Supabase tables",
    prompt: `You are working in the PolyGuez repo at ${REPO}.
Create any missing Supabase migration files for these tables if they don't already exist:
- signal_log (id bigint pk, ts timestamptz default now(), market_id text, btc_price float8, chainlink_price float8, strike_delta float8, terminal_probability float8, terminal_edge float8, yes_price float8, no_price float8, spread float8, phase text, direction text, all_conditions_met boolean)
- trade_log (id bigint pk, ts timestamptz default now(), market_id text, side text, entry_price float8, size_usdc float8, outcome text, pnl float8, exit_price float8, hold_seconds int)
- trade_archive (id bigint pk, ts timestamptz default now(), data jsonb)
Check if these tables are already defined in any migration or SQL file. If they exist, skip. If not, create a new migration file in the supabase/migrations directory. Use standard Supabase migration naming convention.`,
    status: "waiting",
  },
  {
    id: 2,
    title: "Re-enable velocity_ok + oracle_gap_ok",
    prompt: `You are working in the PolyGuez repo at ${REPO}.
Find the SignalState class (likely in agents/utils/objects.py or agents/strategies/).
In the all_conditions_met property, make sure velocity_ok and oracle_gap_ok are included in the conditions list — they may have been commented out or removed.
Also find where elapsed is computed from the entry window and fix it so elapsed = max(0, 300 - remaining) where remaining is the seconds left in the 5-minute window. Look for any inverted elapsed calculation.
Run the tests after to make sure nothing breaks.`,
    status: "waiting",
  },
  {
    id: 3,
    title: "Fix LLM prompt → VERDICT parser",
    prompt: `You are working in the PolyGuez repo at ${REPO}.
Open agents/strategies/llm_adapters.py and agents/strategies/polyguez_prompts.py (or wherever the LLM prompt template is).
Make sure the prompt template instructs the LLM to respond in the exact format:
  VERDICT: GO | REASON: <reason>
  or
  VERDICT: NO-GO | REASON: <reason>
Check that the parse_llm_response() regex matches this format correctly.
If the prompt doesn't include clear format instructions, add them.
Run tests after.`,
    status: "waiting",
  },
  {
    id: 4,
    title: "Add maker limit order support",
    prompt: `You are working in the PolyGuez repo at ${REPO}.
Add a config field use_maker_orders: bool = False to PolyGuezConfig in agents/utils/objects.py.
In the execute_entry function in agents/strategies/polyguez_strategy.py, when use_maker_orders is True and mode is "live", place a GTC limit order instead of a FOK market order.
The limit order should be placed at the current best bid (for YES) or best ask (for NO) from the CLOB.
For dry-run and paper mode, just log that it would have been a maker order.
Make sure existing tests still pass. Add the field with a safe default.`,
    status: "waiting",
  },
  {
    id: 5,
    title: "Run pytest + verification summary",
    prompt: `You are working in the PolyGuez repo at ${REPO}.
Run: python -m pytest tests/ -v
Then print a summary of what was fixed across all 5 tasks:
1. Supabase tables created
2. velocity_ok + oracle_gap_ok re-enabled, elapsed formula fixed
3. LLM prompt format aligned with VERDICT parser
4. Maker limit order support added
5. All tests passing
Format the summary clearly.`,
    status: "waiting",
  },
];

const messages: Array<{ ts: number; role: string; text: string; taskId?: number }> = [];
const instructions: Array<{ ts: number; content: string; consumed: boolean }> = [];
const bus = new EventEmitter();
bus.setMaxListeners(50);

let agentStatus: "idle" | "running" | "paused" | "stopped" = "idle";
let currentTaskIdx = 0;
let childProc: ChildProcess | null = null;
let pauseResolve: (() => void) | null = null;

function emit(role: string, text: string, taskId?: number) {
  const msg = { ts: Date.now(), role, text, taskId };
  messages.push(msg);
  bus.emit("msg", msg);
}

// ---------------------------------------------------------------------------
// Agent runner
// ---------------------------------------------------------------------------
function getPendingInstructions(): string {
  const pending = instructions.filter((i) => !i.consumed);
  pending.forEach((i) => (i.consumed = true));
  if (!pending.length) return "";
  return (
    "\n\nADDITIONAL USER INSTRUCTIONS:\n" +
    pending.map((i) => `- ${i.content}`).join("\n")
  );
}

function runTask(task: TaskDef): Promise<void> {
  return new Promise((resolve, reject) => {
    task.status = "running";
    task.startedAt = Date.now();
    emit("system", `▶ Starting task ${task.id}: ${task.title}`, task.id);
    bus.emit("taskUpdate", task);

    const fullPrompt = task.prompt + getPendingInstructions();

    const args = [
      "-p",
      fullPrompt,
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
                emit("assistant", block.text, task.id);
              }
            }
          } else if (evt.type === "content_block_delta" && evt.delta?.text) {
            emit("assistant", evt.delta.text, task.id);
          } else if (evt.type === "result" && evt.result) {
            emit("result", typeof evt.result === "string" ? evt.result : JSON.stringify(evt.result), task.id);
          }
        } catch {
          if (line.trim()) emit("raw", line.trim(), task.id);
        }
      }
    });

    child.stderr?.on("data", (chunk: Buffer) => {
      const text = chunk.toString().trim();
      if (text) emit("stderr", text, task.id);
    });

    child.on("close", (code) => {
      childProc = null;
      task.finishedAt = Date.now();
      if (code === 0) {
        task.status = "done";
        emit("system", `✓ Task ${task.id} completed`, task.id);
      } else {
        task.status = "failed";
        emit("system", `✗ Task ${task.id} failed (exit ${code})`, task.id);
      }
      bus.emit("taskUpdate", task);
      resolve();
    });

    child.on("error", (err) => {
      childProc = null;
      task.status = "failed";
      task.finishedAt = Date.now();
      emit("system", `✗ Task ${task.id} error: ${err.message}`, task.id);
      bus.emit("taskUpdate", task);
      resolve();
    });
  });
}

async function runAllTasks() {
  agentStatus = "running";
  bus.emit("statusUpdate", agentStatus);
  emit("system", "🚀 Agent started — running 5 tasks sequentially");

  for (currentTaskIdx = 0; currentTaskIdx < TASKS.length; currentTaskIdx++) {
    if (agentStatus === "stopped") break;

    if (agentStatus === "paused") {
      emit("system", "⏸ Agent paused — waiting for resume");
      await new Promise<void>((res) => {
        pauseResolve = res;
      });
      emit("system", "▶ Agent resumed");
    }

    if (agentStatus === "stopped") break;

    await runTask(TASKS[currentTaskIdx]);
  }

  agentStatus = "idle";
  bus.emit("statusUpdate", agentStatus);
  emit("system", "🏁 All tasks finished");
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
  const onTask = (task: any) => {
    res.write(`data: ${JSON.stringify({ type: "taskUpdate", task })}\n\n`);
  };
  const onStatus = (status: string) => {
    res.write(`data: ${JSON.stringify({ type: "statusUpdate", status })}\n\n`);
  };

  bus.on("msg", onMsg);
  bus.on("taskUpdate", onTask);
  bus.on("statusUpdate", onStatus);

  // Send initial state
  res.write(
    `data: ${JSON.stringify({ type: "init", status: agentStatus, tasks: TASKS, messages: messages.slice(-200) })}\n\n`
  );

  _req.on("close", () => {
    bus.off("msg", onMsg);
    bus.off("taskUpdate", onTask);
    bus.off("statusUpdate", onStatus);
  });
});

app.post("/api/agent/start", (_req: Request, res: Response) => {
  if (agentStatus === "running" || agentStatus === "paused") {
    return res.json({ ok: false, error: "Agent already running" });
  }
  TASKS.forEach((t) => {
    t.status = "waiting";
    delete t.startedAt;
    delete t.finishedAt;
  });
  messages.length = 0;
  runAllTasks().catch((e) => emit("system", `Agent crash: ${e.message}`));
  res.json({ ok: true });
});

app.post("/api/agent/stop", (_req: Request, res: Response) => {
  agentStatus = "stopped";
  if (childProc) childProc.kill("SIGTERM");
  if (pauseResolve) {
    pauseResolve();
    pauseResolve = null;
  }
  bus.emit("statusUpdate", agentStatus);
  emit("system", "🛑 Agent stopped by user");
  res.json({ ok: true });
});

app.post("/api/agent/pause", (_req: Request, res: Response) => {
  if (agentStatus !== "running") return res.json({ ok: false, error: "Not running" });
  agentStatus = "paused";
  bus.emit("statusUpdate", agentStatus);
  res.json({ ok: true });
});

app.post("/api/agent/resume", (_req: Request, res: Response) => {
  if (agentStatus !== "paused") return res.json({ ok: false, error: "Not paused" });
  agentStatus = "running";
  bus.emit("statusUpdate", agentStatus);
  if (pauseResolve) {
    pauseResolve();
    pauseResolve = null;
  }
  res.json({ ok: true });
});

app.post("/api/instructions", (req: Request, res: Response) => {
  const content = req.body?.content;
  if (!content) return res.status(400).json({ ok: false, error: "content required" });
  instructions.push({ ts: Date.now(), content, consumed: false });
  emit("user", content);
  res.json({ ok: true });
});

app.get("/api/messages", (_req: Request, res: Response) => {
  res.json(messages);
});

app.get("/api/tasks", (_req: Request, res: Response) => {
  res.json(TASKS);
});

// ---------------------------------------------------------------------------
// Dashboard HTML
// ---------------------------------------------------------------------------
const DASHBOARD_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PolyGuez Control Panel</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0a;color:#d4d4d8;font-family:'IBM Plex Mono',monospace;height:100vh;display:flex;flex-direction:column;overflow:hidden}
a{color:#22d3ee}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:#18181b}
::-webkit-scrollbar-thumb{background:#3f3f46;border-radius:3px}

/* Header */
.header{display:flex;align-items:center;justify-content:space-between;padding:12px 20px;border-bottom:1px solid #27272a;background:#0f0f0f;flex-shrink:0}
.logo{font-size:16px;font-weight:700;color:#22d3ee;letter-spacing:1px}
.logo span{color:#a1a1aa}
.status-group{display:flex;align-items:center;gap:12px}
.status-badge{padding:4px 12px;border-radius:4px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px}
.status-idle{background:#27272a;color:#a1a1aa}
.status-running{background:rgba(59,130,246,0.15);color:#60a5fa;animation:pulse 2s infinite}
.status-paused{background:rgba(251,191,36,0.15);color:#fbbf24}
.status-stopped{background:rgba(239,68,68,0.15);color:#f87171}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.controls{display:flex;gap:8px}
.btn{padding:6px 14px;border:1px solid #3f3f46;border-radius:4px;background:#18181b;color:#d4d4d8;font-family:inherit;font-size:11px;cursor:pointer;font-weight:600;text-transform:uppercase;letter-spacing:.5px;transition:all .15s}
.btn:hover{background:#27272a;border-color:#52525b}
.btn-primary{border-color:#22d3ee;color:#22d3ee}
.btn-primary:hover{background:rgba(34,211,238,0.1)}
.btn-danger{border-color:#f87171;color:#f87171}
.btn-danger:hover{background:rgba(248,113,113,0.1)}

/* Main layout */
.main{display:flex;flex:1;overflow:hidden}

/* Sidebar */
.sidebar{width:280px;border-right:1px solid #27272a;padding:16px;overflow-y:auto;flex-shrink:0;background:#0f0f0f}
.sidebar-title{font-size:11px;color:#71717a;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px}
.task-card{padding:10px 12px;border:1px solid #27272a;border-radius:6px;margin-bottom:8px;transition:border-color .2s}
.task-card.active{border-color:#3b82f6}
.task-card.done{border-color:#22c55e}
.task-card.failed{border-color:#f59e0b}
.task-id{font-size:10px;color:#71717a}
.task-title{font-size:12px;margin-top:2px;color:#e4e4e7}
.task-badge{display:inline-block;padding:2px 8px;border-radius:3px;font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;margin-top:6px}
.badge-waiting{background:#27272a;color:#71717a}
.badge-running{background:rgba(59,130,246,0.15);color:#60a5fa;animation:pulse 2s infinite}
.badge-done{background:rgba(34,197,94,0.15);color:#4ade80}
.badge-failed{background:rgba(245,158,11,0.15);color:#fbbf24}

/* Terminal */
.terminal-wrap{flex:1;display:flex;flex-direction:column;min-width:0}
.terminal{flex:1;overflow-y:auto;padding:16px 20px;font-size:12px;line-height:1.7}
.log-line{white-space:pre-wrap;word-break:break-all}
.log-line .ts{color:#52525b;margin-right:8px}
.role-system{color:#a78bfa}
.role-assistant{color:#d4d4d8}
.role-result{color:#4ade80}
.role-stderr{color:#f87171}
.role-raw{color:#71717a}
.role-user{color:#22d3ee}

/* Input */
.input-bar{display:flex;gap:8px;padding:12px 20px;border-top:1px solid #27272a;background:#0f0f0f;flex-shrink:0}
.input-bar textarea{flex:1;background:#18181b;border:1px solid #3f3f46;border-radius:4px;color:#d4d4d8;font-family:inherit;font-size:12px;padding:8px 12px;resize:none;outline:none;min-height:36px;max-height:80px}
.input-bar textarea:focus{border-color:#22d3ee}
.input-bar .btn{align-self:flex-end}
</style>
</head>
<body>

<div class="header">
  <div class="logo">POLYGUEZ <span>CONTROL PANEL</span></div>
  <div class="status-group">
    <div id="statusBadge" class="status-badge status-idle">IDLE</div>
    <div class="controls">
      <button class="btn btn-primary" onclick="api('agent/start')">START AGENT</button>
      <button class="btn" onclick="api('agent/pause')">PAUSE</button>
      <button class="btn" onclick="api('agent/resume')">RESUME</button>
      <button class="btn btn-danger" onclick="api('agent/stop')">STOP</button>
    </div>
  </div>
</div>

<div class="main">
  <div class="sidebar">
    <div class="sidebar-title">Tasks</div>
    <div id="taskList"></div>
  </div>
  <div class="terminal-wrap">
    <div class="terminal" id="terminal"></div>
    <div class="input-bar">
      <textarea id="inputBox" placeholder="Type an instruction for the agent..." rows="1"
        onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendInstruction()}"></textarea>
      <button class="btn btn-primary" onclick="sendInstruction()">SEND</button>
    </div>
  </div>
</div>

<script>
const terminal = document.getElementById('terminal');
const taskList = document.getElementById('taskList');
const statusBadge = document.getElementById('statusBadge');
const inputBox = document.getElementById('inputBox');
let tasks = [];

function renderTasks() {
  taskList.innerHTML = tasks.map(t => {
    const cls = t.status === 'running' ? 'active' : t.status === 'done' ? 'done' : t.status === 'failed' ? 'failed' : '';
    return '<div class="task-card '+cls+'">' +
      '<div class="task-id">T'+t.id+'</div>' +
      '<div class="task-title">'+esc(t.title)+'</div>' +
      '<span class="task-badge badge-'+t.status+'">'+t.status+'</span>' +
    '</div>';
  }).join('');
}

function setStatus(s) {
  statusBadge.textContent = s.toUpperCase();
  statusBadge.className = 'status-badge status-' + s;
}

function appendLog(msg) {
  const div = document.createElement('div');
  div.className = 'log-line role-' + (msg.role || 'raw');
  const ts = new Date(msg.ts).toLocaleTimeString('en-US',{hour12:false});
  const taskTag = msg.taskId ? ' [T'+msg.taskId+']' : '';
  div.innerHTML = '<span class="ts">'+ts+taskTag+'</span>' + esc(msg.text);
  terminal.appendChild(div);
  terminal.scrollTop = terminal.scrollHeight;
}

function esc(s) {
  const d = document.createElement('span');
  d.textContent = s;
  return d.innerHTML;
}

async function api(endpoint) {
  await fetch('/api/'+endpoint, {method:'POST', headers:{'Content-Type':'application/json'}});
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

// SSE
const es = new EventSource('/api/stream');
es.onmessage = (e) => {
  try {
    const data = JSON.parse(e.data);
    if (data.type === 'init') {
      tasks = data.tasks;
      renderTasks();
      setStatus(data.status);
      (data.messages || []).forEach(appendLog);
    } else if (data.type === 'message') {
      appendLog(data);
    } else if (data.type === 'taskUpdate') {
      const t = tasks.find(x => x.id === data.task.id);
      if (t) Object.assign(t, data.task);
      renderTasks();
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
  console.log(`✅ PolyGuez Control Panel running at http://localhost:${PORT}`);
});
