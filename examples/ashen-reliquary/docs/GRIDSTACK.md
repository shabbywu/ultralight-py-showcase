# GridStack 背包约束评估（2026-10-21）

> 历史评估，记录替换前的中间实现。当前版本已移除 GridStack，使用独立 `packages/grid-inventory`；下文不描述当前运行依赖。

## 结论

npm `latest` 与 GitHub 最新正式版本均为 **14.0.0**。升级本身不会消除自动移位。
最新引擎的推挤、交换、自动寻位属于仪表盘布局的既定行为。
单独拦截引擎不足以稳定约束完整交互。本轮最终关闭 GridStack 内置拖拽，
由小型自有输入与占格规则接管；GridStack 暂时只作为静态渲染器，不需要换前端框架。

本次修复只落在 showcase 的 `examples/ashen-reliquary`，没有回写 Godot。
运行依赖固定为 **10.3.1**：最新版的行为在隔离安装中复现，
生产示例没有混入 14.x 的 `mode`、样式和渲染 API 迁移。
如果日后升级，需验证静态渲染／样式与引擎子类；自有拖放不调用 GridStack 私有 DD 接口。

## 最新版复现与官方契约

最小场景：6×6 网格，A 在 (0,0)，B 在 (2,0)，两者均为 2×2；请求把 B 放到 (0,0)。
实测 14.0.0 的 `mode:'float'`、`maxRow:6`：

| 配置 | A 最终位置 | B 最终位置 | 是否符合背包契约 |
| --- | --- | --- | --- |
| 不锁定 | (0,2) | (0,0) | 否，A 被推走 |
| 两者 `locked:true` | (0,0) | (0,2) | 否，B 被自动改放到另一处 |

