from pathlib import Path
import re

p = Path("webhook_server_fastapi.py")
text = p.read_text(encoding="utf-8")
lines = text.splitlines()

try_count = 0
for i, line in enumerate(lines, start=1):
    stripped = line.strip()
    # skip comments and docstrings naive
    if stripped.startswith("#"):
        continue
    # detect try: at line end
    if re.match(r"^try\s*:\s*$", stripped):
        try_count += 1
    # detect except or finally at same indentation (naive)
    if re.match(r"^(except\b|finally\b)", stripped):
        if try_count > 0:
            try_count -= 1
        else:
            print(f"Unmatched except/finally at line {i}")
            break
    # report first location where try_count gets large without closing
    if try_count > 0 and i % 50 == 0:
        pass

if try_count != 0:
    print("Unclosed try blocks:", try_count)
else:
    print("All tries matched (naive check)")

