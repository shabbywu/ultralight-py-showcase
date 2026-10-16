# 验证记录

2026-10-16，macOS ARM64，Python 3.14.6，已安装 ultralight-py 0.5.0。

- `python -m pip install -e '.[test]'`：通过。
- `BRIDGE_LAB_NATIVE=1 python -m pytest -q`：11 passed，含真正 AppCore 子进程；非项目工作目录启动也通过。
- `python run.py --smoke`：GPU 通过，正常自动退出。
- `python run.py --cpu --smoke --screenshot docs/screenshots/bridge-lab.png --smoke-report docs/smoke-cpu.json`：CPU 通过；报告保留真实失败用例（success=false）以证明错误恢复，总体 success=true。
- 原生断言：六个默认案例；编辑 20→30 得到 52；Counter=2；容器快照；除零语义；完整 profile JSON；未捕获同步错误与异步拒绝后恢复；运行锁、切换/重置锁；日志清空、300 条上限、4000 字符截断。
- 仓库根目录 `BRIDGE_LAB_NATIVE=1 python -m pytest -q`：143 passed（包括其他已有示例回归）。
- 实际 AppCore CPU View 截图已目视检查：六个案例、中文、编辑器、源码、日志、真实 Counter Inspector 显示正常。

需求覆盖：FR-01～08 和 DEMO-01～06 已实现。AC-03～10 有原生自动断言；AC-01 已安装并启动，未另建全新虚拟环境；AC-02 使用全本地资源和 CSP，但未断开系统网络实测；AC-11 自动关闭退出已测，手动点击原生关闭待验；AC-12 文档与真实截图已交付。

尚未人工验证：输入法预编辑、系统剪贴板、键盘选区/撤销、窗口缩放与多显示器、点击原生关闭。尚未验证 Windows、Linux、Python 3.10–3.13；不声明全平台通过。P1 均未实施。

API 修订及原因见 README：wait_until callable；先等待页面 settled；6 函数 + counter 共 7 个入口；安装包内资源及运行时生成源码。所有检查依据 0.5.0 安装源码与官方 AppCore 示例，未使用浏览器代替原生验收。

## 用户功能验收

2026-10-16：用户启动原生窗口后反馈“功能验收正常”。此为用户整体功能反馈，未据此扩大已验证平台范围或逐项声明所有手工检查通过。验收后重新运行真实 AppCore CPU 场景并截图，同步至 `site/assets/bridge-lab.png`。

提交的 smoke-cpu.json 将本机绝对路径替换为 `<repo>/` 与 `<python>/`，保留真实异常、输出、耗时及测试结果。
