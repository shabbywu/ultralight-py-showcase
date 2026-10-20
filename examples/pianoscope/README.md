# PianoScope

以 MusicXML 为曲目源的原生钢琴练习播放器。打开乐谱后即可查看下落音符、试听和慢练，也可切换到五线谱跟随阅读，导出 PDF、原文件副本和 MIDI。

应用使用 ultralight-py **0.6.1**、AppCore、本地 HTML/CSS/JavaScript、Canvas 2D 与 `API("piano")`。钢琴声音来自随包 SoundFont，播放与高亮跟随设备 DAC 时钟。资源安装完成后可离线使用，无需 Web 服务、浏览器或在线音源。目前验证平台为 macOS ARM64；其他平台尚未验证。

![下落音符界面](docs/screenshots/default-roll.png)

## 安装与运行

需要 Python 3.10+。从本目录执行：

```sh
uv sync --python 3.10 --extra test
uv run python run.py
uv run python run.py --file /绝对路径/乐谱.musicxml
uv run python run.py --cpu --width 800 --height 600
```

macOS 还需要本机原生库：

```sh
brew install fluid-synth portaudio cairo
```

Python 依赖及下载哈希由 `uv.lock` 固定。内置 SoundFont、中文字体、音乐字形和第三方许可见 [组件与素材说明](THIRD_PARTY_NOTICES.md)。

## 打开与阅读乐谱

支持 `.musicxml`、根元素正确的 `.xml` 和受限的 `.mxl`。选择文件夹时只列出当前目录的支持文件，不递归扫描；可按文件名搜索。MIDI 仅作为导出格式，不接受 `.mid` 输入。

默认显示下落音符。首次打开先准备播放数据与声音，等待手动播放；五线谱在点击“五线谱”后按需排版，成功后复用。排版期间可以继续播放；取消或失败可返回下落视图或重试。加载新曲失败会保留当前曲目。

五线谱可缩放 100／125／150%，点击符头、休止或小节定位。有反复时可选择遍次；延音线后段仍对应同一次起音。滚轮、触摸或翻页暂停自动跟随，“回到当前”恢复。[五线谱界面](docs/screenshots/lazy-sheet.png)。

下落音符的同键连续起音留有短间隔，延音线连接的持续音保持整条。按住期间有持续溅起的粒子尾迹，松键后淡出；顶部“触键光效”可关闭，系统“减少动态效果”会停止移动粒子。[触键尾迹动画](docs/screenshots/roll-trails-animated.png)。触键线可上移 0–60%。

## 播放与练习

- 速度支持 0.5×／0.75×／1×，慢速保持音高。
- 点击声音概览定位，拖动 A／B 或输入时间设置片段循环；区间至少 0.5 秒。停止回曲首并保留区间，下一次播放从 A 点开始。
- “试听范围”可选全部、上谱表、下谱表或静音，也可按声部筛选；重新打开保留已应用的选择，取消不改变声音。[试听范围界面](docs/screenshots/audition-800.png)。
- “左右手设置”按谱表给出初始建议，确认后才生效，可撤销。未确认前不会将上下谱表直接当作左右手。侧栏“双手｜左手｜右手”可切换试听。[左右手界面](docs/screenshots/hands-800.png)。
- 仅改变标签或等效试听设置时复用声音缓冲，保持播放位置；需要改变实际声音时，先准备候选再替换。试听和手别不修改原乐谱及默认全曲 MIDI。
- 可显示完整 88 键或曲目音域，展开声音波形和频谱。琴键点击仅显示音高信息，不作为演奏输入。

小窗口侧栏为抽屉，下落视图默认展开键盘；五线谱工具栏可收起键盘以增加阅读空间。快捷键：空格播放／暂停，Home 回曲首，左右箭头跳 2 秒，PageUp／PageDown 浏览五线谱，Esc 关闭对话框。输入框和按钮保留自身键盘操作。

## 导出与示例

支持 A4 PDF、原文件副本及 Type 1 MIDI。原文件副本逐字节保留 XML 编码或 MXL 容器。PDF 按需排版；源分页超出 A4 边界时，派生谱面重新分页，原文件不变。默认 MIDI 为完整曲目、基准速度、全部谱表／声部，不受试听设置影响。

保存取消或失败保留已有目标，禁止覆盖当前输入源文件。保存开始后即使换曲，也按已选曲目的快照完成导出。

原创“初光”示例：[两页 PDF](docs/samples/first-light.pdf)、[MusicXML](docs/samples/first-light.musicxml)、[MIDI](docs/samples/first-light.mid)。示例乐谱及对应截图采用本项目 MIT 许可。

## 支持范围与限制

