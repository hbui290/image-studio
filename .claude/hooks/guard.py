"""Claude Code hooks for this repo.

pre:  ask before any edit to LICENSE or NOTICE (attribution files), in any letter case.
post: after a .py edit, compile it with Python 3.9 so 3.9 syntax errors show at once.
      This catches syntax only; `X | Y` annotations fail at runtime, which the CI job on 3.9 catches.
"""
import json
import os
import shutil
import subprocess
import sys

PROTECTED = {'license', 'notice'}
CHECK = 'import sys; compile(open(sys.argv[1], "rb").read(), sys.argv[1], "exec")'


def python39():
    for candidate in (shutil.which('python3.9'), '/usr/bin/python3'):
        if candidate and os.path.exists(candidate):
            version = subprocess.run([candidate, '-c', 'import sys; print(sys.version_info[:2] == (3, 9))'],
                                     capture_output=True, text=True)
            if version.stdout.strip() == 'True':
                return candidate
    return None


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    try:
        data = json.load(sys.stdin)
        path = (data.get('tool_input') or {}).get('file_path') or ''
    except (ValueError, AttributeError):
        return 0  # not a tool call this hook understands
    if not isinstance(path, str) or not path:
        return 0
    root = os.path.abspath(os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd())
    path = os.path.abspath(os.path.join(root, path))

    if mode == 'pre':
        # lower() on both: macOS and Windows paths are case-insensitive, so Image-Studio/LICENSE is the same file
        if os.path.dirname(path).lower() == root.lower() and os.path.basename(path).lower() in PROTECTED:
            print(json.dumps({'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'ask',
                'permissionDecisionReason': os.path.basename(path) + ' holds the codejunkie99/image-loop attribution. Confirm this edit keeps it.',
            }}))
        return 0

    if mode == 'post' and path.endswith('.py') and os.path.isfile(path):
        py39 = python39()
        if not py39:  # ponytail: no 3.9 on this machine, CI's 3.9 job still catches it
            print('guard: no Python 3.9 found; skipped the 3.9 compile check', file=sys.stderr)
            return 0
        result = subprocess.run([py39, '-c', CHECK, path], capture_output=True, text=True)
        if result.returncode:
            sys.stderr.write('Python 3.9 cannot compile ' + path + ':\n' + result.stderr[-1500:])
            return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
