# 文件清单

- `pyproject.toml`：Python 版本、固定运行依赖、测试依赖及包内资源。
- `run.py`：资源白名单、版本核验、AppCore 生命周期、GPU/CPU 原生 smoke、JSON 报告及真实像素截图。
- `bridge_lab/__init__.py`：包入口。
- `bridge_lab/models.py`：Counter 持久对象。
- `bridge_lab/bridge.py`：6 个函数与对象白名单注册。
- `bridge_lab/fixtures.py`：从实际实现提取 Python 源码。
- `bridge_lab/assets/index.html`：本地页面、CSP、可访问性标签。
- `bridge_lab/assets/style.css`：深色布局、小窗口适配与焦点样式。
- `bridge_lab/assets/samples.js`：6 个可编辑 JS 样例及预期说明。
- `bridge_lab/assets/app.js`：真实执行器、草稿、运行锁、Inspector、结构化有界日志和复制。
- `tests/test_models.py`：对象与函数参数边界。
- `tests/test_bridge_contract.py`：注册名称、异步类型、白名单、实例隔离。
- `tests/test_native_smoke.py`：可选择启用的原生子进程回归测试。
- `README.md`：中文启动、使用、API 语义、安全与限制。
- `docs/VALIDATION.md`：验收范围和未验证事项。
- `docs/smoke-cpu.json`：本机真实 CPU 冒烟报告。
- `docs/screenshots/bridge-lab.png`：真实 AppCore CPU View 截图。
- `.gitignore`：忽略本地测试、构建元数据。
