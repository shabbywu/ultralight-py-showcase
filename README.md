# ultralight-py Showcase

[简体中文](README.md) | [English](README.en.md)

[shabbywu/ultralight-py](https://github.com/shabbywu/ultralight-py) 的中英文示例展示站与源码入口，展示 Python 逻辑与 JavaScript 界面在原生桌面中的协作。主项目入口始终指向 `shabbywu/ultralight-py`；本站源码与原生示例在本 showcase 仓库维护。

| 示例 | 状态 | 源码组织 |
| --- | --- | --- |
| [Emberkeep](https://github.com/shabbywu/emberkeep) | 已实现：像素 roguelike | `examples/emberkeep`，固定版本的 submodule |
| [PianoScope](examples/pianoscope/README.md) | 可运行：MusicXML 钢琴练习、下落音符／双谱表、PDF／原件／MIDI 导出 | `examples/pianoscope`，含本地音源、测试、用户指南与示例资源 |
| [Bridge Lab](examples/bridge-lab/README.md) | 已实现：六个 Python/JS 双端编辑桥接实验 | `examples/bridge-lab`，含原生冒烟测试与中文指南 |
| [Ashen Reliquary](examples/ashen-reliquary/README.md) | 独立 TypeScript 网格背包、ARPG 装备与 Python 原生输入验收 | `examples/ashen-reliquary`，含真实输入检查与美术来源 |

Emberkeep、PianoScope 和 Bridge Lab 提供真实原生录制的动画 WebP 和独立静图，支持暂停与放大查看。Ashen Reliquary 提供原生截图和[浏览器在线试玩](https://shabbywu.github.io/ultralight-py-showcase/demos/ashen-reliquary/)。动图仅为无声展示，不在浏览器中执行原生示例。原生示例需要桌面环境，其依赖、运行和验证说明由各项目独立维护。

## 获取与预览

Python 3.10+ 与 Node.js 20+；npm 用于构建 Ashen 浏览器试玩，网站生成器无需第三方 Python 依赖。

```sh
git clone --recurse-submodules https://github.com/shabbywu/ultralight-py-showcase.git
cd ultralight-py-showcase
npm ci --prefix examples/ashen-reliquary/web
npm run build --prefix examples/ashen-reliquary/web
python scripts/build_site.py
python -m unittest discover -s scripts -p 'test_*.py' -v
python -m http.server 8000 --directory dist
```

访问 http://localhost:8000 。构建生成 `dist/`，并检查双语键值、真实多帧动图、本地资源、链接和锚点。只构建网站无需拉取 submodule，也无需 Pillow、WebP 编码器或原生应用依赖。

中文与英文页面分别位于 `zh-CN/`、`en/`，直接访问即可获得完整静态内容。语言切换保留项目锚点并记住选择；根入口在启用 JavaScript 时按上次选择或浏览器语言进入对应页面，禁用 JavaScript 时仍能阅读中文并切换英文。动图仅在接近视口时加载，离开视口或隐藏页面时停止；系统启用“减少动态效果”时默认显示静帧。禁用 JavaScript 时可用普通链接查看动图与大图。

已有 checkout 获取示例：

```sh
git submodule update --init --recursive
```

## 目录

```text
site/                       页面模板、双语项目清单、真实展示素材及许可
site/locales/               zh-CN 与 en 的界面文案
scripts/build_site.py       双语静态页面生成、媒体与本地链接校验
scripts/test_build_site.py  构建与内容约束回归
examples/emberkeep/         独立上游仓库 submodule
examples/bridge-lab/        可运行桥接实验室、测试与中文指南
examples/pianoscope/        原生钢琴练习播放器、MusicXML 曲目与导出、真实音源
.github/workflows/pages.yml 构建与部署
```

## GitHub Pages

将变更推送到 `main` 前，在仓库 Settings → Pages → Build and deployment → Source 选择 **GitHub Actions**。

`Showcase Pages` 工作流在 PR 中构建校验，在 `main` 分支构建后部署。站点打包展示内容与 Ashen 浏览器试玩，不发布原生依赖；完整源码链接位于对应示例卡片。

默认目标地址：https://shabbywu.github.io/ultralight-py-showcase/ 。实际发布状态以 Actions 与 Pages 设置为准。

## 维护

新增或更新示例参见 [接入指南](CONTRIBUTING.md)；运行、测试与平台验证说明见各示例 README。

Emberkeep 和 PianoScope 的原创乐谱、游戏及相应展示素材保留各自 MIT 许可；Bridge Lab 与本站新增代码尚未指定统一许可。素材来源与适用范围见 [展示素材说明](site/assets/MEDIA.md)；各示例和第三方组件保留自身许可。

[Ashen Reliquary · 在线试玩](https://shabbywu.github.io/ultralight-py-showcase/demos/ashen-reliquary/)
