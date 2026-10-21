"""Build the bilingual GitHub Pages showcase without third-party dependencies."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ("zh-CN", "en")
TOKEN = re.compile(r"\{\{([A-Za-z_]+)\}\}")


def e(value: object) -> str:
    return escape(str(value), quote=True)


def render(template: str, messages: dict, **raw: str) -> str:
    values = {key: e(value) for key, value in messages.items()} | raw
    result = TOKEN.sub(lambda match: values[match[1]], template)
    if "{{" in result:
        raise ValueError("Unresolved template token")
    return result


def locale_nav(locale: str, prefix: str, page: str = "") -> str:
    return "".join(
        f'<a href="{prefix}{code}/{page}" lang="{code}" hreflang="{code}" '
        f'data-language="{code}"'
        + (' aria-current="page"' if code == locale else "")
        + f">{label}</a>"
        for code, label in (("zh-CN", "中文"), ("en", "EN"))
    )


def dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Expected a real PNG screenshot: {path}")
    return struct.unpack(">II", data[16:24])


def animation_frames(path: Path) -> int:
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError(f"Expected animated WebP: {path}")
    cursor, frames, animated = 12, 0, False
    while cursor + 8 <= len(data):
        kind = data[cursor : cursor + 4]
        size = int.from_bytes(data[cursor + 4 : cursor + 8], "little")
        if cursor + 8 + size > len(data):
            raise ValueError(f"Truncated WebP: {path}")
        animated |= kind == b"ANIM"
        frames += kind == b"ANMF"
        cursor += 8 + size + (size & 1)
    if not animated or frames < 2:
        raise ValueError(f"Demo must contain multiple real animation frames: {path}")
    return frames


def read_content(source: Path) -> tuple[list[dict], dict[str, dict]]:
    projects = json.loads((source / "projects.json").read_text(encoding="utf-8"))
    catalogs = {
        locale: json.loads(
            (source / "locales" / f"{locale}.json").read_text(encoding="utf-8")
        )
        for locale in LOCALES
    }
    if set(catalogs["zh-CN"]) != set(catalogs["en"]):
        raise ValueError("Locale catalogs must have identical keys")
    for key in catalogs["zh-CN"]:
        for locale in LOCALES:
            if (
                not isinstance(catalogs[locale][key], str)
                or not catalogs[locale][key].strip()
            ):
                raise ValueError(f"Missing localized string: {locale}.{key}")
        fields = [
            set(re.findall(r"\{(\w+)\}", catalogs[locale][key])) for locale in LOCALES
        ]
        if fields[0] != fields[1]:
            raise ValueError(f"Translation placeholders differ: {key}")
    ids = [project["id"] for project in projects]
    if len(ids) != len(set(ids)) or any(
        not re.fullmatch(r"[a-z0-9-]+", ident) for ident in ids
    ):
        raise ValueError("Project IDs must be unique URL-safe slugs")
    for project in projects:
        for field in (
            "kind",
            "description",
            "features",
            "image_alt",
            "license_label",
        ):
            if set(project[field]) != set(LOCALES) or not all(project[field].values()):
                raise ValueError(
                    f"Missing project translations: {project['id']}.{field}"
                )
        for key in ("source", "guide", "releases"):
            if key in project and urlsplit(project[key]).scheme != "https":
                raise ValueError(f"Project links must use HTTPS: {key}")
        for key in ("image", "poster", "animation", "license", "notice"):
            if key not in project and key == "notice":
                continue
            target = (source / project[key]).resolve()
            if (
                not target.is_relative_to((source / "assets").resolve())
                or not target.is_file()
            ):
                raise ValueError(f"Missing demo or license: {project['id']}.{key}")
        animation_frames(source / project["animation"])
        dimensions(source / project["poster"])
        if set(project.get("animation_alt", {})) != set(LOCALES):
            raise ValueError("Missing animation translations")
        dimensions(source / project["image"])
    return projects, catalogs


def project_card(
    project: dict, locale: str, prefix: str, t: dict, source: Path, index: int
) -> str:
    title, slug = e(project["title"]), e(project["id"])
    image = e(prefix + project["image"])
    poster = e(prefix + project.get("poster", project["image"]))
    animation = e(prefix + project.get("animation", ""))
    alt = e(project["image_alt"][locale])
    motion_alt = e(project.get("animation_alt", project["image_alt"])[locale])
    label = e(t["expand_label"].format(project=project["title"]))
    width, height = dimensions(source / project["image"])
    pw, ph = dimensions(source / project.get("poster", project["image"]))
    tags = "".join(f"<li>{e(tag)}</li>" for tag in project["features"][locale])
    links = "".join(
        f'<a href="{e(project[key])}">{e(t[label])} <span aria-hidden="true">↗</span></a>'
        for key, label in (
            ("source", "source"),
            ("guide", "guide"),
            ("releases", "release"),
        )
        if key in project
    )
    motion = f'''
<figure class="demo motion-demo" data-animation="{animation}" data-poster="{poster}" data-title="{title}">
  <figcaption><span class="media-title"><i class="media-dot" aria-hidden="true"></i>{e(t["animated"])}</span><span class="loop-label"><span aria-hidden="true">↻</span>{e(t["loop_preview"])}</span></figcaption>
  <img class="demo-image animated-image" src="{poster}" width="{pw}" height="{ph}" loading="lazy" decoding="async" alt="{motion_alt}">
  <div class="motion-controls"><button type="button" class="motion-toggle" aria-pressed="false" hidden><span class="motion-symbol" aria-hidden="true">▶</span><span class="motion-label">{e(t["play"])}</span></button><span class="motion-state">{e(t["paused"])}</span><noscript><a href="{animation}">{e(t["play"])} ↗</a></noscript></div>
</figure>'''
    return f'''<article class="project" id="{slug}" aria-labelledby="{slug}-title">
  <div class="project-heading"><h3 id="{slug}-title"><span class="project-number">{index:02}</span>{title}</h3><span class="kind">{e(project["kind"][locale])}</span><div class="project-links">{links}</div></div>
  <p class="project-description">{e(project["description"][locale])}</p><ul class="tags">{tags}</ul>
  <div class="media-pair">
    {motion}

    <figure class="demo still-demo">
      <figcaption><span class="media-title"><span class="image-icon" aria-hidden="true">▧</span>{e(t["still"])}</span><a class="expand" href="{image}" aria-label="{label}" data-lightbox data-title="{title}" data-alt="{alt}">{e(t["expand"])} ↗</a></figcaption>
      <a class="still-link" href="{image}" aria-label="{label}" data-lightbox data-title="{title}" data-alt="{alt}"><img class="demo-image still-image" src="{image}" width="{width}" height="{height}" loading="lazy" decoding="async" alt="{alt}"></a>
      <div class="still-caption">{e(project["license_label"][locale])}</div>
    </figure>
  </div>
</article>'''


def license_page(locale: str, prefix: str, t: dict, projects: list[dict]) -> str:
    items = "".join(
        f'<section class="license-item"><h2>{e(p["title"])}</h2><a href="{e(prefix + p["license"])}">{e(p["license_label"][locale])} ↗</a>'
        f'<p><a href="{e(p["source"])}">{e(t["source"])} ↗</a></p>'
        + (
            f'<p><a href="{e(prefix + p["notice"])}">{e(t["license_details"])} ↗</a></p>'
            if p.get("notice")
            else ""
        )
        + "</section>"
        for p in projects
    )
    return f'''<!doctype html><html lang="{locale}" data-locale="{locale}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(t["license_title"])} · ultralight-py</title><link rel="stylesheet" href="{prefix}assets/style.css"><link rel="icon" href="{prefix}assets/favicon.svg"><script src="{prefix}assets/app.js" defer></script></head>
<body><header class="shell bar"><a href="./">← {e(t["back"])}</a><div class="language" role="group" aria-label="{e(t["language"])}">{locale_nav(locale, prefix, "licenses.html")}</div></header><main class="shell license-main"><p class="eyebrow">ULTRALIGHT-PY / SHOWCASE</p><h1>{e(t["license_title"])}</h1><p>{e(t["license_description"])}</p><p>{e(t["license_code"])}</p><div class="license-list">{items}</div></main></body></html>'''


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attrs = dict(attrs)
        if "id" in attrs:
            if attrs["id"] in self.ids:
                raise ValueError(f"Duplicate id: {attrs['id']}")
            self.ids.add(attrs["id"])
        for key in ("href", "src", "data-animation", "data-poster"):
            if attrs.get(key):
                self.refs.append(attrs[key])


def validate(output: Path) -> None:
    pages = {}
    for path in output.rglob("*.html"):
        parser = Links()
        parser.feed(path.read_text(encoding="utf-8"))
        pages[path.resolve()] = parser
    for path, parser in pages.items():
        for ref in parser.refs:
            url = urlsplit(ref)
            if url.scheme or url.netloc:
                if url.scheme and url.scheme not in ("https", "http"):
                    raise ValueError(f"Unsupported URL scheme: {ref}")
                continue
            if url.path.startswith("/"):
                raise ValueError(f"Root-relative URL breaks project Pages: {ref}")
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            if target.is_dir():
                target /= "index.html"
            if not target.is_relative_to(output.resolve()) or not target.is_file():
                raise ValueError(f"Missing local target in {path}: {ref}")
            if (
                url.fragment
                and target in pages
                and unquote(url.fragment) not in pages[target].ids
            ):
                raise ValueError(f"Missing anchor: {ref}")


def build(source: Path, output: Path) -> None:
    projects, catalogs = read_content(source)
    template = (source / "index.html").read_text(encoding="utf-8")
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(source / "assets", output / "assets")
    for locale, directory in (("zh-CN", ""), ("zh-CN", "zh-CN"), ("en", "en")):
        prefix = "../" if directory else ""
        folder = output / directory
        folder.mkdir(parents=True, exist_ok=True)
        t = catalogs[locale]
        messages = json.dumps(t, ensure_ascii=False).replace("<", "\\u003c")
        html = render(
            template,
            t,
            LANG=locale,
            ENTRY="false" if directory else "true",
            PREFIX=prefix,
            LOCALE_NAV=locale_nav(locale, prefix),
            PROJECT_INDEX="".join(
                f'<a href="#{e(p["id"])}">{i:02}<span>{e(p["title"])}</span></a>'
                for i, p in enumerate(projects, 1)
            ),
            PROJECTS="\n".join(
                project_card(p, locale, prefix, t, source, i)
                for i, p in enumerate(projects, 1)
            ),
            MESSAGES=messages,
        )
        (folder / "index.html").write_text(html, encoding="utf-8")
        (folder / "licenses.html").write_text(
            license_page(locale, prefix, t, projects), encoding="utf-8"
        )
    (output / ".nojekyll").touch()
    # Keep stable file paths while invalidating cached assets after an update.
    versions = {
        name: hashlib.sha256((output / "assets" / name).read_bytes()).hexdigest()[:12]
        for name in ("style.css", "app.js")
    }
    asset_ref = re.compile(r'((?:href|src)="[^"]*assets/(style\.css|app\.js))"')
    for page in output.rglob("*.html"):
        html = asset_ref.sub(
            lambda match: f'{match[1]}?v={versions[match[2]]}"',
            page.read_text(encoding="utf-8"),
        )
        page.write_text(html, encoding="utf-8")
    validate(output)
    print(
        f"Built {len(projects)} projects × 2 locales; recorded showcase media; links, translations and animation frames verified: {output}"
    )


def main() -> None:
    build(ROOT / "site", ROOT / "dist")


if __name__ == "__main__":
    main()
