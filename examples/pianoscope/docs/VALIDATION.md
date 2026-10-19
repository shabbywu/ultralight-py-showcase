# PianoScope 实施与验收记录

机器报告、调试截图和批量样本已迁至本地 `.tmp/pianoscope/`，不提交；本文保留验收摘要及原有通过／失败／未测状态。参见 [文件约定](FILE_LAYOUT.md)。

日期：2026-10-18。规格：本地 `.tmp/pianoscope/specs/ultralight_pianoscope_spec.html` v1.0，已完整阅读第 00–15 节。P0 功能已实现并可原生运行；仍有人工项目与性能目标未完成验证，不宣称“全部 P0 验收完成”。本文件保留 P0 历史记录；P1 实施与新增验收见 [v1.1 验收记录](V1_1_VALIDATION.md)。本轮用户已将帧率目标调整为 30 FPS 以上，历史 60 FPS 记载不再作为本轮失败条件；其余未测项目不自动通过。

## 环境与证据

- macOS 27.0.1，Apple Silicon，Python 3.10.20，ultralight-py 0.5.0。
- FluidSynth 2.6.1（`/opt/homebrew/lib/libfluidsynth.dylib`）、PortAudio 19.7.0、sounddevice 0.5.6、Mido 1.3.3、NumPy 2.2.6、PyObjC Cocoa 12.2.2。依赖固定于 pyproject.toml／uv.lock。
- 实际输出：MacBook Air 扬声器，stereo float32，48,000 Hz；设备默认频率虽为 44.1 kHz，但 48 kHz 参数检查与实际流均成功。
- 主窗口请求 1440×960，本机屏幕可用区域使实际 View 为 **1440×747 CSS px，DPR=2**。最小窗口实际 1000×720、DPR=2。未冒充完整 1440×960 工作区的性能测量。
- CPU 与 GPU 都是真实 AppCore 原生窗口；无 HTTP／WebSocket 服务、浏览器或 Node.js 进程。页面资源为本地文件，CSP 禁止 connect，未使用外部字体或 CDN。

| 证据 | 结果与范围 |
| --- | --- |
| [最小闭环](../../../.tmp/pianoscope/validation/reports/minimal-gate.json) | JS → Python async → FluidSynth A4 → 实际扬声器输出完成；非零 PCM 峰值 0.05896；原生选文件窗口打开与取消成功 |
| [Python 测试](../../../.tmp/pianoscope/validation/reports/pytest.xml) | 30 项通过，0 失败；数学与真实 FluidSynth 集成，非 mock 合成 |
| [普通原生冒烟](../../../.tmp/pianoscope/validation/reports/native-offline.json) | CPU AppCore、binding、只读实例、解析、手别、音符选择、几何、错误恢复、真实 View 截图；不要求音频硬件 |
| [有声原生冒烟](../../../.tmp/pianoscope/validation/reports/native-audio.json) | CPU 实际设备输出、循环、音量／暂停分析归零、同键双手、释放尾音、ended／重播；55 项断言通过 |
| [GPU 连续播放](../../../.tmp/pianoscope/validation/reports/native-gpu.json) | 初光双轨连续约 60 秒；实际 GPU 窗口、实际输出设备；断言与性能样本均保存 |
| [最小窗口](../../../.tmp/pianoscope/validation/reports/native-minimum.json) | 1000×720 原生 CPU 冒烟，琴键与播放控件均位于可视区域；两种键盘通过 |
| [文件对话框](../../../.tmp/pianoscope/validation/reports/native-dialog.json) | 原生打开／取消自动通过；人工选择确认仍为 unverified |

普通 smoke 会真实从 JS 调用 pause／seek／stop、配置、预览与分配，并通过设备缺失注入检查拒绝播放／重试。`--audio-test` 才执行真实播放且要求设备。成功进程返回 0，断言／设备失败返回非 0。初始化 ready 只有在 UI 绑定自检成功后设置；持续动画页面使用 0.5.0 的 callable `wait_until` 等候业务状态，不等待动画页面静止。

## 分阶段关卡

