# ultralight-py Showcase

[简体中文](README.md) | [English](README.en.md)

A bilingual showcase and source hub for [shabbywu/ultralight-py](https://github.com/shabbywu/ultralight-py), demonstrating how Python logic and JavaScript interfaces work together in native desktop applications. The main project link always points to `shabbywu/ultralight-py`; the showcase website and native examples are maintained in this repository.

| Example | Status | Source layout |
| --- | --- | --- |
| [Emberkeep](https://github.com/shabbywu/emberkeep) | Implemented: pixel-art roguelike | `examples/emberkeep`, a submodule pinned to a specific revision |
| [PianoScope](examples/pianoscope/README.md) | Runnable: MusicXML piano practice, falling notes / grand staff, and PDF / original file / MIDI export | `examples/pianoscope`, including local sound assets, tests, a user guide, and sample resources |
| [Bridge Lab](examples/bridge-lab/README.md) | Implemented: six bridge experiments with editing on both the Python and JavaScript sides | `examples/bridge-lab`, including native smoke tests and a Chinese guide |
| [Ashen Reliquary](examples/ashen-reliquary/README.md) | Independent TypeScript grid inventory, ARPG equipment and Python native input checks | `examples/ashen-reliquary`, with native input checks and asset notices |

Emberkeep, PianoScope, and Bridge Lab include animated WebP recordings and separate native still images, with controls to pause and enlarge the preview. Ashen Reliquary provides a native screenshot and an interactive browser demo. The animations are silent previews; native examples do not run in the browser. Native examples require a desktop environment. Each project maintains its own dependency, execution, and validation instructions.

## Get started and preview

Requires Python 3.10+ and Node.js 20+. npm builds the Ashen browser demo; the site generator has no third-party Python dependencies.

```sh
git clone --recurse-submodules https://github.com/shabbywu/ultralight-py-showcase.git
cd ultralight-py-showcase
npm ci --prefix examples/ashen-reliquary/web
npm run build --prefix examples/ashen-reliquary/web
python scripts/build_site.py
python -m unittest discover -s scripts -p 'test_*.py' -v
python -m http.server 8000 --directory dist
```

Open http://localhost:8000. The build generates `dist/` and validates bilingual translation keys, genuine multi-frame animations, local resources, links, and anchors. Building only the website does not require fetching the submodule, Pillow, a WebP encoder, or native application dependencies.

The Chinese and English pages are available at `zh-CN/` and `en/`, respectively, each with complete static content. Switching languages preserves the project anchor and remembers your choice. With JavaScript enabled, the root entry selects a language based on your previous choice or browser language. With JavaScript disabled, the Chinese content remains readable and includes a link to English. Animations load only near the viewport and stop when they leave it or the page is hidden. A still image is shown by default when the system's reduced-motion preference is enabled. With JavaScript disabled, ordinary links provide access to animations and full-size images.

To fetch the examples in an existing checkout:

```sh
git submodule update --init --recursive
```

## Directory layout

```text
site/                       Page templates, bilingual example catalog, actual demo assets, and licenses
site/locales/               Chinese (zh-CN) and English (en) interface text
scripts/build_site.py       Bilingual static page generation, media and local link validation
scripts/test_build_site.py  Build and content constraint regression tests
examples/emberkeep/         Submodule from a separate upstream repository
examples/bridge-lab/        Runnable bridge lab, tests, and Chinese guide
examples/pianoscope/        Native piano practice player, MusicXML scores and export, and sound assets
.github/workflows/pages.yml Build and deployment
```

## GitHub Pages

Before pushing changes to `main`, select **GitHub Actions** under Settings → Pages → Build and deployment → Source in the repository.

The `Showcase Pages` workflow builds and validates pull requests, and builds and deploys the `main` branch. The site packages showcase content and the Ashen browser demo, with corresponding source links. Native dependencies are not published.

Default destination: https://shabbywu.github.io/ultralight-py-showcase/. Check Actions and Pages settings for the actual deployment status.

## Maintenance

See the [integration guide](CONTRIBUTING.md) for adding or updating examples, and each example's README for execution, testing, and platform validation instructions.

The original scores, games, and associated showcase assets for Emberkeep and PianoScope retain their respective MIT licenses. Bridge Lab and newly added website code do not yet have a shared license. See the [showcase asset notes](site/assets/MEDIA.md) for asset sources and permitted scope of use. Each example and third-party component retains its own license.

[Ashen Reliquary · Play in browser](https://shabbywu.github.io/ultralight-py-showcase/demos/ashen-reliquary/)
