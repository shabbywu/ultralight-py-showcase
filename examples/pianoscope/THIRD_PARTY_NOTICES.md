# 第三方组件与素材

## 钢琴 SoundFont

`pianoscope/resources/soundfonts/TimGM6mb.sf2` 是 TimGM6mb（约 5.7 MiB），使用 bank 0 / preset 0 的 Acoustic Grand Piano。完整文件随源码提供，启动时不联网、不调用系统 MIDI 音源。

- 作者：Tim Brechbill（2004）、David Bolton（2010）。
- 数据许可：GPL-2.0；保留 [原始版权记录](pianoscope/resources/soundfonts/COPYRIGHT) 和 [GPL 全文](pianoscope/resources/soundfonts/GPL-2.0.txt)。它与本项目 MIT 源码分别保留许可。
- 获取来源：[上游发行数据的镜像](https://github.com/deepin-community/timgm6mb-soundfont/blob/a4ecf408520447604b4e0f85154f6803ff944611/TimGM6mb.sf2)。原始来源及样本说明见 COPYRIGHT。
- SHA-256：`c5378b62028c920cb11e4803327983fee2f2cdff5dc89c708e39da417e51c854`。
- 本项目没有修改 SoundFont；原始可编辑 SoundFont 数据即随附的 `.sf2`。

## 曲目、截图与字体

本项目的原创乐谱、MIDI 测试夹具及其派生 PDF／MIDI 和界面截图采用本项目 MIT 许可，个人乐谱不随仓库分发。内置“初光”和“回环与晨光”由 [generate_fixtures.py](tools/generate_fixtures.py) 直接编写 MusicXML；其他 XML 测试夹具同样为直接创作的源乐谱。

`docs/screenshots/` 中的正式图片来自真实 AppCore CPU View，使用本项目原创曲与随包音源，未使用生成式图片。

产品界面使用系统无衬线字体（macOS 为 PingFang SC）。五线谱与 PDF 使用随包 Noto Sans CJK SC Regular（OFL-1.1）与 Verovio 随 wheel 提供的 Leipzig 音乐字形（OFL-1.1）；生成时转换为路径，不依赖用户机器字体或联网。

## 运行依赖

| 组件 | 本机验证版本 | 许可／来源 |
| --- | --- | --- |
| ultralight-py | 0.5.0 | [项目源码与许可](https://github.com/shabbywu/ultralight-py)；Ultralight 原生 SDK 另受其 [官方条款](https://ultralig.ht/license/) 约束 |
| FluidSynth | 2.6.1 | [LGPL-2.1-or-later](https://github.com/FluidSynth/fluidsynth/blob/master/LICENSE)；通过系统动态库加载，不随本项目复制库文件 |
| PortAudio | 19.7.0 | [MIT 风格许可](https://www.portaudio.com/license.html)，由 sounddevice 使用 |
| sounddevice | 0.5.6 | [MIT](https://github.com/spatialaudio/python-sounddevice/blob/master/LICENSE) |
| Mido | 1.3.3 | [MIT](https://github.com/mido/mido/blob/main/LICENSE) |
| NumPy | 2.2.6 | [BSD-3-Clause 及所含组件许可](https://numpy.org/doc/stable/license.html) |
| PyObjC Cocoa | 12.2.2 | [MIT](https://github.com/ronaldoussoren/pyobjc/blob/master/LICENSE.txt)，仅 macOS 文件选择和窗口生命周期适配 |

Python 包的原始许可随其发行包保留，具体依赖与哈希见 `uv.lock`。本项目未制作包含这些原生库的发行包。

安全 XML 读取使用 defusedxml 0.7.1（PSF license；[随附全文](docs/licenses/defusedxml-LICENSE)）。

## 乐谱排版与测试依赖

| 组件 | 锁定版本／本机资源 | 许可与用途 |
| --- | --- | --- |
| Verovio | 5.6.0；原生引擎 5.6.0-85e7620；macOS 11+ arm64 CPython 3.10 wheel | LGPL-3.0；Python 原生 MusicXML 排版；[GPL 全文](docs/licenses/verovio-COPYING)、[LGPL 补充](docs/licenses/verovio-COPYING.LESSER)，[固定版本源码](https://github.com/rism-digital/verovio/tree/version-5.6.0) |
| Leipzig | wheel 的 `verovio/data/Leipzig/*.xml`、`Leipzig.xml` | [OFL-1.1 全文](docs/licenses/Leipzig-OFL.txt)；[原始字体与可编辑源文件](https://github.com/rism-digital/leipzig)，未修改字体 |
| CairoSVG | 2.8.2 | LGPL-3.0-or-later；[全文](docs/licenses/CairoSVG-LICENSE)，SVG → PNG/PDF |
| cairocffi | 1.7.1 | BSD-3-Clause；[全文](docs/licenses/cairocffi-LICENSE)，Cairo 动态库接口 |
| Cairo | 1.18.4，本机 `/opt/homebrew/lib/libcairo.2.dylib` | [LGPL-2.1 / MPL-1.1](https://www.cairographics.org/)，系统安装，不复制原生库 |
| pypdf | 6.12.2 | BSD-3-Clause；[全文](docs/licenses/pypdf-LICENSE)，PDF 页面合并 |
| fonttools | 4.63.0 | MIT 及外部组件；[全文](docs/licenses/fonttools-LICENSE)、[外部许可](docs/licenses/fonttools-LICENSE.external)，真实字形边界与文字轮廓 |
| psutil | 7.2.2 | BSD-3-Clause；[全文](docs/licenses/psutil-LICENSE)，worker RSS 上限检查 |
| Noto Sans CJK SC Regular | 16,437,364 bytes，随包 `pianoscope/resources/fonts/NotoSansCJKsc-Regular.otf` | [OFL-1.1 全文](pianoscope/resources/fonts/OFL.txt)，[上游原始字体](https://github.com/notofonts/noto-cjk/tree/main/Sans/OTF/SimplifiedChinese)；未修改，SHA-256 `2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b` |
| music21（仅 test extra） | 9.9.1 | BSD-3-Clause；[全文](docs/licenses/music21-LICENSE)，独立读写 MusicXML，不承担产品记谱 |
| PyMuPDF（仅 test extra） | 1.27.2.3 | AGPL-3.0 / 商业双许可；[全文](docs/licenses/pymupdf-COPYING)，验证时 PDF 渲染；产品运行不导入／分发此库 |

精确 Python 包及传递依赖、wheel URL 和 SHA-256 由 `uv.lock` 固定。music21 和 PyMuPDF 仅用于测试，不参与产品播放。所有音乐字形、中文字体和音源在安装后本地可用，无运行时下载。

`score/process.py`／`score/worker.py` 用独立 Python 子进程运行 Verovio／CairoSVG，避免字体／原生库状态影响 AppCore 和音频回调。macOS Cairo 的库定位只在该子进程中临时补充 Homebrew 路径，不修改主进程动态库搜索。SVG 中的文字全部转换为本地字体路径，避免 CairoSVG 忽略网页字体导致的速度音符缺字；相同 SVG 输出 Canvas 底图和黑白 PDF。多页 PDF 用 pypdf 合并，实测页面为 595.2756 × 841.8898 pt（A4）。

新增源码和原创验证 MIDI 继续采用本目录 MIT；各依赖保留其自己的许可。未制作发行包。
