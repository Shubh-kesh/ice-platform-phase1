#!/usr/bin/env python3
"""
CI quality-gate delta checker (Phase 4, P4.1).

Runs a lint/type command and compares its findings against a committed
baseline file. The gate FAILS only when a NEW finding appears (a key not
present in the baseline). Baseline entries that disappear are reported as
progress and never fail the gate, so the repository's pre-existing debt
(Ruff: 2, Mypy: 10, oxlint: 1) is explicitly accounted for without masking
new regressions.

Baseline format: one stable key per line; blank lines and lines starting
with '#' are ignored. Keys are relative to the tool's working directory,
so the workflow runs each tool from the same cwd used to generate the
baseline (see .github/workflows/ci.yml).

Usage:
    python scripts/ci_quality.py \
        --kind ruff --baseline .ci/baseline_ruff.txt \
        --cmd "ruff check app tests --output-format=concise" --cwd backend

Exit codes:
    0  no new findings (baseline met)
    1  one or more NEW findings detected
    2  the tool itself failed to run (missing command / crashed with no findings)
"""
import argparse
import re
import subprocess
import sys

# <path>:<line>:<CODE>
_RUFF = re.compile(r"^([^:]+):(\d+):\d+:\s*([A-Z]\d{3})\b")
# <path>:<line>: error: <message> [<code>]
_MYPY = re.compile(r"^(\S+):(\d+): error: (.*)$")
_MYPY_CODE = re.compile(r"\[([a-z_\-]+)\]$")
# <path>:<line>:<col>: warning|error <rule>:
_OXLINT = re.compile(r"^(\S+):(\d+):\d+:\s*(?:warning|error)\s+([^\s:]+):")


def parse(kind: str, output: str) -> set[str]:
    keys: set[str] = set()
    for line in output.splitlines():
        if kind == "ruff":
            m = _RUFF.match(line)
            if m:
                keys.add(f"{m.group(1)}:{m.group(2)}:{m.group(3)}")
        elif kind == "mypy":
            m = _MYPY.match(line)
            if m:
                message = re.sub(r"\s{2,}", " ", m.group(3)).strip()
                code = ""
                cm = _MYPY_CODE.search(message)
                if cm:
                    code = cm.group(1)
                    message = message[: cm.start()].rstrip()
                keys.add(f"{m.group(1)}:{m.group(2)}:{message}[{code}]")
        elif kind == "oxlint":
            m = _OXLINT.match(line)
            if m:
                keys.add(f"{m.group(1)}:{m.group(2)}:{m.group(3)}")
    return keys


def load_baseline(path: str) -> set[str]:
    items: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            items.add(line)
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=["ruff", "mypy", "oxlint"])
    parser.add_argument("--baseline", required=True, help="path to the baseline file")
    parser.add_argument("--cmd", required=True, help="tool command to run")
    parser.add_argument("--cwd", default=".", help="working directory for the command")
    args = parser.parse_args()

    try:
        proc = subprocess.run(
            args.cmd, shell=True, cwd=args.cwd, capture_output=True, text=True
        )
    except OSError as exc:
        print(f"FAIL: could not execute tool: {exc}", file=sys.stderr)
        return 2

    combined = (proc.stdout or "") + (proc.stderr or "")
    if combined:
        sys.stdout.write(combined)
        if not combined.endswith("\n"):
            sys.stdout.write("\n")

    current = parse(args.kind, combined)
    baseline = load_baseline(args.baseline)

    if proc.returncode < 0 or (proc.returncode != 0 and not current):
        # Tool crashed or failed without producing any findings — fail loudly
        # so a missing/broken tool can never masquerade as a clean gate.
        print(
            f"FAIL: tool exited with code {proc.returncode} and produced no "
            f"findings — cannot validate the baseline.",
            file=sys.stderr,
        )
        return 2

    new = current - baseline
    missing = baseline - current

    print(
        f"[ci_quality] kind={args.kind} current={len(current)} "
        f"baseline={len(baseline)} new={len(new)} resolved={len(missing)}"
    )
    for key in sorted(new):
        print(f"[ci_quality] NEW finding: {key}")
    for key in sorted(missing):
        print(f"[ci_quality] RESOLVED (was baseline): {key}")

    if new:
        print(f"[ci_quality] FAIL: {len(new)} new finding(s) introduced.")
        return 1
    print("[ci_quality] PASS: no new findings (baseline met).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
