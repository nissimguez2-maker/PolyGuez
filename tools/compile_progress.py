from pathlib import Path
p = Path("webhook_server_fastapi.py")
text = p.read_text(encoding="utf-8")
lines = text.splitlines()
for i in range(1, len(lines)+1):
    chunk = "\n".join(lines[:i])
    try:
        compile(chunk, str(p), "exec")
    except Exception as e:
        print("Failed at line", i, "error:", repr(e))
        # print context
        start = max(0, i-10)
        for j in range(start, min(len(lines), i+5)):
            print(f"{j+1:04d}: {lines[j]!r}")
        break
else:
    print("All good")
