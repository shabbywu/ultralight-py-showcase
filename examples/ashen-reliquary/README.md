# Ashen Reliquary

Vue 2 示例业务层接入本地 TypeScript 包 [grid-inventory](packages/grid-inventory/README.md)。运行时已移除 GridStack；纯核心不导入 DOM、Vue、Python 或 Godot。Vue 与 Vite 沿用现有版本。

界面为业务属性、人物装备、背包三栏。Ground 抽屉保留 12×12，Bag 保留 12×6；调整窗口不会重新排列物品。复用 Ashen 字体、物品和 effigy 人物素材。`web/src/business.js` 提供演示属性和装备比较，这些数值不进入框架。

[浏览器在线试玩](https://shabbywu.github.io/ultralight-py-showcase/demos/ashen-reliquary/) · 浏览器存档与 Python 存档独立。

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

原生窗口需要桌面环境、Python 3.10+ 和 ultralight-py 0.6.1。前端开发可执行 `npm run dev --prefix web -- --host 127.0.0.1`。独立静态服务执行 `python run.py --browser --port 4175`，访问 http://127.0.0.1:4175/ 。浏览器模式不导入 ultralight-py。

原生默认仅进程内保存；使用 `--state path/to/state.json` 开启跨启动持久化。浏览器使用 localStorage，与 Python 存档独立。

## 操作

- 拖动严格落格；碰撞、越界和无效目标取消。拿起后按 R 自由旋转，与当前落点是否可放置无关；落点独立显示合法性，释放时校验提交。Escape 或失焦取消。
- 双击装备／卸装；Shift 点击在 Ground、Bag 间快捷转移。双手武器占主手并引用占用副手，旧装备必须全部放回来源网格才换装。
- 拖到兼容堆叠上合并，超过上限的余量留在原处。
- 拖动堆叠时随时按下／松开 Ctrl 切换拆分，释放时确定；默认一半，滚轮调整数量。取消不生成实例。
- 把 Ember Gem 拖到 Saint-Socket 镶嵌一颗；悬停孔内宝石，点 Remove gem to Bag 摘除。已有宝石随 Saint-Breaker 移动。
- 将物品直接拖到快捷栏槽位绑定引用，已有绑定可覆盖；物品仍在原容器，绑定不拆分、不消耗；点击快捷栏激活。Ember Flask 的消耗由示例业务处理。
- Save / Retry 显式保存或重试；错误显示在状态栏。Offer to the ashes 删除选中的物品。

控制台 `Reliquary.snapshot()` 返回全量快照；`Reliquary.engine` 可查看事务预览、命令和事件；`Reliquary.view` 可检查视图生命周期。

## 快照与迁移

唯一新存档包含 `schemaVersion:1`、`revision`、全部 `containers`、`items`、`shortcuts`。定义由业务目录提供，快照不包含 HTML、DOM 或函数。位置支持 grid、slot、socket，孔通过 `owner` 关联装备。快捷栏只保存 item/action 引用。

首次读取旧存档时，只按已知素材文件名识别定义，保留实例 ID、坐标、数量与朝向。无法识别的物品、无效坐标或重复 ID 阻止加载，具体错误显示到状态栏，不自动覆盖原存档。浏览器保留旧 localStorage 键；Python 首次写入迁移后的快照前保留 `.legacy.bak`。Python 继续先写临时文件，再原子替换；写入失败回滚内存状态并允许重试。

## 验收

```sh
npm test --prefix web
npm run check --prefix packages/grid-inventory
python -m unittest discover -s tests -v
python run.py --cpu --smoke --width 1440 --height 1000
python run.py --cpu --standalone --smoke --width 1440 --height 1000 --output ../../.tmp/ashen-reliquary/standalone
```

核心回归包括原子失败、修订号、数量守恒、拆分取消、两件装备回装与满空间失败、镶嵌与摘除、快捷栏重定向、业务拒绝、加载校验、500 次边界操作与 1000 次固定种子随机事务。前端会话测试覆盖迁移、重载和未知物品不覆盖旧存档。Python 测试覆盖全量快照、备份、原子落盘和失败重试。

原生 smoke 使用真实 `View.mouse_down/mouse_move/mouse_up`、键盘及焦点事件，逐帧确认无关物品不变，包括缩放、鼠标回退、hover 与视图销毁，并输出实际像素 PNG 和 JSON 报告。分别执行 Python 桥接与独立 localStorage 模式。原生输入验收不代表桌面浏览器验收；本轮按用户要求使用 ultralight-py，桌面浏览器未执行。

默认报告位于仓库根 `.tmp/ashen-reliquary/`。smoke 使用隔离存档，不读写日常 `--state`。

本轮结果见 [验收记录](docs/ACCEPTANCE.md)。

Godot 不在本轮修改，回移契约见 [GODOT_ADAPTER.md](docs/GODOT_ADAPTER.md)。历史布局库调查保留在 [GRIDSTACK.md](docs/GRIDSTACK.md)，不再描述当前实现。

## 来源

保留上游 GPL v3 文本于 `LICENSE.GPL-3.0.txt`；美术、字体与历史依赖许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

拆分操作：拖动物品堆时可随时按下或松开 Ctrl，以释放鼠标时是否按住 Ctrl 决定拆分或整堆移动。拆分默认一半；拖拽中滚轮向上增加、向下减少数量（1 至原数量减 1）。释放到合法空位才提交，Escape、失焦或无效落点均取消。切换 Ctrl 保留已调整的拆分数量。Shift 点击仍为快捷转移。
