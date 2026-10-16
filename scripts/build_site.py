"""Build the dependency-free GitHub Pages site. Run from any directory."""
import json
import shutil
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'dist'


def project_card(project):
    def value(key):
        return escape(project[key], quote=True)
    if project.get('image'):
        visual = f'<img src="{value("image")}" alt="Emberkeep 原生运行截图：像素地牢与游戏状态界面" width="1280" height="800" loading="lazy">'
    else:
        visual = '<div class="lab-art"><div class="label">BRIDGE LAB / 设计目标 · 非运行结果</div><div class="comment">// JavaScript → Python</div><div>const value = <strong>lab.add</strong>(20, 22);</div><div>print(value);</div><br><div class="comment">// 六个场景，观察真实桥接行为</div><div>Functions · Promises · Objects</div></div>'
    tags = ''.join(f'<li>{escape(tag)}</li>' for tag in project['features'])
    links = ''.join(f'<a href="{value(key)}">{label} ↗</a>' for key, label in [('guide', '本地运行指南'), ('releases', '发行页面')] if project.get(key))
    planned = ' planned' if project['status'] == '规划中' else ''
    return f'''<article class="project" id="{value('id')}"><div class="visual">{visual}</div><div><span class="status{planned}">{value('status')}</span><span class="kind">{value('kind')}</span><h3>{value('title')}</h3><p>{value('description')}</p><ul class="tags">{tags}</ul><div class="links"><a href="{value('source')}">{escape(project.get("source_label", "查看源码"))} ↗</a>{links}</div></div></article>'''


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            if attrs['id'] in self.ids:
                raise ValueError(f'Duplicate id: {attrs["id"]}')
            self.ids.add(attrs['id'])
        for key in ('href', 'src'):
            if attrs.get(key):
                self.refs.append(attrs[key])


def validate():
    pages = {}
    for path in OUT.rglob('*.html'):
        parser = Links()
        parser.feed(path.read_text())
        pages[path.resolve()] = parser
    for path, parser in pages.items():
        for ref in parser.refs:
            url = urlsplit(ref)
            if url.scheme or url.netloc:
                continue
            if url.path.startswith('/'):
                raise ValueError(f'Root-relative URL breaks project Pages: {ref}')
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            if target.is_dir():
                target /= 'index.html'
            if not target.is_relative_to(OUT.resolve()) or not target.is_file():
                raise ValueError(f'Missing local target in {path.name}: {ref}')
            if url.fragment and target in pages and unquote(url.fragment) not in pages[target].ids:
                raise ValueError(f'Missing anchor: {ref}')


def main():
    projects = json.loads((ROOT / 'site/projects.json').read_text())
    ids = [project['id'] for project in projects]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate project IDs')
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / 'site/assets', OUT / 'assets')
    template = (ROOT / 'site/index.html').read_text()
    assert template.count('<!-- PROJECTS -->') == 1
    (OUT / 'index.html').write_text(template.replace('<!-- PROJECTS -->', '\n'.join(map(project_card, projects))))
    (OUT / '.nojekyll').touch()
    validate()
    print(f'Built {len(projects)} projects; local links and anchors verified: {OUT}')


if __name__ == '__main__':
    main()
