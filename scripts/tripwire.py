#!/usr/bin/env python3
"""Tripwire: notice changes to the code that handles the API key.

Recent GitHub attacks pushed a secret stealer into workflows with stolen tokens, then reverted the commit
and deleted the run. With force-pushes blocked on main, those commits stay in history. This script lists
every commit since the last run that touched .github/, scripts/ or sources.json. If there are any, the
workflow fails at the end (after publishing the brief), so GitHub emails a failure notice.
Expected after your own edits: check that the commits listed are yours, then ignore the email.
"""
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "data", "state.json")
WATCH = [".github", "scripts", "sources.json"]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main():
    head = git("rev-parse", "HEAD")
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    last = state.get("last_checked")
    report = []
    if last:
        try:
            log = git("log", "--format=%h  %an  %ad  %s", "--date=iso", f"{last}..{head}", "--", *WATCH)
        except subprocess.CalledProcessError:
            log = f"previous checkpoint {last[:10]} is no longer in the history: was main force-pushed or rewritten?"
        if log:
            report.append("Code that can call Claude changed since the last run:\n" + log)
    state["last_checked"] = head
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(state, open(STATE, "w"), indent=1)
    out = os.environ.get("RUNNER_TEMP", "/tmp")
    with open(os.path.join(out, "tripwire.txt"), "w") as f:
        f.write("\n".join(report) + ("\n" if report else ""))
    print("\n".join(report) or "tripwire: no changes to watched files")


if __name__ == "__main__":
    sys.exit(main())
