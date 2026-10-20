# 接入与维护示例

每个示例需注明用途、状态、能力点、源码入口和运行说明，并记录截图来源、素材许可与实际验证范围。规划项目保留公开简介，验收后再更新为“已实现”。

## 源码组织

- 已有独立仓库：使用 `git submodule add <repo-url> examples/<slug>`，提交 `.gitmodules` 与 gitlink，固定经过审阅的版本。
- 在本仓库维护：源码放入 `examples/<slug>/`，提供独立 README、依赖、测试和许可证说明。
- 展示站不依赖原生示例环境，不将整个示例目录打包到 Pages。
- 临时报告、日志、调试截图、渲染中间文件、个人 MIDI 和本地设计参考统一放入根目录 `.tmp/<示例名>/`，该目录不提交。正式文档只保留维护所需的摘要，以及少量明确选定的展示截图、原创导出样本；验证脚本不得直接覆盖这些正式产物。

## 展示入口

编辑 `site/projects.json`：填写唯一 `id`、`title`、`source`、`guide`，以及每个样例独立的 `animation`（多帧 WebP）、`poster`（动画静帧 PNG）、`image`（独立静态 PNG）、`license`（许可或来源说明）。`releases` 为可选的真实发行页。

如果还需说明音源、字体等组件的许可边界，可用可选的 `notice` 链接到正式素材说明；该链接也会出现在中英文许可页中。

`kind`、`description`、`features`、`image_alt`、`animation_alt`、`license_label` 都需要同时填写 `zh-CN` 和 `en`。站点通用文案在 `site/locales/zh-CN.json` 和 `site/locales/en.json`，两份键集合及格式占位符必须一致，不留空译文。主项目标识与 GitHub 入口为 `shabbywu/ultralight-py`，各样例链接指向其实际源码仓库。

图片放入 `site/assets/`，保留许可及真实来源。动画从实际原生窗口像素录制，不用设计图、模拟输出或静图冒充动图。PNG 静帧用于低动态效果、离屏暂停及加载失败回退；独立静图应展示适合仔细阅读的状态。更新时保留原始录制帧、执行结果、机器信息在根 `.tmp/`，只选择正式压缩素材发布；不发布个人曲目、音轨、原生依赖或完整应用资源。构建不依赖录制环境。

执行 `python -m unittest discover -s scripts -p 'test_*.py' -v` 与 `python scripts/build_site.py`，预览中英文桌面和窄屏。检查双媒体布局、动图播放／暂停、减少动态效果、静图放大与关闭、语言切换后的项目锚点及源码入口。页面内部必须使用相对链接，以兼容 GitHub Pages 项目子路径；构建会校验本地图片、动图、许可、链接和锚点。本地需求、交接文档和开发参考不自动加入公开站点。

## 更新 Emberkeep

```sh
git -C examples/emberkeep fetch origin
git -C examples/emberkeep checkout <reviewed-commit-or-tag>
git add examples/emberkeep
```

检查上游 README、验收记录和许可，再提交新 gitlink；不自动跟随上游 HEAD。网站截图与动图为独立副本，更新时从实际运行同步并检查许可。CI 无需递归 checkout。
