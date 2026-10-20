# 手别分配与声音缓冲内存回归

2026-10-19，用户在分配左右手时触发“当前与候选声音缓冲合计超过 192 MiB”，要求优化或提高限制。本轮针对该路径修正，无 UI 改版、依赖或音源替换；保持 Python 3.10.20、ultralight-py 0.5.0、AppCore、Canvas 2D、`API("piano")` 和唯一 SoundFont／设备 DAC 播放器。

原实现确认任何手别都会重合成全曲。现在确认、撤销及等效试听配置先比较实际发声事件、倍率与安装采样率；声音相同时只更新标签／配置、复用现有只读 PCM，DAC epoch、位置、循环保持。单手试听、单手模式下交换手别或改变速度需要改变声音时，仍先准备候选，成功后原子替换；合成失败、超预算或版本过期保留旧标签、历史、预览、配置及 PCM。

PCM 单份及当前＋候选合计预算统一提高到 **512 MiB**，加载、试听、手别、设备重试和底层渲染共用 `pcm_budget.py`。超过预算在合成／分配前明确拒绝并报告所需大小。XML、排版 worker 和页图等其他预算保持。仅标签更新不再为同一声音申请第二份缓冲。

| 验收 | 实际结果 |
| --- | --- |
| 定向测试 | [28 项通过](../../../.tmp/pianoscope/v2/hands-memory-unit.json)：标签／撤销／等效设置零重合成、PCM 身份和位置／epoch 保持，真实单手交换重新合成且输出变化、撤销恢复原信号，合成失败与超预算回滚，等待命令锁时的过期结果拒绝，512 MiB 精确边界及分配前拒绝，既有事务和 DAC 音频回归。 |
| 个人曲目真实原生鼠标操作 | [16 项通过](../../../.tmp/pianoscope/v2/hands-memory-20261019-234820/report.json)：真实 `Forbidden Colours.mxl`，播放中打开左右手设置并确认、撤销、再确认，期间只有初次加载执行合成；保持同一 PCM／DAC epoch，播放位置继续前进。首轮分配的约 0.44 秒包括侧栏／对话框鼠标步骤，不作为后端耗时。 |
| 实际单手与慢速 | 同一报告：原生按钮切换左手、右手、0.5×；在右手 0.5× 模式交换左右手，再逐次撤销并恢复双手。确实改变发声音符时执行真实 FluidSynth 合成，实际设备输出非零，underrun=0，无 JS 错误；原 MXL 字节和默认 MIDI 保持。总计 7 次真实合成，等效速度按钮未增加合成。 |
| 真实内存规模 | 应用流实际 **48,000 Hz**；初始 PCM 约 107.17 MiB，单手切换两份约 214.33 MiB，1×→0.5× 约 320.77 MiB，两份 0.5× 约 **427.20 MiB**，均已真实分配并在新预算内完成。设备默认字段为 44.1 kHz，此前以默认值计算的约 98.46 MiB 不代表实际应用缓冲。 |
| 正式入口回归 | [51 项原生通过](../../../.tmp/pianoscope/v2/hands-memory-entry.json)：实际 DAC、点击／循环／倍率、手别及试听、取消／坏页图／换曲、原子三格式导出；新默认下落和按需谱面保持。 |

复现命令，在 `examples/pianoscope` 执行：

```sh
.venv/bin/python -m pytest tests/test_v2_hands_memory.py tests/test_v2_transactions.py tests/test_audio.py -q
.venv/bin/python tools/v2_hands_memory_gate.py --source '/本地路径/Forbidden Colours.mxl'
.venv/bin/python run.py --cpu --width 800 --height 600 --smoke --audio-test --smoke-report ../../.tmp/pianoscope/v2/hands-memory-entry.json
```

个人曲目、调试截图及机器报告均留在根 `.tmp/pianoscope`，不提交。原件 SHA-256 为 `1e1cf8410bb7c6fb6dcfdc24d5cf23fd53729aa97a157793684a2130c5413a8b`；测试夹具为项目原创源。无新正式图片或音乐资源，原许可不变。未自动 push，v1.1 历史保持。

512 MiB 仅约束 PCM，应用、原生音源、图形与临时分配另占内存；本机合成结束时采样的进程 RSS 最高约 991.4 MiB，未测全过程内存峰值或极限预算组合。仍采用全曲预合成，尚未实现分段／流式合成；极长曲目或慢速组合仍可能被预算拒绝。此次未重新运行 60 秒 M5 性能矩阵，也未测整曲长时间耳听、物理声画延迟、设备拔插或其他平台，不回填历史未测项。
