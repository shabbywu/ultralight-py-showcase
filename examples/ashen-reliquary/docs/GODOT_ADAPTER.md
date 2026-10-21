# Godot / Ultralight 后端接入

Python 示例采用后端权威模型。Godot Sample 2 可复用 `web/` 界面与 DOM 视图，C# 实现同样的类型模型、原子能力和业务接口。前端不持有权威状态。

## 自底向上的类型边界

- `models.py`：`Position`、`Item`、`Definition`、`Container`、`Snapshot`、`Success/Failure` 等 dataclass，枚举描述容器种类、事件和失败码。
- `inventory.py`：`Inventory` 持有并校验完整状态；`InventoryTransaction` 提供增删、移动、拆分、合并、消费、绑定和寻找位置等原子方法。候选与权威状态隔离，完整校验成功后才提交。
- `game.py`：组合原子方法，实现装备冲突回装、自动选槽、转移、镶嵌、快捷栏效果和随机生成。这里决定游戏业务，不在 Inventory 中分发字符串命令。
- `codec.py`：仅在磁盘和桥接边界解析／编码字典，不把动态记录传入领域层。
- `bridge.py`：公开显式标注参数的方法，不接受通用 Command、批量字典或前端快照。

JSON 只用于文件持久化。桥接使用原生标量参数与独立对象副本。前端使用 `Python.to_value()` 将返回值转成普通 JS 数据；Godot 应提供等价的深复制转换。

## 应用接口

Python 在 `inventory.backend` 注册一个应用对象。以下方法的 Python 签名是具体协议，C# 应逐个实现；每个写方法的最后一个参数为可选 `expected_revision: int`。

| 方法 | 参数（不含 expected_revision） | 业务职责 |
|---|---|---|
| `create_relic()` | 无 | 后端选择定义、生成 ID、放置并提交 |
| `move_item()` | item_id, container_id, x, y, rotation | 精确移动 |
| `remove_item()` | item_id | 删除物品及其 socket 子树 |
| `split_stack()` | item_id, quantity, container_id, x, y, rotation | 后端分配新身份并拆分 |
| `merge_stacks()` | item_id, target_id | 合并与引用重定向 |
| `equip_item()` | item_id, slot_id | 装备并原子回装冲突物品 |
| `equip_best_slot()` | item_id | 自动选兼容槽或卸装回 Bag |
| `transfer_item()` | item_id | 按业务规则选择目标网格 |
| `socket_gem()` | item_id, socket_id | 镶嵌一颗宝石 |
| `unsocket_gem()` | item_id, container_id | 摘除并合并或找空位 |
| `bind_item()` | key, item_id | 绑定现有物品引用 |
| `activate_shortcut()` | key | 根据后端引用执行业务效果 |

除 `create_relic` 外，上述操作各有对应的 `preview_方法名`，参数不包含 revision。预览不提交、不分配永久 ID、不发事件。

`definitions` 返回物品定义；`read()` 返回 `{snapshot, attributes, dirty, persistenceError}`；`comparison(item_id)` 返回装备属性差值或说明；`save()` 只重试后端当前状态的保存；`host_name()` 返回显示名称。

没有 `dispatch(dict | list)`、`load(snapshot)` 或 `save_snapshot(snapshot)`。页面没有添加任意物品或直接消费任意数量的接口。前端拖拽使用的 TypeScript Command 仅存在于 DOM 视图内部，适配层将它转换成明确的应用方法调用；不会把 Command 字典发送给后端。

## 事务与通知

后端事务顺序：组合原子操作 → 完整校验候选 → 替换权威状态 → 尝试持久化 → 发布 `stateChanged`。调用方传入的旧 revision 被拒绝；失败不提交、不通知。

New relic 不依赖页面点击：宿主游戏逻辑直接调用 `Game.create_relic()`，同样触发界面更新。

后端通过受作用域管理的 JSValue 发出 DOM 事件：

```js
window.dispatchEvent(new CustomEvent("inventory-changed", {
  detail: { type: "stateChanged", revision: 1 }
}));
```

前端先订阅，再 `read()`；每次通知重新读取展示副本并替换渲染状态。修改副本不会写回后端，也不依赖 Vue 观察宿主对象。命令返回成功不被视为前端自行提交状态的依据。

`persistenceChanged` 表示保存重试状态。保存失败保留已提交游戏状态，标记 dirty 并显示错误。文件先写临时路径，再原子替换；成功后才更新已保存副本。加载时先严格解码，再由 Inventory 完整校验领域状态。

页面重载保留宿主状态和单个事件通道，新页面订阅后读取当前快照；窗口关闭解除宿主订阅。Godot 需单独验证真实输入、焦点、DPI、保存失败及打包资源路径。
