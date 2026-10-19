PianoScope v2 路线决策 · 2026-10-19

用户已批准实施；v1.1 基线为 `757443f`，保留在 Git 历史。本页只冻结 G0 已实测的路线，完整产品仍须通过 M1–M5。

MusicXML 3.1／4.0 partwise 为唯一曲目源。源字节、SHA-256、原件容器和来源树保持；安全工作副本去除外部资源引用。XML 使用 defusedxml 0.7.1；DTD 不取回，内部实体拒绝。MXL 在内存中有界读取，不解包到文件系统。所有时间先用有理数四分音符单位，浮点秒及整数 MIDI tick／PCM sample 只在输出端使用。

播放采用 Python 自有路径展开与编译器。普通反复、一二结尾、实际路径上的 tie、节内 tempo 与踏板共同生成实例、显示区间及 Type 1 SMF。自有 SMF writer 由独立 Mido 读回并与手工事件表比对。PPQN 由分母最小公倍数确定，超过 32,767 明确拒绝。SMF 使用 15 个非打击乐通道，未验证多端口；容量不足拒绝，不合并同音。试听复用既有 FluidSynth／PCM／PortAudio 设备 DAC 内核，不从 MIDI 反推记谱。

Verovio 5.6.0-85e7620 的 renderToMIDI 已实际比较：时间夹具预期 20 次起音，候选输出 17 次；其产物、日志保留，不选为权威编译器。音符存在／接口存在不能证明源语义正确。

排版采用安全源 XML → Verovio 原生导入 → 只读派生 MEI → 原生 SVG／真实字形几何 → CairoSVG PNG／PDF。G0 发现固定导入器丢失和弦成员独立时值，并遗漏第二结尾 tie；适配器保留源声部和 ID，在 MEI 中恢复成员时值、精确隐藏布局间隔和已由实际路径证明的 tie。MEI 不成为可编辑曲目源，播放从不读取 MEI 时间。所有应显示符头／休止必须实际获得几何，否则阻断发布。

源文件副本直接复制原字节；安全 XML／MEI 工作文件明确命名为中间产物。源文件 SHA-256 不变，未知非执行元数据留在原件。PDF 使用本地 Noto CJK 与 Leipzig 路径，不依赖系统音乐字体。渲染库在独立进程；主线程调用 View，音频回调只消费准备好的 PCM。

依赖保持 Python 3.10+、ultralight-py==0.5.0、AppCore、本地 HTML/CSS/JavaScript、Canvas 2D、API("piano")。本机实测 CPython 3.10.20／macOS 27.0.1 arm64；依赖沿用原锁定版本，新增显式声明既有传递依赖 defusedxml 0.7.1（PSF license）。music21 9.9.1／PyMuPDF 1.27.2.3 仍仅验证使用。音乐片段直接编写 MusicXML，以本项目 MIT 发布；music21 另导出的样本来自同一原创源，许可仍为 MIT，没有从 MIDI 转谱。

G0 保留原建议预算：XML/MXL 10 MiB、容器总解压 32 MiB／256 项／单项 16 MiB／100:1；5,000 源音符／256 小节，20,000 实例／1,024 小节出现，基准 600 秒；当前＋候选 PCM 192 MiB，32 页／每页 2,000 字形，底图和作业各 128 MiB，worker 512 MiB／60 秒。上限不是已实测规模；超限明确拒绝，不裁切后宣称成功。

G0 证据见 [v2 验收](V2_VALIDATION.md)。所有历史人工／性能未测项保持原状态；不把 G0、截图或候选接口记作完整发布通过。P2 仅规划。

偏移规则按 [MusicXML offset 规范](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/offset/) 实现：direction/offset 默认仅显示，sound="yes" 才影响播放；sound 的子 offset 覆盖 direction。早期夹具错误已更正并重新执行 G0，旧报告不作最终证明。SourceDocument 的内容身份保持确定；会话发布 revision 另含加载身份，防止相同文件重载后混用旧确认或资源。
