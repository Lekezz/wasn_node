"""
ioc_guard.py - PreToolUse backstop for CubeMX regeneration discipline.

CLAUDE.md rule this enforces:

    Commit before and after every CubeMX regeneration so git diff exposes
    what the generator changed. It has silently reverted settings twice
    (DMA mode Normal, DMA width Byte).

That rule only works if the tree is clean when the .ioc changes. If there
is unrelated uncommitted work in the tree, the regeneration diff gets mixed
in with it and a silently reverted DMA setting hides in the noise.

So: if a tool is about to touch mic_test.ioc while tracked files have
uncommitted modifications, deny it and say what to commit first. A clean
tree is allowed straight through.

Untracked files (?? in git status) do NOT block. Things like docs/ and
scratch output are untracked by design and would otherwise wedge this
permanently. Only modifications to files git already tracks matter, since
those are what pollute a regeneration diff.

Reads the PreToolUse JSON payload on stdin, writes a permission decision on
stdout. Fails OPEN: any unexpected error allows the edit, because a broken
guard must not block real work.
"""

import json
import subprocess
import sys

REPO = r"C:\Users\lekej\Summer2026\mic_test"


def allow():
    """Silence means allow. Nothing to print."""
    sys.exit(0)


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        allow()

    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not path.lower().endswith(".ioc"):
        allow()

    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO, capture_output=True, text=True, timeout=15,
        )
    except Exception:
        allow()                      # no git, no opinion

    if out.returncode != 0:
        allow()

    # Keep only tracked changes. Untracked (??) is deliberately ignored.
    dirty = [ln for ln in out.stdout.splitlines()
             if ln.strip() and not ln.startswith("??")]
    if not dirty:
        allow()                      # clean tree, regeneration diff will be readable

    listing = "\n".join(f"    {ln}" for ln in dirty[:12])
    if len(dirty) > 12:
        listing += f"\n    ... and {len(dirty) - 12} more"

    deny(
        "Blocked by the CubeMX regeneration guard in .claude/hooks/"
        "ioc_guard.py.\n\n"
        f"About to modify {path}, but these tracked files have uncommitted "
        f"changes:\n{listing}\n\n"
        "CLAUDE.md requires a commit before and after every CubeMX "
        "regeneration, so that git diff shows exactly what the generator "
        "changed. It has silently reverted DMA mode to Normal and DMA width "
        "to Byte twice. With unrelated edits in the tree, that revert hides "
        "in the noise.\n\n"
        "Commit or stash the above, then retry. To override deliberately, "
        "edit the hook out of .claude/settings.json."
    )


if __name__ == "__main__":
    main()
