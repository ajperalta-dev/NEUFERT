import re
from pathlib import Path
s = Path('data/private/reference.html').read_text(encoding='utf-8')
css = '\n'.join(re.findall(r'<style[^>]*>(.*?)</style>', s, re.S))
Path('data/private/reference.css').write_text(css, encoding='utf-8')
rules = re.findall(r'[^{}]*\{[^{}]*\}', css)
for rule in rules:
    if any(x in rule for x in ['padding:0 28px 80px','padding:12px 28px','grid-template-columns:','--framer-font-family:"Funnel','framer-link-hover-text-color:']):
        print(rule[:1800])
