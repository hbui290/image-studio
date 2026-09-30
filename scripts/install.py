#!/usr/bin/env python3
"""Copy every Image Studio skill into a host skills directory.

Nothing is overwritten without --replace. With --replace, each existing skill folder of the
same name is removed, including any files you added inside it; unrelated folders are kept.
New copies are staged and old folders are moved aside before anything is deleted, so a failure
leaves either the previous install or the complete new one, never a mix.
"""
import argparse
import os
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / 'plugins/image-studio/skills'


def skill_names(source_root=SKILLS):
    return tuple(sorted(p.parent.name for p in Path(source_root).glob('*/SKILL.md')))


NAMES = skill_names()


def install(source_root, destination, replace=False):
    source_root = Path(source_root).resolve()
    destination = Path(destination).expanduser()
    resolved = destination.resolve()
    repo = source_root.parents[2] if len(source_root.parents) > 2 else source_root
    # samefile also catches case-insensitive spellings and symlinked paths of the repository.
    if any(p.exists() and os.path.samefile(p, repo) for p in (resolved, *resolved.parents)):
        raise ValueError('Destination is inside this repository; choose a separate skills directory.')
    names = skill_names(source_root)
    if not names:
        raise FileNotFoundError(f'No skills found in {source_root}')
    existing = [destination/name for name in names if (destination/name).exists() or (destination/name).is_symlink()]
    if existing and not replace:
        raise FileExistsError('Existing skills: '+', '.join(p.name for p in existing)+'. Use another directory or explicitly pass --replace.')
    destination.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.image-studio-install-', dir=destination))
    new, old = staging/'new', staging/'old'
    new.mkdir()
    old.mkdir()
    moved, placed = [], []
    try:
        for name in names:
            shutil.copytree(source_root/name, new/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.private'))
        for name in names:  # renames only: fast and reversible
            dst = destination/name
            if dst.exists() or dst.is_symlink():
                dst.rename(old/name)
                moved.append(name)
        for name in names:
            (new/name).rename(destination/name)
            placed.append(name)
    except OSError:
        for name in placed:
            (destination/name).rename(new/name)
        for name in moved:
            (old/name).rename(destination/name)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--to', required=True, type=Path, help='E.g. ~/.codex/skills or ~/.claude/skills')
    parser.add_argument('--replace', action='store_true', help='Replace existing skill folders of the same names')
    args = parser.parse_args()
    try:
        dest = install(SKILLS, args.to, args.replace)
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc)+'\n')
    print('Installed '+', '.join(NAMES)+' into '+str(dest))


if __name__ == '__main__':
    main()
