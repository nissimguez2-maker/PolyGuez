import glob,re

files = glob.glob('paper_trades*.jsonl') + glob.glob('paper_trades_legacy*.jsonl') + glob.glob('archive/**/*.jsonl', recursive=True)
ids = set()
for f in files:
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            for line in fh:
                line=line.strip()
                if not line:
                    continue
                m = re.search(r'"trade_id"\s*:\s*"([^"]+)"', line)
                if m:
                    ids.add(m.group(1))
    except Exception:
        pass
print(len(ids))