MusicXML 3.1／4.0 `score-partwise`，支持一个双谱表 part，或确认后的两个单谱表 part。缺少起始数值速度时需先确认；错误与仅显示的记号在“乐谱提示”中附来源位置。

支持 G／F／C 谱号、调号和整数半音 A0–C8、backup／forward、稀疏声部、独立时值和弦、跨谱表、附点及 3:2／5:4／6:4／7:4 连音。时值直接采用源 duration／divisions。拍号支持 2/4、3/4、4/4、3/8、6/8、9/8、12/8，以及弱起、合法短尾。

普通非嵌套反复（2–16 次）和一二结尾有界展开；tie 合并起音，slur 保持独立起音。支持节内数值速度、附点节拍器、CC64 踏板、固定力度及无 tie 的 staccato。direction/offset 默认仅影响显示，`sound="yes"` 或 sound 子 offset 才影响播放。数值 sound 速度优先于节拍器，同谱表同位置的顺序速度命令采用最后值并提示，跨谱表／分部冲突拒绝。

琶音按源分组和方向依次起音，间隔采用 1/16 四分音符的固定策略，短音时收窄，结束位置不延长。定量震音支持 1–8 划的单音／和弦，以及同小节同声部相邻、等时值音／和弦的交替；2:1 时值比例不重复缩放。自由震音、跨小节配对，以及琶音／震音与 tie、cue、staccato 的组合尚未支持。

grace、D.C./D.S./Fine/Coda 导航、嵌套反复、微分音、非零移调、打击乐及其他未实现装饰音会带位置拒绝。fermata、accent、tenuto、换气、渐强渐弱、rit. 等仅显示并提示未额外改变声音。歌词、密集和弦文字和复杂版式不保证完整还原出版谱；排版缺失符头时不会发布该谱面，下落播放仍可用。

输入限 10 MiB；MXL 最多 256 项、单项 16 MiB、总解压 32 MiB、解压比 100:1。源音符最多 5,000 个、小节 256 个；展开最多 20,000 个实例、1,024 次小节出现、基准 600 秒。当前与候选 PCM 合计限 **512 MiB**，应用和原生音源另占内存；长曲和慢速组合仍可能超限。排版最多 32 页、每页 2,000 个字形；页图和作业产物各限 128 MiB，隔离排版进程限 512 MiB／60 秒。

当前不提供演奏输入、麦克风、评分、完整制谱编辑器或发行安装包。尚未系统验证人工耳听、物理声画延迟、设备拔插和其他操作系统。

## 测试与本地文件

Python 模块按职责组织：

- `pianoscope/score/`：MusicXML 源文件、语义模型、播放计划、MIDI 编译、谱面排版及隔离进程。
- `pianoscope/playback/`：播放事件模型、SoundFont 合成、PCM 缓冲、设备 DAC 时钟与声音分析。
- `pianoscope/app/`：曲目与导出事务、原生对话框、`API("piano")` 桥接。
- `pianoscope/assets/`、`pianoscope/resources/`：本地前端与随包资源；资源位置由 `pianoscope/paths.py` 统一定位。
- `tests/`：自动化回归及 `fixtures/musicxml/` 源乐谱；`tools/`：原生验收与资源生成工具。

```sh
uv run --extra test python -m ruff format --no-cache --check .
uv run --extra test python -m ruff check --no-cache .
uv run --extra test python -m pytest -q
```

Ruff 固定为 0.15.12，按 Python 3.10 检查；需要自动整理格式时运行 `uv run --extra test python -m ruff format --no-cache .`。

`pianoscope/` 的生产函数使用类型标注和中文文档字符串；Ruff 检查参数、返回值标注及文档是否缺失。拍位使用 `Fraction`，声音缓冲为双声道 `float32` 数组，跨界面异构记录与原生 C／PyObjC 边界保留必要的动态类型。这些检查不等同于完整静态类型检查。

前端直接使用 SDK 的共享 Python 容器：任务状态、设置、诊断和命令结果通过普通 JS 属性、数组方法及迭代访问；JS 配置对象直接传给 Python。共享容器本身不提供响应式通知，目前仍由既有轮询和 DOM 更新驱动界面。修改返回的设置记录不等于应用设置，仍须调用配置命令。

Canvas 会反复遍历的数据（音符、谱面几何、文档、播放状态、声音概览及频谱）在进入渲染层时用 `Python.to_value` 显式复制，避免逐帧跨桥读取。加载任务的 `epoch`、`decoding` 等标记属于 JS 本地记录；跨协程和工作线程保存的命令参数由 Python 捕获独立快照。

个人曲目、开发规划、验收记录、机器报告、调试截图和中间产物放仓库根 `.tmp/pianoscope/`，不提交。`docs/` 只保留第三方许可、用户指南引用的正式图片和当前原创示例资源。
