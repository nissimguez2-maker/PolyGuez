from pathlib import Path

text = Path("webhook_server_fastapi.py").read_text(encoding="utf-8")
lines = text.splitlines()

tries = []
for i, line in enumerate(lines):
    stripped = line.lstrip()
    if stripped.startswith("try:"):
        indent = len(line) - len(stripped)
        tries.append((i + 1, indent))

excepts = []
for i, line in enumerate(lines):
    stripped = line.lstrip()
    if stripped.startswith("except") or stripped.startswith("finally"):
        indent = len(line) - len(stripped)
        excepts.append((i + 1, indent))

print("Found try count:", len(tries))
print("Found except/finally count:", len(excepts))

unmatched = []
for lineno, indent in tries:
    matched = False
    for j in range(lineno, min(len(lines), lineno + 1000)):
        s = lines[j].lstrip()
        if s.startswith("except") or s.startswith("finally"):
            # consider this a match
            matched = True
            break
        # if we hit a dedent that ends the block without except, break
        cur_indent = len(lines[j]) - len(lines[j].lstrip())
        if cur_indent < indent and lines[j].strip() != "":
            # block ended
            break
    if not matched:
        unmatched.append((lineno, indent))

print("Unmatched try entries (line, indent):")
for u in unmatched:
    print(u)

if unmatched:
    # print surrounding context for first unmatched
    line_no = unmatched[0][0]
    start = max(0, line_no - 10)
    end = min(len(lines), line_no + 10)
    print("\\nContext around first unmatched try:")
    for i in range(start, end):
        print(f\"{i+1:04d}: {lines[i]}\")
