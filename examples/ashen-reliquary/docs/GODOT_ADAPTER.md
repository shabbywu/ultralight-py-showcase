# Godot 回移契约（本轮不修改 C# 示例）

共享 `packages/grid-inventory`、Vue 页面、业务定义、business 模块和素材。去掉原先每个背包的宿主对象，不移植旧布局类或继承关系。Vue 不升级。

宿主提供：

| 方法 | 输入 | 返回 |
|---|---|---|
| load_snapshot | 无 | 全量快照 JSON 字符串；首次启动返回 `null` JSON |
| save_snapshot | 全量快照 JSON 字符串 | 成功完成；失败抛出可显示异常 |

旧 `load_layout(name)` 仅作为一次性迁移读取接口，返回旧记录数组或 `null` JSON。迁移成功前不得覆盖旧文件。新快照通过 schemaVersion、revision 管理，保存使用临时文件后原子替换；不再逐背包保存。宿主不计算布局，也不保存 HTML。JSON 类型详见包的 `Snapshot`。

所有物品移动、装备、堆叠、镶嵌与消费通过 `engine.execute(command | commands[], expectedRevision?)`；宿主需要发命令时透传 Command 的 JSON 字段。先 `preview`，再以其 revision 执行原命令；不得把预览结果当命令提交。失败返回 `ok:false,code,message`。一次事务只订阅一次 change 进行全量保存。定义、接收规则和业务效果由应用注册，不通过 JSON 传函数。

回移检查：

1. 将 Python/浏览器存储适配替换为以上 Godot 桥接，保持核心与 DOM 包原样。
2. C# ItemDB 对齐业务定义 ID、尺寸、旋转、槽位与堆叠上限；实例 ID 不变。
3. 八装备槽、socket owner 和快捷栏引用必须一起恢复；双手武器只有一份实例。
4. 提供旧布局读取和备份；未知素材或非法状态显示具体错误，不自动重置。
5. 重新运行全部纯核心测试，补充 Godot 真实鼠标、键盘、焦点和 DPI 验收。
6. 单独验证 Godot 保存失败可重试、重载后恢复、桥接异常以及打包后的资源路径。

不包含网络同步、战斗结算、异形占格、嵌套背包、触摸或手柄。
