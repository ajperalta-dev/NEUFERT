"""Read-only source audit; all extracted content stays in data/private."""
import json
from pathlib import Path
import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]

def inspect(path):
    with fitz.open(path) as doc:
        pages = []
        for page in doc:
            text = page.get_text()
            pages.append({"page": page.number + 1, "characters": len(text.strip()),
                          "replacement_characters": text.count('\ufffd'),
                          "images": len(page.get_images()), "sample": text[:300]})
        report = {"file": str(path), "pages": len(doc), "metadata": doc.metadata,
                  "outline": doc.get_toc(), "pages_without_text": [p['page'] for p in pages if p['characters'] < 50],
                  "page_analysis": pages}
        out = ROOT / 'data/private'
        out.mkdir(parents=True, exist_ok=True)
        (out / 'source-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        (out / 'front-matter.txt').write_text('\n\n'.join(f'PDF {i+1}\n{doc[i].get_text()}' for i in range(min(15,len(doc)))), encoding='utf-8')
        doc[min(30,len(doc)-1)].get_pixmap(dpi=100).save(out / 'audit-page.png')
        print(json.dumps({k:v for k,v in report.items() if k!='page_analysis'}, ensure_ascii=True))

if __name__ == '__main__':
    import sys
    inspect(Path(sys.argv[1]))
