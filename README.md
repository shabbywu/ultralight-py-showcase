# ultralight-py Showcase

ultralight-py 的示例展示站与源码入口，展示 Python 逻辑与 JavaScript 界面在原生桌面中的协作。

| 示例 | 状态 | 源码组织 |
| --- | --- | --- |
| [Emberkeep](https://github.com/shabbywu/emberkeep) | 已实现：像素 roguelike | `examples/emberkeep`，固定版本的 submodule |
| [Bridge Lab](examples/bridge-lab/README.md) | 规划中：交互式桥接实验室 | 预留 `examples/bridge-lab`，后续在本仓库开发 |

展示站是静态页面。原生示例需要桌面环境，其依赖、运行和验证说明由各项目独立维护。

## 获取示例

```sh
git clone --recurse-submodules https://github.com/shabbywu/ultralight-py-showcase.git
cd ultralight-py-showcase
```

已有 checkout 获取示例：

```sh
git submodule update --init --recursive
```

独立仓库使用固定版本的 submodule；本仓库开发的示例放在 `examples/` 的独立目录。
