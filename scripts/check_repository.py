"""Small source hygiene check; never prints suspected credential values."""
from pathlib import Path
import re
root=Path(__file__).resolve().parents[1]
failures=[]
for folder in ['backend','frontend','tests','scripts']:
    for path in (root/folder).rglob('*'):
        if path.suffix not in {'.py','.js','.cjs','.html','.json'}:continue
        text=path.read_text(errors='replace')
        if re.search(r'sk-[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{25,}',text):
            failures.append(str(path.relative_to(root)))
if (root/'node_modules').exists():failures.append('tracked/deployed node_modules directory')
if failures:raise SystemExit('Review possible credentials or generated files: '+', '.join(failures))
print('Source hygiene check passed.')
