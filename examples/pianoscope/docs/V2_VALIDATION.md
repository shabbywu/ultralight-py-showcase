PianoScope v2 独立验收 · 实施中

本页从 v2 开始单独记录。v1.0／v1.1、readable-v2.0／v2.1 历史文件保持原状，旧结果不自动签入 v2。用户批准后在本地 `codex/pianoscope-v2` 分支实施，不自动 push。

G0 / M0 已复核通过；数据与时间核心已推进，M3／M4 集成中，M5 尚未运行。当前正式入口仍为 v1.1；完整 v2 发布矩阵 AC-01–AC-25 暂为 not_run，下面的专项结果不表示全部支持矩阵通过。

| G0 专项 | 结果与证据 |
| --- | --- |
| 直接源模型、反复与时间编译 | 26 项核心测试通过；独立 SMF reader 对照 20 次手工起音，tie／同音重叠／tempo offset／八度／MXL／来源守恒／定位与不支持拒绝。[JUnit](../../../.tmp/pianoscope/v2/g0/../offset-semantics-tests.xml) |
| 原音频内核回归 | 30 项通过；实际 SoundFont、DAC 时钟与原数学／音乐基础。[JUnit](../../../.tmp/pianoscope/v2/g0/audio-foundation-regression.xml) |
| 真实原生闭环 | [35 项断言通过](../../../.tmp/pianoscope/v2/g0/run-20261019-114147/report.json)，CPython 3.10.20、固定 0.5.0、AppCore、800×600／DPR=2、真实输出设备、Canvas、重叠实例、暂停、100／125／150% 点击、延音后段／第二遍 seek、0.5／0.75／1× 长音内部恢复、实际 DAC 反复跳转；underrun 记录见报告 |
| 实际排版与容器守恒 | [补充关卡](../../../.tmp/pianoscope/v2/g0/outputs-20261019-115517/report.json)：源 ID、全音符与独立二分符头、第二结尾跨谱表 tie 的真实路径；XML／MXL 原字节相同、两容器 MIDI 相同；worker 峰值约 247 MiB、单作业约 0.8–1.4 秒 |
| 原创两页 PDF 与原件／MIDI | [两页 A4 PDF](../../../.tmp/pianoscope/v2/g0/run-20261019-114147/printed/score.pdf)、[原 XML 副本](../../../.tmp/pianoscope/v2/g0/run-20261019-114147/printed/source-copy.musicxml)、[真实 MIDI](../../../.tmp/pianoscope/v2/g0/run-20261019-114147/printed/score.mid)；三张 PDF 页面 PNG（时间夹具一页＋打印夹具两页）已查看，中文／谱号／连线／页边界无裁切 |
| 外部软件样本／独立读取 | music21 9.9.1 独立读取 192 个源音高并重新导出；导出样本再次按同一 MusicXML profile 载入成功。原创 MIT 许可。[外部软件导出文件](../../../.tmp/pianoscope/v2/g0/run-20261019-114147/music21-export.musicxml) |
| 候选失败与路线选择 | Verovio MIDI 输出 17 次起音，手工预期 20，未选为播放编译器。桥接初始文档竞争、seek 返回 Fraction 和测试预期修正的失败尝试均保留在同目录各 run-*／JUnit attempt-1 文件，不覆盖或伪装通过 |

运行命令（从 examples/pianoscope）：

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_v2_core.py -q
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/v2_g0_outputs.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/v2_g0.py
```

每次原生／输出关卡写新的带时间目录，不覆盖历史失败。G0 完成后只在受影响的底层改动时重跑对应专项；M5 再运行一次完整对应发布矩阵和 60 秒 CPU／GPU 最低 30 FPS 验收。G0 没有声称已经完成这项性能检查。

未测：人工耳听、物理声画误差、纸质打印、设备拔插、其他操作系统／DPI、完整人工可访问性，以及完整产品事务／曲库／导出界面。它们不因原生自动断言通过而补签。所有机器报告、个人文件、调试截图和中间文件保存在根 .tmp/pianoscope；路径链接仅供本地查阅，新克隆不附带。

2026-10-19 复核更正：早期 G0 夹具误把未标 sound="yes" 的 direction/offset 当作播放偏移，且存在空 direction-type。现改为规范 sound/offset；两份原始夹具已通过固定 MusicXML v4.0 官方 XSD 的 xmllint --nonet 校验，并用新输入重新通过 35 项原生断言和上述输出关卡。早期 run-20261019-111109 等报告保留为历史尝试，不作为最终 offset 语义通过证据。新增单测区分 direction 默认显示偏移、显式播放偏移、子 sound/offset 覆盖及附点 metronome。
