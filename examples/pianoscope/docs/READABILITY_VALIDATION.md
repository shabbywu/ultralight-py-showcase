# 节奏可读性、调号与谱号验收

2026-10-19，自动整理配置 2，规则 `readable-v2.1`。本轮实现常规节奏优先、和弦起点归并、休止／延音整理、调号建议与按音域选择谱号／八度记号。算法不按文件名分支；严格配置 1 保持兼容，旧谱需重新生成预览并应用。原始演奏、PCM 和设备音频时钟保持原契约，P2 继续仅规划。

## 实际输入与结果

输入为本地用户文件 `.tmp/pianoscope/midi/Interstellar-Main-Theme-Left-Right-Hand.mid`，SHA-256 为 `c6bdcf6d55fd037451219426392423b418a666029478dab85d144caab992d19a`。PPQN=384，1,566 个源音符，原速度 120 BPM、4/4。右手轨 `t0c0` 的 689 个音符放上谱表，左手轨 `t1c1` 的 877 个音符放下谱表；没有使用中央 C 分谱。文件未提供调号事件，原解析器的 C 是缺省值。

前后比较使用相同源文件与谱表分配，旧规则为 `readable-v2.0`。事件数包括和弦的各符头与休止；三连音按记谱片段计数，延音连接按 `tie_start` 计数，不是源起音数。

| 项目 | 旧规则 | 本次规则 |
| --- | ---: | ---: |
| 源音符 | 1,566 | 1,566 |
| 记谱事件 | 5,401 | 3,809 |
| 休止 | 2,841 | 1,911 |
| 三连音片段 | 905 | 0 |
| 延音连接 | 994 | 332 |
| 第 36 小节事件 | 47 | 32 |
| 第 36 小节三连音片段 | 15 | 0 |

本次实际导出 **10 页 A4 PDF** 和同版本可编辑 MusicXML。旧版只生成对照模型和 XML，没有以旧版 PDF 页数作为测量结果。详细比较见 [JSON](../../../.tmp/pianoscope/validation/reports/readability-comparison.json)。

## 规则与可审阅信息

先按十六分音符网格整理起点，合并接近的长音和弦。不会合并同轨同音的重复起音；规则快速音列和真实短音保留更细网格。三连音需要连续起音的局部证据，不以单个微小偏差触发。真实四分三连音、十六分三连音、六十四分重复音及混合伴奏都有定向用例。

音长推导仅作用于记谱副本。常规时值优先，普通跨拍音符可保持完整，休止避免不必要附点；整小节休止采用专用符号，完全空闲的多余声部不打印重复休止。跨小节、和弦部分松键以及真实节奏需要的延音仍保留。本文件 1,561 个源音符采用默认十六分起点网格，其余 5 个采用更细网格；仍有 **39 个待检查项**，不会用符号变少掩盖整理偏移。

模型保留原始 tick、PPQN、tempo map、调号来源、源 ID、推导规则、网格、起点／松键偏差和释放候选。所有源音符都有完整记谱链；高亮仍按原始源区间，延音段分界由原曲 tempo map 换算。零时值补足不虚构音频发声区间，超出范围仍明确拒绝。

调号由所选音符的时值加权音级分布与大小调模板相关性给出，需用户复核，可选原调号或手动覆盖。本文件建议 **B 大调**（相关系数 0.786745），同时提示关系小调 **G♯ 小调**；相关系数不是准确率。两者同为五个升号，不能据此保证作者选择的主音或还原出版原谱。没有实现自动转调分析。

谱号按各小节实际音域规划，使用加线代价、切换代价和延音保护，避免逐音来回切换。可选“自动（含八度记号）”“自动高低音谱号”或固定传统高低音谱号。本文件上谱表起始为低音谱号，第 58、66、110 小节依次改为高音、低音、高音；下谱表为低音谱号配低八度记号。MusicXML 使用真正的 `octave-shift`，音符仍保留实际发声音高，独立读取器没有八度漂移。

## 本轮验证证据

| 检查 | 本轮结果 |
| --- | --- |
| [定向结构测试](../../../.tmp/pianoscope/validation/reports/readability-targeted.xml) | 21 通过，3 个其他完整下载文件用例未运行；2.32 秒。覆盖和弦偏移、真假三连音、快速重复、休止简化、来源守恒、手动调号、谱号稳定和八度实际音高 |
| [真实 AppCore 原生检查](../../../.tmp/pianoscope/validation/reports/readability-native.json) | 800×600、DPR=2，实际 MacBook Air 扬声器；14 项断言通过。真实 binding 制谱／应用、播放中生成保留 PCM、第 36 小节符头命中与 seek、设备时钟高亮、两格式原子导出、源数据不变、无 JS 错误 |
| [独立 music21 9.9.1 读取](../../../.tmp/pianoscope/validation/reports/readability-independent.json) | 3,809 个事件的音高、时长、谱表、声部、小节和偏移逐项一致；重新输出可编辑 XML；10 页纸张均为 A4 |
| 排版人工查看 | PDF 第 1、3、4 页已渲染查看，涵盖起始低音谱号／八度、包含第 36 小节的页面及第 58 小节谱号切换；未声称逐页人工检查全部 10 页 |

原生截图：[设置](../../../.tmp/pianoscope/validation/screenshots/readability-settings-800.png)、[第 36 小节跟谱](../../../.tmp/pianoscope/validation/screenshots/readability-measure-36-800.png)。截图只证明可见界面；音频和交互结论来自真实设备状态、源区间与绑定断言。

产物：[PDF](../../../.tmp/pianoscope/validation/samples/readability/after.pdf)、[MusicXML](../../../.tmp/pianoscope/validation/samples/readability/after.musicxml)、[记谱模型](../../../.tmp/pianoscope/validation/samples/readability/after.document.json)、[几何与映射](../../../.tmp/pianoscope/validation/samples/readability/after.layout.json)。个人 MIDI、批量产物、截图和机器报告均在忽略提交的根 `.tmp/pianoscope/` 内；新克隆不附带这些个人文件。运行依赖和资源版本不变，见 [许可与依赖说明](../THIRD_PARTY_NOTICES.md)。

## 复现和边界

从 `examples/pianoscope` 运行，只选受影响范围：

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_readability.py tests/test_readable.py -k 'not complete_downloaded'
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python run.py --readability-smoke --cpu --width 800 --height 600 --smoke-report ../../.tmp/pianoscope/validation/reports/readability-native.json
```

原生专项流程需要上述本地分轨 MIDI；没有个人文件时，相应 pytest 用例会跳过。用户使用时重启应用，重新生成预览、检查后应用即可，不需要运行验收脚本。

本轮未重跑完整回归、跨尺寸／多缩放矩阵和长时 FPS／循环。30 FPS 目标保持；[旧规则性能记录](READABLE_VALIDATION.md)不自动算作新版性能通过。当前 XML 通过独立结构读取；本次未重做 MuseScore 图形界面导入，也未验证纸质打印、人耳音质、端到端声画延迟或其他平台。P0 旧验收继续在 [VALIDATION.md](VALIDATION.md) 单独记录。

自动整理提高练习谱可读性，不保证恢复作曲者原谱或降低原演奏难度。当前声部／音符／页数和 worker 预算仍有效；关系大小调、自由速度和复杂混合节奏仍可能需要人工判断或在外部制谱软件继续编辑。
