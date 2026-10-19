# 接入与维护示例

每个示例需注明用途、状态、能力点、源码入口和运行说明，并记录截图来源、素材许可与实际验证范围。规划项目保留公开简介，验收后再更新为“已实现”。

## 源码组织

- 已有独立仓库：使用 `git submodule add <repo-url> examples/<slug>`，提交 `.gitmodules` 与 gitlink，固定经过审阅的版本。
- 在本仓库维护：源码放入 `examples/<slug>/`，提供独立 README、依赖、测试和许可证说明。
- 展示站不依赖原生示例环境，不将整个示例目录打包到 Pages。
- 临时报告、日志、调试截图、渲染中间文件、个人 MIDI 和本地设计参考统一放入根目录 `.tmp/<示例名>/`，该目录不提交。正式文档只保留维护所需的摘要，以及少量明确选定的展示截图、原创导出样本；验证脚本不得直接覆盖这些正式产物。

## 展示入口

编辑 `site/projects.json`：填写唯一 `id`、`title`、`status`、`kind`、`description`、`features`、`source`。可选 `source_label`、`image`、`image_alt`（截图替代文字）、`guide`（运行指南）、`releases`（发行页面）。

图片放入 `site/assets/`，保留许可；页面内部使用相对链接，以兼容 GitHub Pages 项目子路径。新增项目时同时检查模板中的配图与替代文字是否适用。

执行 `python scripts/build_site.py`，预览桌面和窄屏，检查源码与运行说明入口。本地需求、交接文档和开发参考不自动加入公开站点。

## 更新 Emberkeep

```sh
git -C examples/emberkeep fetch origin
git -C examples/emberkeep checkout <reviewed-commit-or-tag>
git add examples/emberkeep
```

检查上游 README、验收记录和许可，再提交新 gitlink；不自动跟随上游 HEAD。网站截图为独立副本，更新时从实际运行截图同步到 `site/assets/emberkeep.png` 并检查许可。CI 无需递归 checkout。
