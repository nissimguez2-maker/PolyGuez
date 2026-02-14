from pathlib import Path
text = Path("webhook_server_fastapi.py").read_text(encoding="utf-8")
lines = text.splitlines()
start = 1000
end = 1080
for i in range(start-1, min(end, len(lines))):
    print(f"{i+1:04d}: {repr(lines[i])}")
