# Ashen Reliquary

基于 ultralight-py 原生窗口的背包示例。Python 持有权威状态和业务规则；Vue 2 与 DOM 视图只提交命令、渲染副本。后续 Godot Sample 2 可复用前端并实现相同宿主协议。

## 结构

| 目录 | 职责 |
|---|---|
| `web/packages/grid-inventory/` | TypeScript 背包核心与可选 DOM 视图，见[包说明](web/packages/grid-inventory/README.md) |
| `web/src/game/` | 只读展示副本、后端命令与事件适配 |
| `web/src/main.js` | 连接后端事件并装配 Vue 界面 |
| `reliquary/state.py` | 内存／文件快照存储，原子写入 |
| `reliquary/models.py` | 明确的领域 dataclass 与枚举 |
| `reliquary/inventory.py` | 状态校验与原子事务方法 |
| `reliquary/game.py` | 权威状态、初始化、物品生成、业务规则与事件 |
| `reliquary/catalog.json` | 后端物品定义与默认容器 |
| `reliquary/codec.py` | 磁盘与桥接边界的数据编解码 |
| `reliquary/bridge.py` | 明确的方法接口与宿主事件桥接 |
| `run.py` | ultralight-py 窗口启动入口 |

前端不导入背包核心来提交本地事务。DOM 视图通过 `InventoryPort` 调用后端预览与命令接口；后端提交后发布事件，前端重新获取展示副本。Godot 接口见 [Godot 接入](docs/GODOT_ADAPTER.md)。

## 运行

```sh
cd web
npm ci
npm run build
cd ..
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python run.py --cpu
```

原生窗口需要桌面环境、Python 3.10+ 和 ultralight-py 0.6.1。默认仅在进程内保存，`--state path/to/state.json` 开启文件持久化。

前端修改后重新执行 `npm run build --prefix web`，再通过 ultralight-py 运行。前端需要宿主桥接，不提供 localStorage 权威状态或独立浏览器运行模式。

## 操作与存档

- New relic 请求后端生成物品；后端选择定义、分配 ID、放置并提交后，通知前端刷新。
- 拖动物品落格；R 旋转，Escape 或失焦取消。Ground 为 12×12，Bag 为 12×6，窗口缩放不重排物品。
- 双击装备／卸装，Shift 点击在 Ground 与 Bag 间转移。双手武器同时占用主副手。
- 拖到兼容堆叠上合并；释放时按住 Ctrl 拆分，滚轮调整数量，取消不生成实例。
- 将 Ember Gem 拖到 Saint-Socket 镶嵌，选中宝石后点击 Remove gem to Bag 摘除。
- 将物品拖到快捷栏绑定，点击或按 1–6 激活；Ember Flask 消耗由后端处理。
- Save / Retry 保存或重试；Offer to the ashes 删除选中物品。

全量快照包含版本、修订号、容器、物品与快捷栏引用，不包含 HTML。每次后端事务提交后自动保存；保存失败保留游戏内操作并允许重试。加载失败阻止覆盖原存档。旧版布局存档和迁移接口已移除，旧文件需要自行移走后重新开始。

控制台 `Reliquary.snapshot()` 返回快照，`Reliquary.engine` 提供后端命令与预览适配（不提供状态加载），`Reliquary.view` 提供视图调试入口。

## 检查

```sh
npm test --prefix web
npm run check --prefix web/packages/grid-inventory
python -m unittest discover -s tests -v
```

后端测试覆盖生成、身份分配、事务失败、修订号、装备、堆叠、镶嵌、引用、随机移动和保存重试；前端测试覆盖事件驱动刷新和副本隔离。通用 TypeScript 包保留独立核心回归，但应用不使用它持有权威状态。

真实 Ultralight 离屏检查：`python -m tools.native_smoke`，验证 Python 主动生成后的页面更新、对象副本隔离、命令、通知及页面重载。这不代表已完成桌面窗口真实输入验收。

Python 开发依赖：`pip install -e ".[dev]"`。检查：`ruff check .`、`ruff format --check .` 与 `mypy`（strict 模式，覆盖领域、存储、桥接、入口及检查代码）。

## 来源

代码来源与当前依赖声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，上游 GPL v3 文本保留于 `LICENSE.GPL-3.0.txt`。素材来源见 [素材清单](web/public/reliquary/LICENSES.md)，字体 OFL 文本随字体保留。
