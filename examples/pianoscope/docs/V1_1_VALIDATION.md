# PianoScope v1.1 实施与验收

本页保留初版 P1 的验收范围与测量；后续自动整理配置见 [版本 2 历史记录](READABLE_VALIDATION.md)，当前节奏、调号和谱号调整见 [readable-v2.1 定向验收](READABILITY_VALIDATION.md)。后续通过项不补签 P0 或未重测的性能项目。

机器报告、调试截图和批量样本已迁至本地 `.tmp/pianoscope/`，不提交；本文保留验收摘要及原有通过／失败／未测状态。参见 [文件约定](FILE_LAYOUT.md)。

日期：2026-10-18。新增基准为根目录 v1.1 HTML（含 02A 状态与布局约束）。P1-A／P1-B 已实施；P2、实时输入、麦克风、外部 MusicXML 导入、完整制谱编辑器与发行打包未开发。按本轮用户明确调整，帧率目标为 **30 FPS 以上**，替代原 60 FPS 目标。工作区另有 600 秒解析上限调整，本轮保留并把旧超时夹具改为 601 秒；600 秒边界单测通过，长曲实际播放／性能不在本轮已验证样本中，仍受 192 MiB PCM 预算约束。P0 历史未测项继续保存在 [VALIDATION.md](VALIDATION.md)，不因本版完成而自动通过。

## 环境与技术决策

macOS 27.0.1 / Apple Silicon，CPython 3.10.20，ultralight-py 0.5.0；实际 MacBook Air 扬声器、48 kHz、双声道 float32。Verovio 5.6.0-85e7620 原生 wheel、CairoSVG 2.8.2、Cairo 1.18.4、pypdf 6.12.2、fonttools 4.63.0、psutil 7.2.2。精确依赖及哈希见 uv.lock；本机资源、体积及许可见 [清单](../../../.tmp/pianoscope/validation/reports/v11-dependencies.json) 与 [第三方说明](../THIRD_PARTY_NOTICES.md)。music21 9.9.1、PyMuPDF 1.27.2.3 仅安装在验证 extra；MuseScore Studio 4.6.5 仅作为独立验证工具。

原生排版路线为独立有理数记谱模型 → MusicXML → Verovio Python → SVG 字形及几何 → CairoSVG PNG → 本地 Canvas 2D。相同 SVG 输出黑白 PDF，再由 pypdf 合并。MusicXML 是同一已应用语义版本；导出不读试听速度、静音或单手过滤。AppCore、本地资源、`API("piano")`、原音频内核均保留，没有 HTTP、WebSocket、CDN、Node.js 或浏览器运行要求。

排版独立子进程中，主线程只校验并发布完整版本。源码帧循环不调用排版；音频回调不调用记谱代码。前端跟谱仅使用既有 transport 中的 DAC 源秒和 active_note_ids，不累计独立播放时间。Python 从原始 tempo map 提供小节／拍，几何锚点包含事件、拍点和节内速度变化；每个延音段边界由记谱 tick 经原曲 tempo map 积分，不按总秒数等分。

## G0 与里程碑

| 阶段 | 实际交付与证据 | 状态 |
| --- | --- | --- |
| G0 / M0 | [真实原生关卡](../../../.tmp/pianoscope/validation/reports/g0.json)：原创 MIDI、双谱表、和弦、休止、跨小节延音、ID 穿透、Canvas 底图、实际设备高亮、暂停、三档缩放 binding seek；[两页 PDF](../../../.tmp/pianoscope/validation/samples/g0/score.pdf)／[MusicXML](../../../.tmp/pianoscope/validation/samples/g0/score.musicxml)／[原生截图](../../../.tmp/pianoscope/validation/screenshots/v11-g0-native.png) | 通过 |
| M0 P0 基线 | [30 项旧测试基线](../../../.tmp/pianoscope/validation/reports/v11-p0-baseline.xml)、[60 秒 GPU 基线](../../../.tmp/pianoscope/validation/reports/v11-p0-gpu.json)、[800×600 基线](../../../.tmp/pianoscope/validation/reports/v11-p0-800.json) | 自动基线通过；旧人工项目未补签 |
| M1 | 原始 tick、PPQN、调号、CC64、指纹与源事件位置；实际 PCM 对比测试证明 CC64 留档不重复合成 | 通过 |
| M2 | 确定性量化、谱表独立于手别、至多两声部、完整小节休止、附点／三连音、延音链、元数据与弱起；[结构测试](../../../.tmp/pianoscope/validation/reports/v11-pytest.xml) | 通过 |
| M3 | 预览／原子应用、状态与错误、原生保存、原子导出、取消／过期／换曲隔离；独立读写／渲染 | 通过 |
| M4 | 同谱高亮、尾音轮廓、非匀距小节游标、手动浏览／恢复、点击、变速／筛选／循环 | 通过原生自动验收 |
| M5 | 三尺寸 DPR=2、缩放命中、60 秒 CPU／GPU、真实截图、打印与互通样本、中文文档与许可 | 自动与屏幕视觉检查通过；纸质打印／声画端到端仍未测 |

