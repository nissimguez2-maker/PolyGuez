from pathlib import Path

text = Path("webhook_server_fastapi.py").read_text(encoding="utf-8")
lines = text.splitlines()

results = []

for i, line in enumerate(lines):
    stripped = line.lstrip()
    if stripped.startswith("try:"):
        indent = len(line) - len(stripped)
        # scan forward for an except/finally at same or lesser indent within next 200 lines
        matched = False
        for j in range(i+1, min(len(lines), i+200)):
            s = lines[j].lstrip()
            if s.startswith("except") or s.startswith("finally"):
                ind2 = len(lines[j]) - len(s)
                if ind2 <= indent:
                    matched = True
                    break
            # if a def or async def at same or less indent found before except, consider problematic
            if s.startswith("def ") or s.startswith("async def "):
                ind2 = len(lines[j]) - len(s)
                if ind2 <= indent:
                    # likely no except directly follows try
                    break
        results.append((i+1, indent, matched))

out = []
for ln, ind, matched in results:
    out.append(f"try at {ln} indent={ind} matched={matched}")

Path('tools/try_balance.txt').write_text('\\n'.join(out), encoding='utf-8')
print('Wrote tools/try_balance.txt')