1. **原生＋音源最小闭环先行**：先建立 `tools/minimal_gate.py`，实际合成、输出和选文件取消通过后才制作正式 UI。Homebrew 首次提示 Command Line Tools 过旧，但所需瓶装 FluidSynth／PortAudio 最终安装并实测成功，未以假音频绕过原生库。
2. **时间线与曲目**：Type 0/1、逐轨累计 ticks、全局 tempo 分段积分、同 tick 稳定顺序、FIFO、velocity=0、CC64、控制传播、缺失／孤立松键、输入保护通过。两首原创 MIDI、明确手别 sidecar、生成脚本、SoundFont 原始许可与 hash 已保存。
3. **音频内核**：事件时间除以 rate 后重新合成，固定采样率输出；不同轨道／同键重叠使用虚拟通道。独占 synth worker、2048 样本块取消、generation 隔离、发布失败回滚、关闭回收均有测试。已修正完成 Future 保留旧 PCM 的问题；完成任务不再保留 PCM 结果，只保留小型状态。
4. **键盘与手别**：单一 KeyboardLayout；52 白＋36 黑；黑键分组、音域连续、窄音域扩展、中央 C 范围外提示、真实 DOM／Canvas 原点一致通过。外部文件不根据 Left 轨名自动确认；预览、应用、逐音／框选修正、撤销及同键双手真实高亮均原生通过。
5. **完整交互与分析**：真实 PCM min/max 概览、DAC 对应输出窗、Hann／单边幅度校准／128 log bands；数学脉冲与正弦测试通过。音量零和暂停实时图归零，概览保留。A/B 输入与拖动入口、视图／音名／分析开关、焦点快捷键、设备重试已接入。
6. **展示与交付**：中文 README、许可、真实截图、机器报告和展示条目齐备；展示站构建通过本地链接／锚点检查，1280 与 640 宽原生预览无横向溢出，三张项目图均成功加载。条目状态保留“可运行 · 原生自动验收通过”。

## 测量结果与边界

GPU 报告对应“初光”、双轨、1×、实际 1440×747／DPR=2，先完成至少 10 次短循环，再关闭循环连续播放约 60 秒。

| 指标 | 本机记录 |
| --- | --- |
| 生成初光 1× | 约 0.30 s（单次记录，不是统计分位数） |
| GPU FPS | 样本平均约 53.58、最低约 42.00；满足本机 ≥30 可用目标，**未达成持续 60 FPS** |
| GPU 进程 CPU | 约 30.29% 单核占用口径：process_time / wall_time |
| GPU 峰值 RSS | 887,832,576 bytes，含原生引擎、字体、图形、音源和准备任务；不是 PCM 缓存大小 |
| 当前初光 PCM | 34,560,000 bytes；完成任务无旧 PCM 引用，当前与准备版本预算 ≤192 MiB |
| 60 秒 underrun | 0 |
| 输出流 latency | 0.0321875 s，PortAudio 设备估计值 |
| CPU 后备路径 | 约 27.5 FPS（本次末段读数）、约 70% CPU；能运行和截图，**未达到 ≥30 FPS 目标** |
| 端到端音画差 | **未验证**；设备 latency 不等于实测音画差 |
| 控制反馈延迟分布 | **未测量**；不根据代码或 FPS 推断 ≤100 ms |

音频时钟单测明确覆盖“已提交缓冲尚未到达 DAC 时，位置不得前移”；loop 至少 10 次、尾音结束时机、gain 后分析亦有覆盖。原生输出测试证明数据交给实际设备并完成播放，没有人工耳听或 loopback 证据时，不写“音色／爆音验收通过”。

## AC 对照