官方 [14.0.0 发布说明](https://github.com/gridstack/gridstack.js/releases/tag/v14.0.0)
介绍了 `mode` 替换 `float`，不是新增背包模式。
[`locked` 文档](https://gridstackjs.com/doc/html/interfaces/GridStackWidget.html#locked)
承诺防止被其他物品推挤，但不等于严格拒绝当前落点。

代码依据是 [v14.0.0 engine](https://github.com/gridstack/gridstack.js/blob/v14.0.0/src/gridstack-engine.ts)
和 [v14.0.0 grid](https://github.com/gridstack/gridstack.js/blob/v14.0.0/src/gridstack.ts)。
碰撞处理、有限行数的原版 engine clone、跨栏 `autoPosition` fallback 是不同路径，
只重写 `_fixCollisions` 或只开 `float` 不足以覆盖全部入口。

可在本示例目录复现（隔离安装，不修改应用依赖）：

```sh
npm install --prefix ../../.tmp/ashen-reliquary/upstream gridstack@14.0.0 --no-audit --no-fund
cd web
node tests/upstream-audit.cjs ../../../.tmp/ashen-reliquary/upstream/node_modules/gridstack
```

本机结果保留在根 `.tmp/ashen-reliquary/gridstack-audit/v14.json`。

## 原示例的实际漏口

1. `moveNodeCheck()` 调用父实现时，有限行数路径会创建普通 `GridStackEngine`，
   子类的碰撞拦截不在那个副本上生效；它会把副本中改动过的坐标写回。
2. `_packNodes()` 在移动、删除、batch/load 等多个入口工作；`float` 不代表禁用所有整理。
3. 跨栏拖入在候选落点不合适时会尝试 `autoPosition`，主动寻找其他空位。
4. 示例自身的旋转调用 `findEmptyPosition()`，会移动旋转中的物品。
5. 原先只检查最终不重叠，没有逐帧核对未拿起物品的坐标。

## 最终实现与明确行为

曾试验引擎拦截加跨栏 admission hook：单次操作能够通过，但连续取消、非法跨栏后再拖动，
仍暴露库的 DD 清理状态残留。因此没有交付那套私有 DD 补丁，改为下列结构：

- `Inventory.vue` 设置 `staticGrid:true` / `disableDrag:true`，不注册库的跨栏接收与删除区。
- `web/src/gridstack/GridStackEngine.ts`：为 API／渲染更新提供严格矩形验证，
  关闭 pack、swap、compact；直接移动，不调用有限行数的父类 clone。
- `web/src/gridstack/dragTransaction.js`：自有鼠标输入与键盘旋转、Escape 取消。
  拖动期间仅渲染独立 ghost 和有效／无效落点高亮，所有真实库存坐标都保持拿起前状态。
  释放时验证确切矩形，成功才一次提交来源和目标；失败只移除预览，原物品自然留在原位置。
  不调用 GridStack 内置 DD、自动寻找替代位置或私有 admission hook。
- 旋转只检查当前锚点，空间不足则不生效；跨栏与原地放置都不钳位、不缩小物品、不增长背包。
- 仅显式 **New relic** 和初次填充允许为新物品找空位；
  没有连续空位时返回失败，不移动任何已有物品。原来的 `force` 绕过也已移除。
- 拖动预览不写回 Python／localStorage；提交后统一保存，丢弃是显式删除而不是自动整理。

当前实现相当于“自有背包核心与输入 + 现有 GridStack 静态外壳”。
它避免重做整套页面；未来用 CSS 定位替换静态外壳也可以保留输入和规则。
引擎子类仍需固定版本与回归约束，但交互不再依赖原库的私有拖拽状态机。

## 验证

```sh
npm test --prefix web
python -m unittest discover -s tests -v
npm run build --prefix web
python run.py --cpu --smoke --output ../../.tmp/ashen-reliquary/strict-native
python run.py --cpu --standalone --smoke --output ../../.tmp/ashen-reliquary/strict-standalone
```

纯引擎回归覆盖 7 组契约和 2,000 次确定性随机候选移动：碰撞、原地旋转、
越界／不缩放、删除／batch／compact、碎片空位及新增物品。
原生输入回归逐帧采样未拿起物品的坐标，覆盖同栏非法落点、跨栏非法落点、
越界、跨栏往返、满背包、碎片背包、新增、丢弃、Escape 取消、重载与持久化。
像素截图来自真实 CPU AppCore View，报告保留采样帧数。
浏览器 fallback 也在无 Python 桥接的原生渲染环境运行同套输入检查；
不把它冒称为 Chrome/Firefox/Safari 人工验收。当前实现只接入鼠标／键盘，触摸交互未接入；GPU、其他系统尚未验收。

## 如果未来更换：自写核心比再换仪表盘布局库更合适

| 方案 | 要维护什么 | 建议 |
| --- | --- | --- |
| 当前：自有背包输入与规则，保留 GridStack 静态渲染 | 严格矩形验证、ghost、提交和静态渲染回归 | 已实施，可继续验收 |
| 完全自写背包 model + CSS 定位 + Pointer Events | `canPlace` / `move` / `rotate` / 跨栏原子提交，以及输入与预览 | 若扩展到装备类型、堆叠、异形格、多人权威状态，优先选这个方向 |
| interact.js 管输入，自写背包 model | 网格吸附有库支持，库存占用和事务仍需自写 | 需要更复杂触摸／拖动手势时再考虑 |
| React Grid Layout 等仪表盘库 | 新框架适配、碰撞／整理模式，仍需背包规则 | 当前 Vue 2 工程没有迁移收益，不建议为了此问题换过去 |

后两项依据：interact.js 的 [snap grid](https://interactjs.io/docs/snapping/)
是输入坐标吸附能力，不能替代库存规则；
[React Grid Layout](https://github.com/react-grid-layout/react-grid-layout)
面向 React 的可拖动布局，提供碰撞／compactor 配置，但不是跨栏背包事务系统。
这两者只做文档和接口评估，本轮没有迁移或原生兼容性验证。
