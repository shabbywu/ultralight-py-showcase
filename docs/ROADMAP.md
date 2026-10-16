# 项目路线图

## 组织方式

展示站使用静态 HTML/CSS 与 Python 标准库构建，部署到 GitHub Pages。公开项目清单维护在 `site/projects.json`。

Emberkeep 独立发布，以固定版本的 submodule 引用；Bridge Lab 已在本仓库的独立目录实现 P0。展示素材保留固定副本，使网站构建独立于示例源码与原生 SDK。

## 已完成

- Bridge Lab：六类真实桥接场景、可编辑 JS、Python 实际源码、Console 与 Inspector。
- 模型、注册契约及 AppCore 原生自动测试；macOS ARM64 上 GPU / CPU 冒烟通过。
- 2026-10-16 用户反馈功能验收正常；真实 AppCore 截图已同步到展示站。

## 下一步

1. 完成展示站的桌面与移动端视觉检查，发布 GitHub Pages，确认项目子路径访问正常。
2. 补充 Bridge Lab 在 Windows / Linux 与其他 Python 版本的原生验证。
3. 根据后续需求推进 Bridge Lab P1：Python 主动推送、导航恢复展示与日志导出。
4. 随实际产出补充运行指南、录屏和发行包入口；按内容增长需要增加项目详情页与双语支持。

## 验收范围

网站构建只验证静态资源与站内链接，不代表原生示例通过测试。各示例独立记录测试平台、版本、命令与结果；发行包由各自项目的发布流程提供。
