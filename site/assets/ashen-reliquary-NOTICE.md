# Ashen Reliquary / 原生演示素材

[完整对应源码 / Source](https://github.com/shabbywu/ultralight-py-showcase/tree/main/examples/ashen-reliquary)

`ashen-reliquary-demo.webp`, `ashen-reliquary-poster.png` and `ashen-reliquary.png` are recordings/captures of the actual AppCore CPU window running ultralight-py 0.6.1. The animation demonstrates native input for equipment, drag rotation, shortcut binding, socketing, extraction and stack splitting, plus Python-owned relic generation and state-change notifications. The recording uses an isolated demo session with a deterministic selection of new relic definitions.

动图和截图来自真实原生窗口像素。操作通过原生 View 鼠标／键盘接口执行；新物品由 Python 后端生成，最后一次生成由后端直接触发，再通知前端刷新。海报取自动图第一帧；画面仅缩放与压缩，没有生成帧、合成结果或音频。原始帧和时间戳保存在本地 `.tmp/ashen-reliquary/recording/`，不随站点发布。

The current application requires a native backend; GitHub Pages presents recorded media and does not publish a browser-playable build or native Ultralight libraries.

Source code retains its upstream GPL v3 notice. Item photographs are from Cleveland Museum of Art Open Access (CC0); textures derive from CC0 sources. Grenze / Grenze Gotisch fonts use SIL OFL 1.1. Vue and build dependencies retain their own licenses.

- [Retained GPL v3 text](https://github.com/shabbywu/ultralight-py-showcase/blob/main/examples/ashen-reliquary/LICENSE.GPL-3.0.txt)
- [Component and source notices](https://github.com/shabbywu/ultralight-py-showcase/blob/main/examples/ashen-reliquary/THIRD_PARTY_NOTICES.md)
- [Artwork source manifest](https://github.com/shabbywu/ultralight-py-showcase/blob/main/examples/ashen-reliquary/web/public/reliquary/LICENSES.md)
