# v2 迁移记录

v1.1 基线为 `757443f2fbf031d09b671606e7e81320dd3b6009`。旧 MIDI 载入、量化、猜调、声部分配、制谱预览／应用和对应 UI／专项工具已从生产路径移除；历史源码和测试仍可用 `git show 757443f:examples/pianoscope/<路径>` 阅读。v1.1 验收及选定样本保持原文件。

正式入口 `run.py` 使用 MusicXML Controller 和白名单 binding；旧入口未并存。MIDI 解析器仅保留为基础数据类型与独立回归辅助，不被源导入调用；原分手算法移入 tests/legacy_hands.py，只服务基础回归。原五组旧 Controller／转谱／曲库测试退役，由 test_v2_core、test_v2_source_limits、test_v2_profile、test_v2_transactions 及 v2_checks 的同源事务测试替代；不把旧断言改名当作 v2 证据。

生产保留原 SoundFont、字体、许可证、合成与 DAC 内核。个人文件及本机全部历史证据留在根 .tmp/pianoscope；本次不改写历史、不推送。P2 仅规划：演奏输入、麦克风、评分、制谱编辑和发行打包均未实现。
