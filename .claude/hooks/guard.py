"""Claude Code hooks for this repo.

pre:  ask before any edit to LICENSE or NOTICE (attribution files).
post: after a .py edit, compile it with Python 3.9 so 3.9-only syntax errors show at once.
"""
import json
import os
import shutil
import subprocess
import sys

PROTECTED = {'LICENSE', 'NOTICE'}


def main():
    data = json.load(sys.stdin)
    path = (data.get('tool_input') or {}).get('file_path') or ''
    root = os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()
    if not path:
        return 0
    path = os.path.abspath(path)

    if sys.argv[1] == 'pre':
        if os.path.dirname(path) == os.path.abspath(root) and os.path.basename(path) in PROTECTED:
            print(json.dumps({'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'ask',
                'permissionDecisionReason': os.path.basename(path) + ' holds the codejunkie99/image-loop attribution. Confirm this edit keeps it.',
            }}))
        return 0

    if path.endswith('.py') and os.path.isfile(path):
        py39 = '/usr/bin/python3' if os.path.exists('/usr/bin/python3') else shutil.which('python3.9')
        if not py39:  # ponytail: no 3.9 on this machine, CI's 3.9 job still catches it
            return 0
        check = 'import sys; compile(open(sys.argv[1], "rb").read(), sys.argv[1], "exec")'
        result = subprocess.run([py39, '-c', check, path], capture_output=True, text=True)
        if result.returncode:
            sys.stderr.write('Python 3.9 cannot compile ' + path + ':\n' + result.stderr[-1500:])
            return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
