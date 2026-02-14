import tokenize, io
from pathlib import Path

text = Path("webhook_server_fastapi.py").read_text(encoding="utf-8")
tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
out = []
for tok in tokens[:200]:
    out.append(repr(tok))
out.append("...TOTAL TOKENS: " + str(len(tokens)))
# dump a window around probable area
start = max(0, len(tokens)//2 - 200)
for tok in tokens[start:start+400]:
    out.append(repr(tok))
Path('tools/tokens_dump.txt').write_text('\\n'.join(out), encoding='utf-8')
print('dump written to tools/tokens_dump.txt')
