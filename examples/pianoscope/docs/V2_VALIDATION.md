# PianoScope v2 独立验收

2026-10-19，分支 `codex/pianoscope-v2`，v1.1 基线 `757443f2fbf031d09b671606e7e81320dd3b6009`。G0 后依次完成 M1 来源模型、M2 播放编译、M3 阅读跟谱、M4 事务和 M5 入口迁移／交付。正式 `run.py` 已切换 v2；历史验收文件及 Git 历史未改写，不自动 push。这里仅给实际执行的范围签入结果；下列 not_run 子项仍未完成，不声称全部人工与极限组合验收通过。

参考机为 Apple M1 / MacBookAir10,1（硬件型号由本机 sysctl 读取），环境为 macOS 27.0.1 ARM64、CPython 3.10.20、ultralight-py 0.5.0、Verovio 5.6.0（原生 5.6.0-85e7620）、CairoSVG 2.8.2、pypdf 6.12.2、fonttools 4.63.0、psutil 7.2.2、defusedxml 0.7.1、Mido 1.3.3、NumPy 2.2.6、sounddevice 0.5.6、Cocoa 12.2.2；原生 FluidSynth 2.6.1、PortAudio 19.7.0、Cairo 1.18.4。独立验证为 music21 9.9.1／PyMuPDF 1.27.2.3。Python 精确依赖及哈希在 `uv.lock`；[本机安装冻结](../../../.tmp/pianoscope/v2/m5-environment-freeze.txt)不代表其他 Python／平台通过。

机器信息、输入 SHA、设备、worker 时间与内存、逐项断言均在实际报告内。输出设备为 MacBook Air 扬声器；设备声明默认 44.1 kHz，实际原内核优先打开 48 kHz，[单独打开探针](../../../.tmp/pianoscope/v2/m5-device-open.json)记录实际 stream.samplerate=48000。44.1 kHz 切换、设备热拔插均未实测。

| 证据代号 | 实际结果 |
| --- | --- |
| U | [M5 全套 80 passed](../../../.tmp/pianoscope/v2/m5-unit-matrix.xml)，一次完整矩阵，含源、编译、真实 worker／离线 SoundFont 与原 DAC 回归；ZIP 重复名称警告来自故意构造的坏输入 |
| B | [边界／保存取消 20 passed](../../../.tmp/pianoscope/v2/m5-boundary-export-supplement.xml)：含既有 profile 的定向回归；另 [真实 worker 确定性／33 页 1 passed](../../../.tmp/pianoscope/v2/m5-worker-determinism-pages.xml)，[诊断位置 30 passed](../../../.tmp/pianoscope/v2/m5-diagnostic-location.xml)。这些是后续定向结果，不能与 U 简单相加为独立用例总数；当前源码共 89 个参数展开用例 |
| C | [800×600 CPU，47 passed](../../../.tmp/pianoscope/v2/m5-cpu-800-attempt-1.json)：实际 AppCore／API／Canvas／音频，断网沙箱，60 秒最低 30 FPS |
| G | [1440×900 GPU，47 passed](../../../.tmp/pianoscope/v2/m5-gpu-1440-attempt-1.json)：实际 AppCore／音频，断网沙箱，60 秒最低 45 FPS |
| N | [最终遍次／UI 补充 51 passed](../../../.tmp/pianoscope/v2/m5-occurrence-ui-supplement.json)：真实原生休止、小节、tie 后段、第二遍 binding；A/B 遍次文字、默认小屏折叠及触键线持久化 |
| I | [独立进程 0 退出](../../../.tmp/pianoscope/v2/independent-20261019-154037/report.json)：源 XML／MXL 均 192 个音高／拼写，SMF 192 起音，两页 A4 PDF；music21 重新导出 XML 及 PyMuPDF 页面渲染均为实际文件；独立子进程不导入产品编译器 |
| L | [排版／MXL 6 passed](../../../.tmp/pianoscope/v2/g0/outputs-20261019-154040/report.json)：全音符／二分和弦成员真实字形、第二结尾跨谱表 tie、XML/MXL 原件复制与 MIDI 一致；原生 worker <512 MiB／60 秒 |
| X | [官方 MusicXML 4.0 XSD](../../../.tmp/pianoscope/v2/m5-xsd.log)：temporal、printed、symbols 均由 xmllint --nonet 校验通过；XSD 仅开发验证，不运行时下载 |
| G0 | [35 项原生闭环](../../../.tmp/pianoscope/v2/g0/run-20261019-114147/report.json)：实际 DPR=2，100／125／150% 点击、休止、tie 后段、第二遍、变速长音、真实 DAC 与输出；这个小型关卡不代表最终 UI 的 DPR=2 性能 |

