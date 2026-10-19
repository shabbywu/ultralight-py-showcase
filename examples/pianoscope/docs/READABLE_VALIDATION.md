# 下载 MIDI 自动整理：交付与验收

本页保留 `readable-v2.0` 的历史规则与测量。当前配置 2 已更新为 `readable-v2.1`，新增节奏简化、调号建议和自动谱号；本次验证范围见 [最新可读性记录](READABILITY_VALIDATION.md)，不将旧性能结果自动算作新版通过。

机器报告、调试截图和批量样本已迁至本地 `.tmp/pianoscope/`，不提交；本文保留验收摘要及原有通过／失败／未测状态。参见 [文件约定](FILE_LAYOUT.md)。

2026-10-18。此扩展落实用户确认的两项选择：保留全部音符、在记谱副本整理成可读节奏；复杂段落仍使用同一份双谱表，允许每谱表最多四声部。原始 MIDI、PCM、PPQN、tempo map 和设备音频时钟保持原契约。

## 实际样本

| 文件 | 源音符 | 最大声部／谱表 | 短音补足 | PDF | 可编辑 MusicXML |
| --- | ---: | ---: | ---: | --- | --- |
| Interstellar | 1,205 | 2 | 0 | [4 页](../../../.tmp/pianoscope/validation/samples/readable/interstellar.pdf) | [MusicXML](../../../.tmp/pianoscope/validation/samples/readable/interstellar.musicxml) |
| Rush E | 1,842 | 3 | 32 | [10 页](../../../.tmp/pianoscope/validation/samples/readable/rush-e.pdf) | [MusicXML](../../../.tmp/pianoscope/validation/samples/readable/rush-e.musicxml) |
| Interstellar-Main-Theme 完整版 | 1,566 | 4 | 0 | [16 页](../../../.tmp/pianoscope/validation/samples/readable/interstellar-main-theme.pdf) | [MusicXML](../../../.tmp/pianoscope/validation/samples/readable/interstellar-main-theme.musicxml) |

使用当前仓库用户文件、全部轨道、音高 60 以下左手／其余右手，从真实 MIDI 生成。不是从网上下载的谱例替代，也没有按文件名选择算法。完整源 ID 集合均有记谱映射，延音链可一对多；零时值和同音重复保留。生成可读记谱不等于降难度：Rush E 原文件含跨多个八度的密集和弦，不承诺适合人类双手演奏或还原出版原谱。

原文件指纹、源索引、整理记录、事件数、页数及作业结果见 [原生 worker 关卡](../../../.tmp/pianoscope/validation/reports/readable-gate.json) 和样本的 `.document.json`／`.layout.json`。之前严格配置的失败结果保留于 [历史验收](CUSTOM_MIDI_VALIDATION.md)，不将错误定位测试当作成功转谱。

## 固定的记谱配置版本 2

界面默认“自动整理（推荐）”，对应 `profile: 2, rhythm: "auto"`。接口不传配置版本仍兼容版本 1；严格直分和八分三连音继续对应旧版本。已有谱面不自动重算，切换设置需要新预览并应用。

