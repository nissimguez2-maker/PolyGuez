import tokenize, io
from pathlib import Path

text = Path("webhook_server_fastapi.py").read_text(encoding="utf-8")
tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))

stack = []
for tok in tokens:
    s = tok.string
    if s == "try":
        stack.append(tok.start[0])
    elif s == "except" or s == "finally":
        if stack:
            stack.pop()
        else:
            print("Unmatched except/finally at line", tok.start[0])

if stack:
    print("Unmatched try at lines:", stack[:10])
else:
    print("All try/except balanced (naive)")