G0 中曾实际遇到并修复：Cairo 的 Homebrew 库自动定位失败、主进程混载原生图形库不稳定、早于页面加载的绑定检查冲突、system bbox 只含连接线、网页字体在 CairoSVG 中缺失速度音符、PDF 像素单位误作点单位。最终使用独立 worker、子元素几何合并、音乐／中文文字转路径，以及明确 96 dpi 的 A4 转换；未用静态假谱或第二播放器替代。PDF 每页实测为 595.2756 × 841.8898 pt。

## 固定规则与能力边界

记谱配置版本 1，四分音符为一拍。常规配置网格 1/4 拍；三连音配置使用 1/4 与 1/3 拍网格并集。起音／松键独立就近取整，等距取较晚点；最大端点偏移为 **1/10 拍，含边界**。短音塌缩、负／零时值、超容差及无法分解的网格残差阻断生成，返回具体源音符和小节。不会为了和弦统一时值，也不会去重同音重叠事件。

无弱起从 tick 0 起算，首部空白写休止；用户确认弱起长度，必须小于完整小节且符合网格；末小节补休止。支持 2/4、3/4、4/4、6/8 及边界变拍，中途变拍明确拒绝。调号／速度保留源值和来源，缺失值需确认；不自动宣称默认无升降号代表真实 C 大调。

源范围的每个音符都有来源映射。源索引保留音高、轨道、手别、起止 tick／源秒、原轨道事件位置，跨加载由文件指纹与事件位置追溯。延音拆分不会制造新起音；踏板尾音不改变记谱松键时长。MusicXML note ID 保留记谱事件标识，miscellaneous-field 附来源索引、PPQN、元数据和记谱修订。

制谱范围限制为 5,000 源音符、256 小节、每谱表 2 声部、最多 32 页，另受 PNG 解码与作业文件各 128 MiB、worker RSS 512 MiB、60 秒时限约束。音符分页和几何按页读取，单页最多 2,000 个记谱符号，量化提示每次最多 100 条。超限明确报错，原曲与旧谱保留。

## 作业与恢复

预览依赖指纹、当前加载身份与手别来源；普通试听 revision 不使其失效。只有最新、源依赖匹配、成功完成的预览可应用。应用仅替换完整 document／layout 引用。PNG、PDF、MusicXML 与映射均准备完才发布；前端也等所有页图加载成功才替换可见谱面。

导出保存 token 绑定已应用对象、格式与源依赖；原生保存窗口返回后再次验证。开始后持有不可变快照，即使换曲也只能输出明确标识的原版本。临时文件在目标目录写入并 fsync 后，持锁检查取消，再 os.replace。发布前取消不碰旧文件；发布后返回 completed，不误报取消。预览、导出和音频使用独立作业状态，不用一个全局 busy 阻断播放。

实际 binding：`begin_notation`、`get_notation_job`、`cancel_notation_job`、`get_notation_preview`、`apply_notation`、`get_notation`、`get_notation_page`、`get_notation_warnings`、`choose_score_export`、`begin_score_export`。谱面缩放复用已准备几何与底图，打印布局固定 A4；接口草案中的重排作业名未照搬。资源 token 只允许本作业的已发布 PNG，不开放任意文件读取。

## 新增验收逐项记录