| 验收项 | 已验证证据 | 尚未验证／限制 |
| --- | --- | --- |
| AC-01 | 两首离线资源、真实 AppCore、安装锁定、无远程资源 | 未在物理断网的新机器重新安装验证 |
| AC-02 | Type 0/1、损坏／空／Type 2／SMPTE／大小／时长／数量／轨道上限拒绝；坏文件保留旧曲；原生窗口取消 | 原生选择合法文件后的人工确认未验证；路径打开合法文件已原生通过 |
| AC-03 | 实际 SoundFont 非零采样、设备输出、pause／stop／ended／replay | 人工耳听未验证 |
| AC-04 | 和弦、踏板 key_off／sustain 分离、暂停清高亮、真实截图 | 人工逐帧音画时差未测 |
| AC-05/06/07 | 88=52+36；A0/C8；黑键锚点；单音／全音域／C4 范围外；1000/1280/1440 数学几何与实际 DOM ≤1 px；DPR=2 | 未验证其他 DPI／操作系统 |
| AC-08 | 真正 playing 时切两种模式 20 次以上，rate／loop 不变，设备无 underrun | 耳听连续性未人工复核 |
| AC-09 | seek 源秒、暂停位置、循环夹取；新 PCM 游标与短淡变；UI 拖动仅释放提交 | 人工长音跳转听感未验证 |
| AC-10 | 0.5/0.75/1 真实合成基频保持；缓冲长度按源秒／rate 映射 | 未宣称任意音源音色完全相同 |
| AC-11 | 真合成 mute／solo／hand 过滤、CC11；共享源通道同 pitch 与独立合成之和一致；范围不随筛选变化 | 无额外平台设备证据 |
| AC-12 | 校验、边界保留、停止不删选区、DAC 十次以上回绕 | A/B 物理鼠标拖动体验需人工复核 |
| AC-13/14 | 脉冲 min/max、已知正弦幅度／频率标定、真实输出波形／频谱、静音／暂停归零、概览保留 | 未做声学麦克风验证 |
| AC-15 | 设备缺失注入拒播；真实输出设备打开／重试；重试不自动播放 | 物理拔插设备恢复未验证 |
| AC-16 | 取消可见响应 <1s、旧任务不覆盖、失败回滚、退出无工作线程、关闭前原生 macOS 通知回收 | 极限负载反复手动关闭未验证 |
| AC-17 | 中文真实截图、Home／输入框箭头焦点、音名／面板切换、1000×720；reduced motion 静态模式已实现 | 完整人工可访问性／键盘操作／系统 reduced motion 复核待做 |
| AC-18 | JS 实际控制 Python、真实 View PNG、成功 0／失败非 0、报告含版本／fixture | GPU View 无 CPU pixels，截图明确来自 CPU View |
| AC-19 | 60 秒、FPS、CPU、RSS、准备时间、latency、underrun 报告 | 60 FPS、CPU ≥30 FPS、反馈延迟与音画偏差目标未全满足／验证 |
| AC-20 | 中文指南、原生依赖、来源许可 hash、真实截图、平台限制、验收记录 | 其他平台未验证 |
| AC-21/22 | 固定 L/R 色、实际单手过滤、同键双手、外部未分配、误导轨名、阈值预览／确认、逐音／框选修正／撤销 | 任意 MIDI 自动分手准确率不作承诺 |
| AC-23 | 原生页面正文与截图检查；没有需求提示、图号、FR/AC/TASK 或 binding／PCM／FFT 工程说明 | 无 |

## 真实截图与复核方式

### 触键时刻与画布边界修正

根据使用反馈补充琴键顶边的“现在 · 按下”线和同色触键标记；音符下缘到线表示按下，上缘到线表示松开。排查中发现 Ultralight 对直接放在 grid 内的 Canvas 百分比高度计算使画布延伸到琴键后方，本机收起频谱时实际偏移 181 CSS px。原先水平对齐检查未覆盖这一问题。现使用占据音符行的独立视口约束 Canvas，绘制的当前时刻与可见琴键顶边一致。

[修正后有声原生报告](../../../.tmp/pianoscope/validation/reports/native-strike-line.json) 包含两种键盘与频谱展开／收起的实际 DOM 检查：画布底边、线中心、琴键顶边偏差均为 0 CSS px；触键标记与亮键水平中心偏差约 0.008 CSS px。真实设备循环播放无 underrun，截图已更新。此处验证的是绘制几何，端到端音画延迟仍需单独测量。

[1000×720 原生复核](../../../.tmp/pianoscope/validation/reports/native-strike-line-minimum.json) 与 [GPU 原生复核](../../../.tmp/pianoscope/validation/reports/native-strike-line-gpu.json) 亦通过上述四种布局检查；小窗口截图和展示站图片已同步更新。展示站重新构建通过本地链接及锚点检查。

### 触键线位置可调

后续根据使用反馈增加“触键线上移”滑块与标签上下拖动，范围为音符区高度的 0–60%，默认 0%。调整共享绘制锚点，触线时刻仍由设备音频时钟决定；通过线后的音符可继续向下离开画面，松键后的音符减淡。上移时琴键顶边改为普通分隔色，避免出现两条金色触键线。切换曲目／键盘与展开频谱保持比例设置。