发布性能采用 rAF 实际绘制完成后计数，连续 60 秒，以不重叠 1 秒墙钟窗口统计；没有把长帧窗口平均为合格。准备、截图与导出在采样前完成，采样包含翻页和全曲回绕。CPU 使用 1× Canvas backing，GPU 使用 min(2,DPR)；本次系统实际 DPR 均为 1，原生 content points／backing pixels 分别为 800×600、1440×900。参考机 CPU 架构、核心与内存在 C/G 的 reference_machine。最低值仅针对这些窗口和本机，不能沿用到高 DPI 或其他机器。

| 渲染 | 最低 FPS | 平均 FPS | 进程 CPU | 结束 RSS / 全程峰值 RSS | underrun | 接收快照至绘制最大值 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| CPU 800×600 | 30 | 32.20 | 65.73% | 155.83 / 357.89 MiB | 0 | 98 ms |
| GPU 1440×900 | 45 | 57.52 | 39.13% | 204.63 / 405.59 MiB | 0 | 69 ms |

CPU 百分比按单核 100% 的 process_time/wall 计算；RSS 是整个进程，不能与 PCM 192 MiB 专项预算混同。轮询间隔目标 50 ms；“接收至绘制”不包含完整 bridge 传输和物理设备／显示延迟。高亮断言比较同一 seq 的 actual painted element IDs 和 DAC 快照，绝不是只检查数组存在。性能采样后补充 A/B 遍次文字与无效输入位置诊断，分别以 N／定向单测验证；绘制与音频内核未改变，不无因重复长时矩阵。

断网采用 `/usr/bin/sandbox-exec -p '(version 1) (allow default) (deny network*)'`，覆盖应用与其 worker。C/G/N 在成功加载后实际 socket connect 返回 PermissionError；本机没有物理关闭 Wi-Fi 的声明。应用为单 Python／AppCore 进程，报告记录自身进程树；生产无 HTTP、WebSocket、浏览器播放器或 CDN，CSP connect-src=none。Verovio／Cairo 的 SVG 外部 fetch 另有真实拒绝测试。