| ID | 证据与结论 | 状态／限制 |
| --- | --- | --- |
| AC-N01 | 单音、和弦、双声部、完全同音重叠；唯一源 ID 与音高集合逐一守恒，所有成功源都有映射；P0 原生同键双手继续回归 | 通过 |
| AC-N02 | 附点、八分三连音、跨拍／跨小节延音成对、每声部小节时值完整，弱起／尾休止显式测试 | 通过 |
| AC-N03 | 常见拍号、边界变拍、节内变速、调号变化与临时记号；[边界谱](samples/v11/edge-phrase.pdf) | 通过 |
| AC-N04 | 超两声部、塌缩、零音长、超容差、非支持拍号、复合残差；错误带位置，不发布错误谱 | 通过 |
| AC-N05 | [独立 music21 比对](../../../.tmp/pianoscope/validation/reports/v11-independent-exports.json)逐个比较音高、时长、谱表、声部、小节与拍内位置；PDF 与 XML 锁定同一版本 | 通过 |
| AC-N06 | 初光两页、中文标题、A0／C8 极端加线、密集双声部，全部 PDF 页面渲染检查；[MuseScore 独立导入](../../../.tmp/pianoscope/validation/reports/v11-musescore.json)并输出两页 PDF／可编辑 MSCZ | 通过屏幕读谱；实物打印未测 |
| AC-N07 | 保存取消原生通过；覆盖、磁盘失败、锁内取消、提交后取消、迟到结果、换曲前后快照测试；旧文件逐字节保持 | 通过；覆盖确认按钮的人工操作未复核 |
| AC-F01 | active IDs 与各段源区间共同高亮；踏板尾音轮廓、暂停清除，静音／单手排除 | 通过自动与截图检查；物理音画差未测 |
| AC-F02 | 0.5／0.75／1× 保留谱面，实际设备至少十次循环、pause／stop／seek | 通过 |
| AC-F03 | 100／125／150% 缩放、DPR=2、真实符头与后段延音经 binding seek，几何往返误差 ≤1 CSS px，另有真实休止／小节点击检查 | 通过；触屏物理点按未测 |
| AC-F04 | 滚轮／手动滚动不抢回视图，恢复自动跟随保持 clock_epoch | 通过 |
| AC-F05 | [800×600 连续播放](../../../.tmp/pianoscope/validation/reports/v11-score-800.json)、[最终交互与模态检查](../../../.tmp/pianoscope/validation/reports/v11-score-800-interactions.json)、[1000×720](../../../.tmp/pianoscope/validation/reports/v11-score-1000.json)、[1440×747 实际高度](../../../.tmp/pianoscope/validation/reports/v11-score-1440.json)，实际 DPR=2，谱行与传输可见 | 通过本机；其他 DPI／平台未测 |
| AC-F06 | playing 时切下落／五线谱、键盘与侧栏；generation／clock_epoch／rate／loop 不变，缩放复用缓存 | 通过 |
| AC-P01 | 初次制谱、暖缓存、60 秒 CPU／GPU、FPS 样本、进程 CPU、峰值 RSS、设备 underrun，见下表及 JSON | 通过本机 30 FPS 目标 |
| AC-P02 | 保留 P0 独立基线与旧人工债务；本轮仅把帧率目标按用户授权调整为 30 FPS 以上 | 自动回归通过；旧未测项保持未测 |
| AC-N08 | 首部休止、弱起、尾补齐、空曲、容差边界两侧、等距决胜、重复生成稳定 | 通过 |
| AC-F07 | 持续 A0 长音内三档变速，tempo 变化后跨小节分界确为 2.1 源秒；延音后段点击、循环内外跳转保留意图 | 通过实际设备与 binding |
| AC-N09 | 播放中生成不换 PCM；实际手别修改后过期；保存 token 跨换曲拒绝；已启动导出只完成原快照 | 通过；保存模态框内换曲由事务测试覆盖 |
| AC-D01 | 中文 README、依赖／许可、真实原生截图、两格式样本、逐项记录；未使用设计稿充当证据 | 通过 |

结构／数学测试共 **49 项通过**（原有 30 项＋新增 19 项），见 [pytest XML](../../../.tmp/pianoscope/validation/reports/v11-pytest.xml)。原生测试是真正 AppCore 窗口、真实绑定和实际扬声器设备，不以截图证明设备音频。独立 reader 的 PDF、MSCZ 与原始日志都保留，最终 MuseScore 4.6.5 三个转换全部退出码 0；4.7.5 在本机发生退出阶段 mutex 异常，失败日志 `musescore-4.7.5-exit-failure.log` 保留，不计为通过。验证工具改用 4.6.5（官方 DMG SHA-256：`89624d9e6618bd7fd224b226e63e83722b9124bc2c466206b01762375c69d4ad`）。不要求产品用户安装该软件。

## 性能与原生截图

以下为本机单次测量，不是多机统计；FPS 样本直接来自实际 requestAnimationFrame。CPU 占用口径为进程 CPU 时间／墙钟时间；峰值 RSS 包含 AppCore、字体、图形、音源、PCM 与准备数据，不是 PCM 大小。CPU 原生报告还包含像素读回检查的临时数组，不能视为产品稳态驻留。后续报告更新以原始 JSON 为准。

