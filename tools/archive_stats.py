#!/usr/bin/env python3
import os
import shutil
import time
from glob import glob

def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    d = os.path.join("archive", f"stats_{ts}")
    print("Creating", d)
    os.makedirs(d, exist_ok=True)
    files = sorted(glob("paper_trades_legacy*.jsonl")) + ["paper_trades.jsonl","paper_trades_legacy.jsonl","position_state.json","pending_confirmations.json"]
    moved = []
    for f in files:
        if os.path.exists(f):
            dest = os.path.join(d, os.path.basename(f))
            try:
                shutil.move(f, dest)
                moved.append(f)
            except Exception as e:
                print("ERR moving", f, e)
    print("MOVED:", moved)

if __name__ == '__main__':
    main()

