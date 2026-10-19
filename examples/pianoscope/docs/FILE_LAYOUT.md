# 文件与本地产物

源码、测试夹具、运行所需音源／字体、精确依赖与许可说明保留在示例目录。`docs/` 只保存维护文档、验收摘要，以及明确选定的一张原生截图和两组原创 PDF／MusicXML 样本。展示站使用 `site/assets/pianoscope.png` 的独立正式副本。

临时文件统一放在仓库根目录 `.tmp/pianoscope/`，由根 `.gitignore` 排除：

| 目录 | 内容 |
| --- | --- |
| `midi/` | 用户自行加入的 MIDI，不作为随包演示或必需测试夹具 |
| `validation/reports/` | JSON、JUnit XML、日志，包括失败与未测记录 |
| `validation/screenshots/` | 原生冒烟、调试和不同尺寸的截图 |
| `validation/samples/` | 自动导出、阅读器副本、逐页图片、布局／来源 JSON、SVG 和单页 PDF |
| `specs/`、`reference/`、`planning/` | 本地需求 HTML、设计图、生成提示词和历史交接材料 |
| `exports/` | 本地手动导出的文件 |
| `pytest-cache/` | pytest 缓存 |

2026-10-18 清理迁移了 206 个文件，约 60 MiB。完整清单及文件校验值保存在本地 `cleanup-manifest.json`；个人 MIDI 未修改、未删除。历史报告正文中的原路径与测量结果保留原样，文档链接已更新到迁移位置；这些本地证据不会随新克隆出现，也不代表重新验证过。

验证脚本通过 `pianoscope/dev_paths.py` 取得上述路径，默认不再写入正式文档目录。`run.py` 的原生冒烟默认报告为 `validation/reports/native-latest.json`；`--smoke-report` 可显式指定其他位置。可以通过 `PIANOSCOPE_TMP_DIR` 把整个本地目录放到仓库外，通过 `PIANOSCOPE_MIDI_DIR` 指定独立的个人 MIDI 目录。普通应用仍通过原生文件／文件夹选择器加载曲目，导出位置由用户选择，不受开发目录约定限制。

没有个人 MIDI 时，相关 pytest 用例跳过；显式运行三首用户曲目的原生验收前，需要准备本地输入。源码中的小型原创 MIDI 夹具继续随仓库保存，其中 `tests/fixtures/score-edge-phrase.mid` 支持原生变拍／延音回归，不依赖上次导出的临时样本。

`.venv`、安装元数据、Python 缓存和标准构建目录沿用各工具的惯例路径并排除提交。更新正式截图／样本时，应在检查后明确复制所选文件，验证脚本不自动覆盖它们。日常只运行受改动影响的定向检查，完整回归与长时性能测试单独安排。
