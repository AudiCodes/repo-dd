"""Time every dd.py section on a set of inputs, so a speed change is a measured change.

    python3 bench/bench.py <input> [<input> ...] [--label before]

Appends one JSON line per run to bench/results.jsonl: input, label, and the elapsed seconds at
which each section (X, QUICK, DEV TREE, FOMO, SITE, PROGRAMS, DONE) printed.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DD = os.path.join(os.path.dirname(HERE), "scripts", "dd.py")


def run(arg):
    t0 = time.time()
    p = subprocess.Popen([sys.executable, "-u", DD, arg], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    marks = {}
    for line in p.stdout:
        m = re.match(r"=== (.+?)  \[", line) or re.match(r"(DONE) \[", line)
        if m:
            marks[m.group(1)] = round(time.time() - t0, 1)
    p.wait()
    return marks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    for arg in a.inputs:
        marks = run(arg)
        row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "label": a.label, "input": arg, "marks": marks}
        with open(os.path.join(HERE, "results.jsonl"), "a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"{arg[:44]:44s} " + "  ".join(f"{k} {v}s" for k, v in marks.items()))


if __name__ == "__main__":
    main()
