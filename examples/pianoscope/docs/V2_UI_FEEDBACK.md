# v2 界面反馈修正 · 2026-10-19

MusicXML 迁移需要更换来源与播放逻辑，不需要同时重做视觉。此前将两者绑定实施，带来了不必要的界面回退。本次恢复 v1.1 的深绿／金色、侧栏、暗色阅读谱面、当前音符和独立播放面板，保留已经完成的 MusicXML 模型及真实 DAC 播放。打印 PDF 不随阅读配色改变。

互斥选择统一为「五线谱｜下落音符」式的分段按钮，当前值高亮，支持左右方向键和焦点：速度、缩放、反复遍次、键盘范围、左右手、谱表试听。页面与动态表单中没有原生 select 或原生 radio。

“试听范围”只有「全部｜上谱表｜下谱表｜静音」及折叠的声部筛选，显示实际已应用状态，取消不修改声音。“左右手设置”独立显示上／下谱表和音符数，修改时自动给出分配预览，一次确认生效；可撤销。已有逐音符混合分配显示“保留逐音符分配”，不被默认建议覆盖。原件、谱面和默认 MIDI 不变。修复撤销全部分配后仍残留 left/right 过滤的问题：现在恢复 both，同时保留谱表／声部范围。

播放按钮使用独立、固定 42×38 CSS px 的控件组，声音概览负责定位；兼容状态用的 seek input 隐藏，不与按钮并排或覆盖。可选键盘／频谱挤占空间时，阅读区独立滚动，播放面板保持可达。底图按 DPR 缓存以保留清晰度，静态声音概览也缓存，避免每帧重复绘制 1,400 条线。

原问题的复现边界：本机旧界面的 800×600／大窗口中，按钮九点的 View 鼠标与 AppKit NSEvent 路径都能触发，未稳定重现用户报告的“仅左侧能点”；没有把一个未捕获的遮挡元素冒称为根因。新版已对实际命中与状态变化做原生回归，不能仅凭 `.click()` 或直接调用 piano.play() 代替命中测试。

| 检查 | 实测结果 |
| --- | --- |
| 原生小窗口 | [60 项通过](../../../.tmp/pianoscope/v2/ui-20261019-204011/report.json)，CSS 800×600、DPR=2、readback 1600×1200；九点 View 输入、九点 AppKit 输入；展开键盘／频谱／循环时的左中右位置命中并真实播放 |
| 原生大窗口 | [61 项通过](../../../.tmp/pianoscope/v2/ui-20261019-204133/report.json)，请求 1440×900，受屏幕可用高度限制，实际 CSS **1440×753**、DPR=2；同样的实际鼠标／表单检查，另含 native key_down/up 切换分段选项 |
| 原生 GPU 大窗口 | [62 项通过](../../../.tmp/pianoscope/v2/ui-20261019-204510/report.json)，实际 CSS **1440×750**、DPR=2；相同原生鼠标／表单检查，10 秒最低 **41 FPS**。截图采自 CPU；GPU 记录交互与帧率 |
| 表单事务 | [16 passed](../../../.tmp/pianoscope/v2/ui-practice-transactions-attempt-2.xml)；范围包含空选择，重开保持范围／声部，预览不改 PCM，撤销恢复双手，来源／布局／MIDI 一致 |
| 混合标签 | [1 passed](../../../.tmp/pianoscope/v2/ui-mixed-labels.xml)；只更改下谱表时，上谱表既有逐音符左右手保持 |
| 小窗口播放定向性能 | 真实设备下 10 秒，完整不重叠 1 秒窗口为 30、32、33、34、31、33、32、32、31、33 FPS，最低 **30**；不是一次新的 60 秒发布矩阵 |
| 视觉检查 | 查看实际原生底图及两张表单截图，谱号／符头、当前控件、操作区完整，无原生下拉；[800 窗口](screenshots/v2-score-restored-800.png)、[大窗口](screenshots/v2-score-restored-1440.png)、[试听范围](screenshots/v2-audition-800.png)、[左右手](screenshots/v2-hands-800.png) |

实际原生检查包括：按钮全区域播放、速度合成、缩放、重开范围与声部、取消不换 PCM、建议不冒充确认、确认与撤销、真实单手可听实例、开关可选面板后的命中、源谱／布局／MIDI 守恒、没有 JavaScript 错误。使用本地原创 MusicXML、固定 0.5.0、实际音源与设备，未引入浏览器、网络播放器或前端播放时钟。PDF 和源编译路径未修改。

失败尝试保留：最初新增撤销断言暴露了只替换 PCM 而未安装新 config 的问题，修正后事务通过；UI 驱动曾错误地在侧栏已遮住菜单时继续点菜单，以及字符串转义错误，报告保留为脚本失败；ui-20261019-203827 中短时最低 29 FPS，缓存静态概览和减少重复 DOM 更新后以 ui-20261019-204011 复测通过。没有把失败计为通过或覆盖原文件。

未测限制：本轮没有重复首轮 M5 的 60 秒 CPU/GPU 矩阵，没有把旧 FPS 写成新 UI 的长时性能；原始单侧点击问题的特定触发条件仍未捕获。其他平台、所有缩放／外接屏切换、人工听感、物理声画与拔插等保持未测。v1.1 历史文件与旧 M5 机器报告不改写。

从 examples/pianoscope 执行定向原生检查，每次产生根 .tmp/pianoscope/v2 下新的 ui-* 目录：

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/v2_ui_gate.py --measure-seconds 10
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/v2_ui_gate.py --width 1440 --height 900
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/v2_ui_gate.py --gpu --width 1440 --height 900 --measure-seconds 10
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_v2_transactions.py -q
```