| 工作负载 | 实际视口 | FPS 最低／平均 | 进程 CPU | 峰值 RSS | underrun |
| --- | --- | --- | --- | --- | --- |
| P0 新版前 GPU 基线，连续 60 秒 | 1440×747 / DPR=2 | 见 [基线 JSON](../../../.tmp/pianoscope/validation/reports/v11-p0-gpu.json) | 28.54% | 744,636,416 B | 0 |
| P1 五线谱 GPU，连续 ≥60 秒 | 1440×747 / DPR=2 | 35.0 / 49.4 | 33.29% | 757,972,992 B | 0 |
| P1 五线谱 CPU，连续 ≥60 秒 | 800×600 / DPR=2 | 34.0 / 37.8 | 50.44% | 1,143,586,816 B | 0 |

初次“初光”制谱及显示约 3 秒，暖缓存约 8 ms；精确值分别保存在各原生报告的 first_notation_seconds／warm_notation_seconds，包含当次 IPC、图片加载及可见性等待。暖缓存使用不可变语义、几何、PNG 与 PDF，不重新启动原生排版进程。

[800×600 原生播放](screenshots/v11-score-800.png) · [待应用预览](../../../.tmp/pianoscope/validation/screenshots/v11-preview-800.png) · [制谱设置](../../../.tmp/pianoscope/validation/screenshots/v11-settings-800.png) · [PDF 导出检查](../../../.tmp/pianoscope/validation/screenshots/v11-export-pdf-800.png) · [MusicXML 导出检查](../../../.tmp/pianoscope/validation/screenshots/v11-export-musicxml-800.png) · [1000×720 原生播放](../../../.tmp/pianoscope/validation/screenshots/v11-score-1000.png) · [1440×实际可用高度原生播放](../../../.tmp/pianoscope/validation/screenshots/v11-score-1440.png)。图片均由真实 CPU View.copy_pixels 采集；GPU 不支持同样的像素读取，因此 GPU 音频／交互与 CPU 像素证据分别报告。

## 未测与保留范围

未进行声学 loopback／高速屏录端到端音画差、人工耳听的爆音与音色、物理设备拔插、纸质打印、其他操作系统与 DPI、完整人工可访问性测试；均不标通过。原 P0 的这些遗留项继续在原记录中独立跟踪。CPU 下落视图旧记录约 27.5 FPS，不能用本版五线谱 CPU 达标自动覆盖；新版下落视图的 [单独 P0 有声回归](../../../.tmp/pianoscope/validation/reports/v11-p0-regression-audio.json) 83 项断言通过，0.5 秒循环实测末段约 34.4 FPS、11 次回绕、underrun=0；该短循环不能替代旧项目的 60 秒 CPU 下落视图测量。

MIDI 转谱是有限规则的练习谱；自由速度、超过两声部、超细复合节奏、非支持变拍仍可能被明确拒绝。屏幕缩放重用打印谱行，放大后可横向浏览，不是任意纸张重排或完整制谱编辑器。输出保留可编辑 MusicXML，外部软件继续编辑后的文件不在本轮导入范围。

独立制谱软件复核命令（可选，仅供开发验收）：

```sh
python tools/check_musescore.py --executable '/path/to/MuseScore 4.app/Contents/MacOS/mscore'
```

脚本在独立转换进程中读取真实导出文件，核对退出码、PDF 页数、MSCZ 内的可编辑 MSCX，并记录源文件 SHA-256；不会使用旧文件存在作为通过条件。`tools/validate_score_outputs.py` 另外比对 MusicXML 的每个音高、时长、谱表、声部、小节和拍内偏移。


## 自定义 MIDI 后续反馈

文件夹曲目列表、条件分配表单与真实曲目问题定位的后续实现和验证，单独记录于 [CUSTOM_MIDI_VALIDATION.md](CUSTOM_MIDI_VALIDATION.md)。本页的原 v1.1 / P0 历史报告保留，不以这次交互修复补签历史人工项目，也不将两首受限曲目的报错测试记作成功转谱。


## 下载 MIDI 自动整理后续交付

本页固定规则与历史报告对应严格记谱配置版本 1。用户后续明确授权版本 2 的记谱整理及四声部扩展；两首实际全曲输出与新验收单独见 [READABLE_VALIDATION.md](READABLE_VALIDATION.md)，不改写本页原通过／未测历史。