| 验收 | 状态 | 实测范围及尚未签入的子项 |
| --- | --- | --- |
| AC-01 原生／离线 | passed | C/G/N：固定 binding、AppCore、API("piano")、实际禁止网络后本地载入／合成／播放 |
| AC-02 唯一源入口 | passed | U/B/N/L：UI、CLI、文件夹共用 XML/MXL 导入；.mid、伪 XML、timewise、opus／多 rootfile 拒绝；失败保留旧曲 |
| AC-03 容器／XML 边界 | passed | U/B：DTD 不下载、实体／外部读取拒绝、穿越／重复规范路径／symlink／真实高倍率 ZIP／缺 container 与错误 rootfile；实际节点／文件／条目数上限 |
| AC-04 来源守恒 | passed | U/L/I/N：源哈希不变、全树来源定位、合法 Unicode ID、重复 ID 诊断、原 XML/MXL 字节相同、未知字段原件保留 |
| AC-05 结构 | passed | U/B/G0：backup／forward、divisions 改变、稀疏 voice、异时值和弦、双 part 确认与对齐、重复小节号、弱起与短尾 |
| AC-06 音高／八度 | passed | U/B/I：G/F/C 谱号及真实 C 谱号几何、±7 key、等音／重升降、跨谱表及 8va/8vb 字面音高不二次移动；独立 reader 对源拼写 |
| AC-07 节奏 | passed | U/B/L：原 duration、附点、3/5/6/7 连音精确；5/7 实际 worker 几何，原 voice 保留，不量化 |
| AC-08 速度确认 | passed | U/B/N：offset 默认显示／sound=yes／sound 子 offset、附点 metronome、优先级冲突、缺速度确认及原件绑定；rit. 仅显示诊断 |
| AC-09 反复结尾 | passed | U/B/G0：手工序列 pickup,A,B,A,C,D 与 20 实例；隐含前反复、显式次数、第一／第二结尾、歧义及展开上限拒绝 |
| AC-10 tie／同音 | passed | U/G0/L：链一次起音、跨谱表第二结尾路径、slur 独立起音、不同同音重叠路由及踏板尾音 |
| AC-11 实际 SMF | passed | U/I：独立 Mido 读回手工 20 事件、源音高、note off、tempo、CC64、准确 track/event_index 映射；无 MIDI 转谱 |
| AC-12 DAC 高亮 | passed | C/G/N/G0：真实非零输出、同 seq 的实际涂色 IDs、变速长音、符头全覆盖几何、踏板按住／尾音区分；物理误差 not_run |
| AC-13 定位遍次 | passed | C/G 的裁剪谱行点击 100/125/150%；G0 的 DPR=2 符头／休止／后段／第二遍点击误差 <1 CSS px；N 实际休止／小节／后段和第二遍 binding。最终 UI DPR=2 子项 not_run |
| AC-14 播放恢复 | passed | C/G/N/G0：长音内部／踏板段 seek、pause/stop、三档倍率、单真实流十次回绕与同 epoch；输出在暂停／静音时归零；人工耳听 not_run |
| AC-15 试听／手别 | passed | U/C/G/N：源谱表／voice／确认手别影响真实 PCM 与可听 IDs，空选择静音，未确认拒绝单手；撤销后原件／谱面／默认 MIDI 不变 |
| AC-16 浏览视图 | passed | C/G/N：手动浏览暂停跟随，回当前恢复；谱面／下落／频谱切换保持 PCM/epoch；侧栏／键盘为视图状态 |
| AC-17 小屏／DPI | passed | C/G/N 的实际 CSS／物理 800×600 与 1440×900、DPR=1，小屏默认折叠与整行双谱表；G0 另有 DPR=2 几何，最终 UI 高 DPI 矩阵 not_run |
| AC-18 原子／过期 | passed | U/C/G/N：A 播放时 B 准备、取消、坏源、旧作业迟到、C 胜出、坏 PNG 真解码失败保留 A，候选完整解码后一起发布、不自动播放；确认哈希和同源重载身份隔离。15 秒慢页超时专项 not_run |
| AC-19 导出事务 | passed | U/B/C/G/N：真实原生打开／目录／保存取消，实际原子导出三格式；程序注入的选定目标测试覆盖、磁盘错误、提交前锁检查取消／提交后取消、保存跨曲快照、过期 token；人工保存／覆盖按钮点击 not_run |
| AC-20 打印互通 | passed | I/X/L：独立进程实际 XML/MXL／SMF/PDF 读回及 roundtrip；本次逐页查看两页 PDF PNG 与符号页，中文、谱号、beam/slur/fingering/dynamics/hairpin/fermata、边界无裁切；纸质打印／MuseScore GUI not_run |
| AC-21 特殊项 | passed | U/B：grace／导航／微分音等带定位拒绝；非法声音数值带定位；cue 仅显示、不可见音符仍播放，各有实际 worker 几何和诊断 |
| AC-22 预算确定性 | passed | U/B/L：5,000/5,001 note、256/257 measures、1,024/超限 occurrences、20,000 实例、600 秒、XML／ZIP 限额拒绝；同源两次真实 worker 布局／实例／MIDI 映射完全一致，33 页拒绝且无截断 PDF。512 MiB／60 秒 worker 熔断、最大缓存／底图／PCM 组合的实际极限压力 not_run |
| AC-23 性能 | passed | C/G 各一次 60 秒、最低 30／45 FPS、翻页包含、实际设备播放、0 underrun；完整 60 个计数见原报告 |
| AC-24 旧回归与债务 | passed | U/N：原 SoundFont／合成／DAC、实际波形／频谱／52白36黑键／触键线；v1.1 原文与旧性能失败均保留，未补签历史人工项 |
| AC-25 交付 | passed | 中文 README、锁定版本／许可、原创 XML、真实截图、两页 PDF／原件／SMF／映射、路线／迁移／本页；本地逻辑提交，不 push |

