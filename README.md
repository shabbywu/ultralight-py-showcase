# ultralight-py Showcase

ultralight-py 的示例展示站与源码入口，展示 Python 逻辑与 JavaScript 界面在原生桌面中的协作。

| 示例 | 状态 | 源码组织 |
| --- | --- | --- |
| [Emberkeep](https://github.com/shabbywu/emberkeep) | 已实现：像素 roguelike | `examples/emberkeep`，固定版本的 submodule |
| [Bridge Lab](examples/bridge-lab/README.md) | 规划中：交互式桥接实验室 | 预留 `examples/bridge-lab`，后续在本仓库开发 |

展示站是静态页面。原生示例需要桌面环境，其依赖、运行和验证说明由各项目独立维护。

## 获取与预览

Python 3.10+，无需 npm 或第三方 Python 网站依赖。

```sh
git clone --recurse-submodules https://github.com/shabbywu/ultralight-py-showcase.git
cd ultralight-py-showcase
python scripts/build_site.py
python -m http.server 8000 --directory dist
```

访问 http://localhost:8000 。构建生成 `dist/`，并检查本地资源、链接和锚点。只构建网站无需拉取 submodule。

已有 checkout 获取示例：

```sh
git submodule update --init --recursive
```

## 目录

```text
site/                       页面模板、项目清单、展示素材及许可
scripts/build_site.py       网站生成与本地链接校验
examples/emberkeep/         独立上游仓库 submodule
examples/bridge-lab/        桥接实验室项目计划
docs/ROADMAP.md             公开路线图
.github/workflows/pages.yml 构建与部署
```

## GitHub Pages

将变更推送到 `main` 前，在仓库 Settings → Pages → Build and deployment → Source 选择 **GitHub Actions**。

`Showcase Pages` 工作流在 PR 中构建校验，在 `main` 分支构建后部署。站点仅打包展示内容，不发布原生依赖或整个示例源码。

默认目标地址：https://shabbywu.github.io/ultralight-py-showcase/ 。实际发布状态以 Actions 与 Pages 设置为准。

## 维护

参见 [接入约定](CONTRIBUTING.md) 与 [路线图](docs/ROADMAP.md)。本地开发参考文件不作为网站内容或构建输入。

Emberkeep 展示截图来自对应示例，遵循其 [MIT 许可](site/assets/emberkeep-LICENSE.txt)。各示例和第三方组件保留自身许可；本站新增代码尚未指定统一许可。
