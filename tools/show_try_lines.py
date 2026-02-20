from pathlib import Path
lines = Path("webhook_server_fastapi.py").read_text(encoding="utf-8").splitlines()
out = []
for i,l in enumerate(lines, start=1):
    if "try:" in l:
        out.append(f"{i}: {l.strip()}")
Path("tools/try_lines.txt").write_text("\\n".join(out), encoding="utf-8")
print("Wrote try lines to tools/try_lines.txt")