[可调位置有声原生报告](../../../.tmp/pianoscope/validation/reports/native-adjustable-line.json) 与 [1000×720 报告](../../../.tmp/pianoscope/validation/reports/native-adjustable-line-minimum.json) 检查两种键盘、频谱展开／收起、0／30／60% 共 12 种组合；捕获实际 Canvas 绘制使用的锚点，与可见线比较，偏差不超过 1 CSS px。同时验证拖动上下边界、局部设置保存，以及播放中调整位置和切换模式不改变音频 generation、clock_epoch、rate 或 loop。[上移 30% 的真实播放截图](../../../.tmp/pianoscope/validation/screenshots/pianoscope-adjustable-line.png) 单独保留。

本次有声 CPU 71 项、小窗口 CPU 59 项、[GPU 原生复核](../../../.tmp/pianoscope/validation/reports/native-adjustable-line-gpu.json) 59 项断言全部通过；展示站同步使用可调触键线截图，重新构建通过。

### 小屏布局重新设计

移除独立顶部 header，将品牌与“打开 MIDI”合入原有左侧栏。主区域仍直接显示完整／曲目键盘、音名、静态音符、触键线位置；这些控制没有收进菜单。曲名与元信息使用紧凑工具区，缩减页面边距、概览和播放区高度，优先给下落音符和大键盘分配空间。宽度 ≤1100 px 时侧栏默认收起，通过左上角 ☰ 打开，×／遮罩／Escape 关闭；宽屏亦可收起侧栏。

[800×600 原生报告](../../../.tmp/pianoscope/validation/reports/native-compact-800.json) 中，音符区从屏幕顶部 54 CSS px 开始，高 207 px，琴键高 142 px；主区域无需滚动，无横向溢出。两种键盘、频谱展开／收起时主区域控件保持可见，A–B 输入与分析同时展开也无需滚动。原生检查验证品牌与导入入口所在区域、主区域显示控制、侧栏开关、焦点循环／Escape 返回，以及 12 种触键线布局对齐。

[1000×720 报告](../../../.tmp/pianoscope/validation/reports/native-compact-1000.json) 与 [有声 CPU 报告](../../../.tmp/pianoscope/validation/reports/native-compact-audio.json) 单独保留；有声原生运行继续覆盖真实设备、循环、同键双手、波形与频谱。全部截图重新从实际 View 采集，另保留 [800×600 主界面](../../../.tmp/pianoscope/validation/screenshots/pianoscope-800x600-focused.png) 与 [展开侧栏](../../../.tmp/pianoscope/validation/screenshots/pianoscope-800x600-sidecar.png)。

[有声 GPU 复核](../../../.tmp/pianoscope/validation/reports/native-compact-gpu.json) 同样通过，并新增播放中收起／展开侧栏不改变 generation、clock_epoch、速度或循环的检查；本次实际设备输出无 underrun。展示站截图同步更新，构建通过本地链接与锚点检查。此轮是布局与交互复核，没有重测 60 秒性能或端到端音画延迟。

- [曲目键盘](../../../.tmp/pianoscope/validation/screenshots/pianoscope-focused.png)：真实初光第 16 源秒，暂停轮廓，不冒充正在发声。
- [完整键盘](../../../.tmp/pianoscope/validation/screenshots/pianoscope-full.png)：同曲同位置，88 键完整可见。
- [播放与分析](../../../.tmp/pianoscope/validation/screenshots/pianoscope-playing.png)：实际输出中的音符、琴键、波形和频谱，未经生成式修改。
- [1000×720 曲目模式](../../../.tmp/pianoscope/validation/screenshots/pianoscope-1000x720-focused.png)、[完整模式](../../../.tmp/pianoscope/validation/screenshots/pianoscope-1000x720-full.png)。

图片来自真实 `View.copy_pixels().to_rgba()`；未使用设计图作截图。已逐图检查布局、高亮、中央 C、手别文字和控件可见性。GPU／CPU 性能数据分别记录，截图所示状态是当时采样，不是图稿写死的数据。

原生文件选择的自动预选确认尝试未能稳定选中文件，未将该尝试标记成功；保留可人工运行的 `python tools/dialog_gate.py --interactive`，选择合法 MIDI 后会记录文件名与解析结果。普通 `dialog_gate.py` 仅验证取消。

后续人工复核：实际选择合法文件／取消；耳听音色、暂停与跳转爆音；设备物理拔插；完整快捷键与焦点；系统 reduced motion；屏录或 loopback 测量端到端音画偏差。完成前继续保留当前验收状态。
