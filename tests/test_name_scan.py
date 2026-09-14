from pathlib import Path


def test_runtime_source_has_no_legacy_ung_tax_identity():
    roots = [Path('main.py'), Path('static')]
    for root in roots:
        paths = [root] if root.is_file() else [p for p in root.rglob('*') if p.is_file() and p.suffix in {'.html','.js','.css'}]
        for path in paths:
            text = path.read_text(encoding='utf-8')
            assert 'UNG-TAX' not in text, f'legacy identity remains in {path}'
