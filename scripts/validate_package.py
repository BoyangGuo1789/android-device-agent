#!/usr/bin/env python3
"""Check tracked release files, local Markdown links and documentation inventory."""
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    'README.md', 'AGENTS.md', 'LICENSE', '.gitignore', 'config.example.json', 'Open-Mirror.command',
    '.github/workflows/tests.yml', 'scripts/__init__.py', 'scripts/config.py',
    'scripts/tablet_control.py', 'scripts/bootstrap.sh', 'scripts/validate_package.py',
    'tests/test_tablet_control.py', 'tests/test_config.py', 'tests/test_capture.py',
    'examples/smoke_test.py', 'examples/START_HERE_PROMPT.md',
    'docs/SETUP.md', 'docs/USAGE.md', 'docs/RECIPES.md', 'docs/WORKSPACE.md',
    'docs/GOAL.md', 'docs/PROVENANCE.md', 'docs/VERIFICATION.md', 'docs/INDEX.md',
}


def main():
    errors = []
    result = subprocess.run(['git', '-C', str(ROOT), 'ls-files'], capture_output=True, text=True)
    files = set(result.stdout.splitlines()) if result.returncode == 0 else ALLOWED
    for filename in sorted(files - ALLOWED):
        errors.append('Unexpected tracked file: ' + filename)
    for filename in sorted(ALLOWED):
        path = ROOT / filename
        if not path.is_file():
            errors.append('Missing release file: ' + filename)
            continue
        text = path.read_text(encoding='utf-8')
        if re.search(r'/' + r'Users/[^/\s]+/', text):
            errors.append('Developer home path in: ' + filename)
        if re.search(r'\b(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}', text):
            errors.append('Credential-like value in: ' + filename)
        if path.suffix == '.md':
            for target in re.findall(r'\]\(([^)]+)\)', text):
                target = target.strip('<>').split('#', 1)[0]
                if not target or re.match(r'[A-Za-z][A-Za-z0-9+.-]*:', target):
                    continue
                resolved = (path.parent / unquote(target)).resolve()
                if not resolved.is_relative_to(ROOT) or not resolved.exists():
                    errors.append(f'Broken / external local link in {filename}: {target}')
    index = (ROOT / 'docs/INDEX.md').read_text(encoding='utf-8')
    for doc in (ROOT / 'docs').glob('*.md'):
        if doc.name != 'INDEX.md' and '(' + doc.name + ')' not in index:
            errors.append('Document missing from index: ' + doc.name)
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f'Package checks passed: {len(ALLOWED)} allowlisted source/document files; local links and index OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
