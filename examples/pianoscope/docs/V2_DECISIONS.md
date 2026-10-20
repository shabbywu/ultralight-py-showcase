PianoScope v2 路线决策 · 2026-10-19

用户已批准实施；v1.1 基线为 `757443f`，保留在 Git 历史。本页冻结 G0 已实测的路线；后续 M1–M5 的实测结果与未测限制见独立验收页。

MusicXML 3.1／4.0 partwise 为唯一曲目源。源字节、SHA-256、原件容器和来源树保持；安全工作副本去除外部资源引用。XML 使用 defusedxml 0.7.1；DTD 不取回，内部实体拒绝。MXL 在内存中有界读取，不解包到文件系统。所有时间先用有理数四分音符单位，浮点秒及整数 MIDI tick／PCM sample 只在输出端使用。

播放采用 Python 自有路径展开与编译器。普通反复、一二结尾、实际路径上的 tie、节内 tempo 与踏板共同生成实例、显示区间及 Type 1 SMF。自有 SMF writer 由独立 Mido 读回并与手工事件表比对。PPQN 由分母最小公倍数确定，超过 32,767 明确拒绝。SMF 使用 15 个非打击乐通道，未验证多端口；容量不足拒绝，不合并同音。试听复用既有 FluidSynth／PCM／PortAudio 设备 DAC 内核，不从 MIDI 反推记谱。

Verovio 5.6.0-85e7620 的 renderToMIDI 已实际比较：时间夹具预期 20 次起音，候选输出 17 次；其产物、日志保留，不选为权威编译器。音符存在／接口存在不能证明源语义正确。

排版采用安全源 XML → Verovio 原生导入 → 只读派生 MEI → 原生 SVG／真实字形几何 → CairoSVG PNG／PDF。G0 发现固定导入器丢失和弦成员独立时值，并遗漏第二结尾 tie；适配器保留源声部和 ID，在 MEI 中恢复成员时值、精确隐藏布局间隔和已由实际路径证明的 tie。MEI 不成为可编辑曲目源，播放从不读取 MEI 时间。所有应显示符头／休止必须实际获得几何，否则阻断发布。

源文件副本直接复制原字节；安全 XML／MEI 工作文件明确命名为中间产物。源文件 SHA-256 不变，未知非执行元数据留在原件。PDF 使用本地 Noto CJK 与 Leipzig 路径，不依赖系统音乐字体。渲染库在独立进程；主线程调用 View，音频回调只消费准备好的 PCM。

依赖保持 Python 3.10+、ultralight-py==0.5.0、AppCore、本地 HTML/CSS/JavaScript、Canvas 2D、API("piano")。本机实测 CPython 3.10.20／macOS 27.0.1 arm64；依赖沿用原锁定版本，新增显式声明既有传递依赖 defusedxml 0.7.1（PSF license）。music21 9.9.1／PyMuPDF 1.27.2.3 仍仅验证使用。音乐片段直接编写 MusicXML，以本项目 MIT 发布；music21 另导出的样本来自同一原创源，许可仍为 MIT，没有从 MIDI 转谱。

G0 保留原建议预算：XML/MXL 10 MiB、容器总解压 32 MiB／256 项／单项 16 MiB／100:1；5,000 源音符／256 小节，20,000 实例／1,024 小节出现，基准 600 秒；当前＋候选 PCM 192 MiB，32 页／每页 2,000 字形，底图和作业各 128 MiB，worker 512 MiB／60 秒。上限不是已实测规模；超限明确拒绝，不裁切后宣称成功。

G0 证据见 [v2 验收](V2_VALIDATION.md)。所有历史人工／性能未测项保持原状态；不把 G0、截图或候选接口记作完整发布通过。P2 仅规划。

偏移规则按 [MusicXML offset 规范](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/offset/) 实现：direction/offset 默认仅显示，sound="yes" 才影响播放；sound 的子 offset 覆盖 direction。早期夹具错误已更正并重新执行 G0，旧报告不作最终证明。SourceDocument 的内容身份保持确定；会话发布 revision 另含加载身份，防止相同文件重载后混用旧确认或资源。


2026-10-19 用户反馈变更：默认下落视图与 profile V2-P0-2

按用户要求覆盖原规格“默认五线谱／排版后才能就绪”的加载顺序。候选源语义、MIDI 和 PCM 保持一起原子发布；五线谱改为独立、绑定 source revision 的按需作业，全部真实页图解码后才提交布局，取消、失败或迟到结果不得改变当前 PCM／DAC epoch。尚未排版时 `layout_revision=null`、`layout_ready=false`，不宣称已有符头几何；PDF 导出独立按原源快照排版，源副本及 MIDI 不等待排版。无新增依赖，继续同一 SoundFont 播放器。

profile V2-P0-2 新增琶音及定量单音／同小节成对音／和弦震音的真实事件编译。琶音分组／默认方向来自 [MusicXML arpeggiate](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/arpeggiate/)，间隔采用项目明确策略（1/16 四分音符，短音收窄、原 release 不延长）；规范没有指定演奏展开时间。震音按 [MusicXML tremolo](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/tremolo/) 使用划数／原 type 附加符尾确定细分，并以原 duration 限定总时长，2:1 不重复缩放。自由／跨小节／歧义或与 tie 等组合继续拒绝，换气仅显示并诊断。同谱表同位置连续速度命令采用源顺序最后值并诊断，跨谱表矛盾仍拒绝。

个人曲目的编码分页实测可越过固定 A4 页底。排版器先以真实原生几何预检，超界时只对派生谱面进行一次自动重新分页，再按原严格符头／休止／ID／打印边界校验；不裁切，不删除音符，不改原字节。页数、内存、产物、超时预算保持。

新证据、失败尝试及未测限制另记 [默认下落／兼容验收](V2_LOADING_VALIDATION.md)。原 G0／M5 结果与 v1.1 历史保持原记录，不据此回填新的完整发布矩阵。


2026-10-19 手别分配内存修正：用户在确认左右手时触发旧 192 MiB 上限，授权优化或提高限制。确认／撤销手别后比较实际发声事件（实例、轨道、音高、力度、起止及延音结束）、倍率和安装采样率；完全一致时只提交标签／试听配置并复用只读 PCM，保持 DAC epoch、位置和循环。等效范围／速度选择同样复用。实际声音改变时继续后台预合成、取消／过期检查、成功后原子替换，失败保留旧 PCM 和手别历史。

PCM 单份与当前＋候选合计预算统一提高至 512 MiB，集中于 `pcm_budget.py`，覆盖加载、试听／速度、手别、设备重试和渲染器；不修改 XML、排版 worker 或其他预算。真实个人曲目在应用实际 48 kHz 下的慢速候选组合达到约 427.2 MiB，原生鼠标操作／DAC 输出通过。设备默认采样率字段为 44.1 kHz，不能用它冒充应用流采样率。实测与内存／长时未测限制见[手别内存验收](V2_HANDS_MEMORY_VALIDATION.md)，原 192 MiB 记录保留为历史。