1. 所有位置采用有理数四分音符拍。先将音长至少 1/4 拍、距四分之一拍网格不超过 1/16 拍的起音视为可整理的演奏偏移，短音快速经过与精确三连音保留节奏；随后逐拍分析起音，候选细分为 1、2、4、8、16、3、6、12；以最大拟合误差、误差总和、最粗网格的顺序确定，等距向后取整。这里 16 细分表示六十四分音符。
2. 音长独立推导。比较正常释放、95% 和 99% 缩短，以及提前 0／1 个源 tick 松键的候选；拟合误差在两个源 tick 内的候选先视为同等拟合，再按最少记谱符号、与原音长差、较少缩短、精确误差、较少提前量、确定的音长排序，避免为拟合微小误差而选出复杂时值。常用候选覆盖 1/16 和 1/12 拍网格至 8 拍，长音仅在原音长附近增加有界候选。
3. 零时值只在谱面补为 1/16 拍，明确计入短音补足。正时值短音不消失；负时值仍拒绝。推导记录保留原音长、推导音长、释放比例、提前 tick、拟合误差、网格与规则版本 `readable-v2.0`。零时值、拟合误差大于两个源 tick 的音符，以及为衔接下一起音而补足无法表示的微小休止（小于 1/16 拍）的音符标记待检查，不能据此声称作者使用了某种演奏法。
4. 使用完整音符／休止时值分解，覆盖六十四分音符及三十二分三连音；保留附点、逐层连梁、完整连音组和跨拍／小节延音。每谱表最多四个独立声部，同起点同音长的不同音高合成和弦，同音重复保留独立声部及来源。出现声部拥挤时，按起音和弦组重新分配，将不同松键时间切成和弦段并以来源音符的延音链连接；优先空闲声部，必要时合并不冲突的节奏段，同时检查休止／片段可表示性。不会把不同音长改成相同时值。真正的同音重叠或无法表示的混合节奏超出四声部时仍明确报错。
5. MusicXML 使用精确整数 divisions，两个谱表的声部编号互不冲突。全部源速度事件以精确 `sound`／`offset` 保存；密集速度变化在谱面按小节显示数值范围，避免逐条印刷成垂直堆叠。原始 tempo map 和节内速度锚点完整保留，显示数字最多两位小数。
6. 高亮只使用 DAC 时钟的原始起音／松键区间。零时值补出的符头不会获得虚构的发声时长；延音链中间分界仍经源 tempo map 换算并钳制到原始区间。

范围继续受 5,000 个源音符、256 小节、32 页、单页 2,000 个记谱符号、worker 512 MiB／60 秒及作业文件／底图各 128 MiB 限制。长谱 PNG 在 2× 以下按 0.25 阶梯选择满足预算的比例，比例随布局传给 Canvas；PDF 始终保留矢量路径。可见谱行才分配完整 Canvas，离屏释放到 1×1；CPU Canvas 按 CSS 像素绘制，GPU 保留最高 DPR=2。小节定位缓存原 tempo map，避免每次轮询重建。

## 验证记录

- [69 项结构与既有回归测试](../../../.tmp/pianoscope/validation/reports/readable-pytest.xml)：包含完整三首文件的来源守恒与确定性、95%／99% 释放候选、一个 tick 偏差、精确音长、零时值、六十四分音符／十六分三连音、四声部与第五声部拒绝、十音和弦共用一个声部、独立 XML 声部编号、变速长音分界、PCM 不变、弱起、曲尾补充，以及原有取消／过期／原子导出测试。最后一次完整运行 69 通过，用时 13.71 秒；后续按用户要求只做受影响范围的定向验证。
- [worker 关卡](../../../.tmp/pianoscope/validation/reports/readable-gate.json)：通过生产隔离进程完成全曲排版、预览、应用和原子 PDF／MusicXML 导出。所有源 ID、记谱事件与真实字形几何守恒。自动整理谱行超出可打印区域会阻断发布，不能交付裁切谱面。
- [music21 独立结构比对](../../../.tmp/pianoscope/validation/reports/readable-independent.json)：逐项检查全部音符／休止的音高、时值、谱表、声部、小节与偏移，并重新导出可编辑 MusicXML；PDF 页面实测 A4。
- [800×600 原生 CPU 验收](../../../.tmp/pianoscope/validation/reports/readable-native-800.json)：95 项通过，DPR=2，三首各连续播放 60 秒；验证真实 DAC 高亮、0.5×／0.75×／1× 试听（见下方缓冲限制）、三种缩放命中、手别／轨道试听、十次循环、播放中生成、原子导出、取消与失败恢复。最低／平均 FPS 分别为 Interstellar 30.97／38.21、Rush E 35.00／38.50、完整版 33.43／37.00；三个窗口段均无 underrun，播放时钟持续前进。
- [大窗口 GPU 复测](../../../.tmp/pianoscope/validation/reports/readable-native-1440-first-fps-failure.json)：首曲连续 60 秒平均 42.87 FPS，最低 22.27，未达最低 30 FPS，不能记为通过；该次未继续其余两首。未确定降帧原因，不据此推断音频或算法错误，也不以平均值掩盖低点。
- [严格配置原生回归尝试](../../../.tmp/pianoscope/validation/reports/readable-legacy-regression.json)：循环采样仅观察到 6 次回绕，未达到该检查要求的 10 次，流程在此停止，后续项未执行；保留失败结果，未覆盖旧版成功记录。三首自动整理曲目的十次循环检查已通过，但不据此补签这项严格配置检查。
- music21 已对三首导出逐事件独立读取并重新导出；MuseScore 的既有两首导入记录保留于 [阅读器记录](../../../.tmp/pianoscope/validation/reports/readable-musescore.json)，其后更新的最终文件及完整版未重新做 MuseScore 图形阅读器验收，不宣称该项全部完成。