SMF 时间采用各精确位置的分母最小公倍数，不够 32,767 则拒绝；不以四舍五入掩盖。temporal 原创夹具为 PPQN=24，基准 97/6 秒、20 次手工起音；90 BPM 的整数微秒 tempo 编码造成全曲误差界 7/3 微秒，独立读回逐事件按该界对照。PCM sample 四舍五入每个边界最多半 sample（48 kHz 下约 10.42 微秒）；设备 block 512 帧与 UI 轮询延迟单列，不把它们放宽为半拍。

真实文件：[两页 PDF](samples/v2/first-light.pdf)、[原 XML 字节副本](samples/v2/first-light.musicxml)、[Type 1 MIDI](samples/v2/first-light.mid)、[全来源／符头／实例／MIDI 映射](samples/v2/first-light.mapping.json)、[五线谱原生截图](screenshots/v2-score-800.png)、[下落与触键线截图](screenshots/v2-roll-800.png)。原创音乐及代码 MIT，原字体／SoundFont／第三方许可原样保留。打印夹具 SHA-256 为 `f97cfdaadd8572bfba73d3102b41864d190d90d7007d96dc612ecfa375d74f79`。

not_run 子项集中保留：人工耳听与物理声画／高速记录、纸质打印、物理拔插／44.1 kHz 变更、其他 OS／Python／显示器、最终 UI 的 DPR=2 长时运行、15 秒慢页专门注入、完整辅助功能人工检查、真人保存／覆盖交互、MuseScore GUI 与所有预算极限组合。歌词和复杂未列 profile 记谱没有完整显示验收；不能宣称完整 MusicXML 规范兼容。P2 仅规划，无演奏输入、麦克风、评分、完整编辑器和打包。

G0 的路线失败和更正保留：Verovio MIDI 实测 17 起音而手工预期 20，因此改用 Python 编译器；初始 bridge 文档竞争、Fraction 返回和测试预期修正均保存原尝试。早期 run-20261019-111109 的 offset 夹具把默认显示偏移误作播放偏移，已纠正为 sound/offset 并以官方 XSD、新 G0 报告重新验证；该旧通过报告不作为最终 offset 证据。v1.1 的旧 CPU/GPU 失败／未测也未改写。

从 examples/pianoscope 重现本轮发布检查（报告请使用新文件名，保留失败尝试）：

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q --junitxml=../../.tmp/pianoscope/v2/local-unit.xml
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/validate_v2_outputs.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/v2_g0_outputs.py
PIANOSCOPE_NETWORK_DENIED=1 PYTHONDONTWRITEBYTECODE=1 /usr/bin/sandbox-exec -p '(version 1) (allow default) (deny network*)' .venv/bin/python run.py --cpu --width 800 --height 600 --file tests/fixtures/v2/printed.musicxml --smoke --audio-test --measure-seconds 60 --smoke-report ../../.tmp/pianoscope/v2/local-cpu.json
PIANOSCOPE_NETWORK_DENIED=1 PYTHONDONTWRITEBYTECODE=1 /usr/bin/sandbox-exec -p '(version 1) (allow default) (deny network*)' .venv/bin/python run.py --width 1440 --height 900 --file tests/fixtures/v2/printed.musicxml --smoke --audio-test --measure-seconds 60 --smoke-report ../../.tmp/pianoscope/v2/local-gpu.json
```

机器证据在根 `.tmp/pianoscope`，新克隆不附带；正式样本／截图随提交。保护清单复核确认实施前 244 个本地文件未变；v1.1 历史验收、选定样本、SF／字体及许可哈希相同。旧 MIDI 演示和转谱代码仅按迁移范围退役，可在原基线读取；不覆盖用户个人曲目。
