# Ultralight Bridge Lab

用 AppCore 原生窗口探索真实 Python ↔ JavaScript 桥接。已实现 FR-01～FR-08、六个 P0 示例及中文编辑界面；运行输出全部由 ultralight-py 0.5.0 计算。无需浏览器、Node、CDN 或 Python Web 服务。

![真实 AppCore CPU 窗口渲染截图](docs/screenshots/bridge-lab.png)

从仓库根目录开始（Python 3.10+，需要该版本支持的系统 wheel 和桌面环境）：

```sh
cd examples/bridge-lab
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e '.[test]'
python run.py
python run.py --cpu
python run.py --smoke --smoke-report result.json
python -m pytest -q
BRIDGE_LAB_NATIVE=1 python -m pytest -q  # 包含真实原生子进程测试
```

安装需要下载依赖；安装完成后资源均在包内，运行不依赖网络。`python -m pip install -e .` 只安装运行依赖，测试额外安装 `.[test]`。Windows 可用 PowerShell `$env:BRIDGE_LAB_NATIVE='1'` 启用原生测试。

左侧切换六个案例。修改 JS 后按运行或 Ctrl/Cmd+Enter；Tab 输入两个空格，支持系统选择、复制、粘贴和撤销。Python 面板只读，内容通过 `inspect.getsource` 从实际注册实现生成。复制按钮复制对应面板；不可用时可手动选中复制。运行前与切换案例时复位后端 Counter；切换保存各案例 JS 草稿，只有“重置 / 恢复示例”恢复默认文本。运行期间禁止重复运行、切换和重置。

`lab.add` 为同步调用；`lab.delayed_double` 返回 Promise，校验整数和 0–2000ms 边界，使用 AppCore 共享 asyncio。`lab.counter` 是长期存在的真实实例，只开放 value、history、increment、reset。list/dict 为 Python 代理：索引用 `Python.getitem`，长度用 `Python.len`，先 `Python.to_value` 再 JSON 序列化或交给 UI 状态管理。快照修改不写回 Python。另有 reset_counter、divide、get_profile、get_status；不存在任意 Python eval/exec 入口。

Runner 包装可信 JS 为 async 函数，注入 print 和 console.log/warn/error；显式 return 也会显示。异常记录消息及堆栈，失败后恢复按钮。日志记录时间、run ID、案例、级别及完成耗时，最多 300 条、每条 4000 字符。Inspector 读取真实 Proxy/API。

API 核验与规格修订：固定使用安装包 0.5.0 的实现，参考[官方 AppCore 示例](https://github.com/shabbywu/ultralight-py/blob/main/examples/appcore.py)。核心 register/register_object/attach 契约一致。`wait_until` 需要 Python callable，不能传 JS 字符串；原生测试先 `wait_settled` 再检查 ready，避免加载中提前 evaluate 触发桥接上下文冲突。规格称“7 个 API 入口”实际为 6 个函数加 1 个 counter 对象，按表格实现。资源放入 `bridge_lab/assets` 以确保安装后也能读取；sources.js 动态生成以避免源码副本漂移。

所有 Runtime/View 操作均在主线程。仅 app.run / run_async 驱动，不额外调用 Runtime.update。API/Application 上下文负责关闭与取消桥接任务，pagehide 使页面输出失效。测试使用临时缓存目录，超时或断言失败返回非 0，并写入报告。

这是可信本地代码实验室，**不是安全沙箱**。不运行他人的脚本；不提供 Python REPL、文件系统、进程执行能力。页面 CSP 禁止连接、外部框架与表单；资源 loader 只服务精确文件白名单。用户自己修改的 JS 可以阻塞主线程，死循环无法由 UI 中断，需要结束进程。

默认 1280×800；宽度低于 1000px 后检查器移到下方。CSS 最小内容宽度 580px，小窗口滚动；0.5.0 create_window 未提供最小尺寸参数，因此不虚构原生最小窗口限制。

实测 macOS ARM64 / Python 3.14.6，GPU 与 CPU 冒烟通过；Windows x64、Linux x64（glibc ≥2.34）、Python 3.10–3.13 未在本次验证。没有 GUI 或可用 wheel 时，默认 pytest 明确跳过原生测试，不能当作原生通过。完整结果、手工待验项目见 [VALIDATION.md](docs/VALIDATION.md)。

常见问题：若 GPU 启动失败，试 `--cpu`；ready 超时请检查终端异常及是否安装 0.5.0；`textAreaResizeCorner` 平台资源警告不影响本次验证的桥接。截图可重现：

```sh
python run.py --cpu --smoke --screenshot docs/screenshots/bridge-lab.png
```

截图来自真实 AppCore View 像素，未绘制模拟结果。P1 主动推送、导航恢复展示、日志导出、PyInstaller 和发行流水线未实现。IME、剪贴板、原生手动关闭与多显示器仍需人工验收。Ultralight SDK 与 Python 绑定遵守各自许可，商业分发需独立核验 SDK 授权。