初次 CPU 连续播放未达标的报告保留于 [优化前记录](../../../.tmp/pianoscope/validation/reports/readable-native-800-before-optimization.json)。该结果不记为通过；后续使用可见画布分配、CPU 绘制比例和定位缓存后，通过上述 800×600 验收。高亮试听过滤现与绘制使用同一份设备时钟快照，避免配置切换时混用旧手别状态。截图或静态导出不能替代音频与交互验收。

真实原生截图：[预览](../../../.tmp/pianoscope/validation/screenshots/interstellar-readable-preview-800.png)、[Rush E 播放](../../../.tmp/pianoscope/validation/screenshots/rush-e-readable-playing-800.png)、[完整版播放](../../../.tmp/pianoscope/validation/screenshots/interstellar-main-theme-readable-playing-800.png)。PDF 已逐页渲染检查分页、中文说明、页码与谱行边界；密集演奏 MIDI 仍会产生繁多休止和延音线，不把版面完整等同于出版级编配质量。

## 声部、手别与可弹奏性

一个声部可以包含多音和弦，四声部不等于四个琴键，也不能由十个手指推断十声部一定可弹。按中央 C 分手只是初分；交叉手和低音旋律可能被分到同一谱表。按已确认手别建议谱表时，手别分错会增加拥挤；按音高／轨道独立分配谱表不会重写手别。新版先修正音长分组高估声部的问题，不把分手或单纯提高上限作为唯一补救。按用户最后确认，不为完整版 Interstellar 或任何文件添加专用分手规则；三份文件只作为通用算法的真实输入。

## 复现与保留限制

```sh
# 日常：按修改范围选择测试，不重复全量或长时播放
uv run --extra test pytest tests/test_readable.py -q -k 'chord or zero_fill'
# 需要原生复核时可仅选择受影响曲目，默认不测长时性能
uv run run.py --readable-smoke --readable-song rush-e --cpu --width 800 --height 600 --smoke-report ../../.tmp/pianoscope/validation/reports/readable-targeted.json
```

完整结构、三曲 worker、跨尺寸与 60 秒性能流程仍可显式运行，留待相关底层改动或发布验收；本次已停止追加这些完整复测。完整三曲命令为 `run.py --readable-smoke`，性能另加 `--measure-seconds 60`。`--capture-prefix` 可保留旧截图。

需要项目内三首用户 MIDI；不把它们复制进演示或发行资源。Python 3.10+、ultralight-py 0.5.0、AppCore、真实 `API("piano")` 和原音频内核保持；没有新增运行依赖，music21／PyMuPDF／MuseScore 仅用于验证。许可与精确版本沿用 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) 和 uv.lock。

完整版在 48 kHz、0.5× 下预计需要约 206.6 MiB 单版本 PCM，超过原有 192 MiB 限制；因此本次该曲的原生变速长音只验证 0.75×／1×。没有扩大音频预算或假装 0.5× 已通过；两首较短文件均验证三档速度。

本次不扩展 P2、实时输入、麦克风、外部 MusicXML 导入、完整编辑器或发行打包。纸质打印、人耳音质、声画端到端延迟及其他操作系统仍未测；P0 历史人工项目继续单独记录，不因新版通过而补签。
