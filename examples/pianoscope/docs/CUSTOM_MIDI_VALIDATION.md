# 文件夹曲库、左右手设置与自定义 MIDI 验收

机器报告、调试截图和批量样本已迁至本地 `.tmp/pianoscope/`，不提交；本文保留验收摘要及原有通过／失败／未测状态。参见 [文件约定](FILE_LAYOUT.md)。

这是自动整理实现之前的历史验收。两首完整转换的最新交付见 [READABLE_VALIDATION.md](READABLE_VALIDATION.md)，本页的严格模式结果保留。

日期：2026-10-18。Python 3.10.20、ultralight-py 0.5.0、本机 macOS / Apple Silicon，原生 AppCore，实际 MacBook Air 扬声器。沿用 v1.1 的依赖、音频时钟和记谱配置版本 1；没有放宽量化规则或修改用户文件。

## 已交付

- 侧栏“选择文件夹”调用原生目录选择器，列出直属 MIDI 文件，支持文件名搜索、长曲名换行和点击加载；保留“打开单曲”。目录扫描在后台，不解析所有曲目、不生成声音、不打断播放。不递归子目录，最多 1,000 首；超限显式报错，取消或失败保留旧列表。列表为会话状态，重新选目录可刷新。
- 曲库使用独立不透明 token，不受单文件入口最近 16 个 token 的淘汰影响；换目录原子替换列表，迟到的扫描不能覆盖较新的选择。加载失败保留旧曲。
- 左右手设置先选分配方式：按轨道仅显示轨道手别；按音高仅显示分界音、规则说明和双手音符计数。轨道试听仍有独立静音／独奏设置。修改参数使旧预览失效，异步返回的旧预览也不能恢复“应用”。隐藏控件不进入键盘焦点环。
- 制谱设置同样隐藏不适用的分界音及逐轨谱表下拉框。失败自动打开问题汇总：总数、各原因数量、真实音符位置、分页列表。点击问题通过现有 binding 暂停并跳转原曲。完整来源事件、tick、位移与秒数保留在诊断数据，失败不替换旧谱。
- 曲目变化后不再沿用旧谱的轨道范围；迟到的失败归为过期，不在新曲上发布旧错误。

## 两首用户文件的实测结果

下表统计为第一轮量化检查，不意味着其余音符或后续声部／时值排版已经通过。全部源音符仍在原曲中；没有删除、改长音符或声称生成了完整谱面。

| 文件 | 解析音符 | 常规节奏 | 含八分三连音 | 完整转谱 |
| --- | ---: | --- | --- | --- |
| Rush E.mid | 1,842 | 101 项：39 超容差、30 短音塌缩、32 零时值 | 同样 101 项 | 未通过 |
| Hans Zimmer - First Step - Interstellar.mid | 1,205 | 95 项：28 超容差、67 短音塌缩 | 28 项超容差 | 未通过 |

完整文件 SHA-256、两个配置的每项问题与来源位置见 [诊断 JSON](../../../.tmp/pianoscope/validation/reports/custom-midi-diagnostics.json)。分配采用音高 60 以下左手、其余右手，手别不是错误原因。

Interstellar 的首处为第 12 小节 E5，源事件 `t0:e164`、tick 16320–17231。松键向最近网格移动 49/480 拍，超过固定的 1/10 拍（48/480）容差；选择三连音可消除这轮 67 项塌缩，但剩下 28 项仍会阻断。不能通过修改左右手解决。

Rush E 的首个零时值例为 C4 / `t0:e1177`，起音与松键都在 tick 143040。已核对原始 MIDI 事件，并非展示或左右手分配制造的零时值。保留当前“不能静默丢音、零时值阻断”的契约时，需要用户提供修正后的 MIDI，或后续明确扩展并版本化量化／复杂节奏能力，才能继续完整转谱。单纯扩大容差也不能保证可表示所有复合时值及声部。

## 验证证据

- [55 项结构与回归测试](../../../.tmp/pianoscope/validation/reports/library-pytest.xml)：目录 24 首／大小写扩展名／非递归／空目录／1,001 首超限／扫描失败保留／扫描竞态；两首真实文件问题来源和原音符不变；旧曲失败过期，以及原有记谱、导出和音乐测试。
- [28 项 800×600、DPR=2 原生报告](../../../.tmp/pianoscope/validation/reports/library-native-800.json)：真实目录选择器取消；实际播放中列目录不换 PCM 或音频代次；搜索／加载第 24 首／列表跨换曲保留；条件表单／预览与提交／异步预览失效／操作按钮可见；两首真实曲目完整导入、应用音高分手、隔离 worker 报错、真实 binding 暂停／seek，失败保留旧谱及 PCM；原 MIDI 文件 SHA 不变，无 JavaScript 错误。
- [83 项 P0 原生音频回归](../../../.tmp/pianoscope/validation/reports/library-p0-regression.json)：沿用既有完整原生交互与实际设备 A–B、变速、手别、频谱测试。历史 P0 人工未测项仍未补签。
- [45 项跟谱与导出原生回归](../../../.tmp/pianoscope/validation/reports/library-score-regression.json)：真实底图、缩放命中、设备播放高亮、binding seek、变速长音、A–B 循环、实际 PDF／MusicXML 导出及错误恢复通过。未重新扩展记谱范围。
- 原生 CPU 像素截图：[两首曲目的曲库](../../../.tmp/pianoscope/validation/screenshots/library-800.png)、[按轨道](../../../.tmp/pianoscope/validation/screenshots/hands-tracks-800.png)、[按音高](../../../.tmp/pianoscope/validation/screenshots/hands-pitch-800.png)、[Rush E 问题](../../../.tmp/pianoscope/validation/screenshots/rush-e-issues-800.png)、[Interstellar 问题](../../../.tmp/pianoscope/validation/screenshots/interstellar-issues-800.png)。截图只证明布局，交互及音频由上述原生断言验证。

复现：在 `examples/pianoscope` 执行：

```sh
uv run --extra test pytest -q
uv run run.py --library-smoke --cpu --width 800 --height 600 --smoke-report ../../.tmp/pianoscope/validation/reports/library-native-800.json
uv run run.py --smoke --audio-test --cpu --width 800 --height 600 --smoke-report ../../.tmp/pianoscope/validation/reports/library-p0-regression.json
```

`--library-smoke` 需要两首用户 MIDI 仍位于项目目录；它们不复制进发行资源，也不替换为伪造夹具。自动化使用真实 binding 传入已知测试目录，同时原生目录面板实际验证取消；人工点选任意目录、其他平台、文件夹持久化与实时文件监视不在已通过项内。本次未重复 60 秒 FPS 测量，历史 v1.1 已测 ≥30 FPS 结果独立保留。
