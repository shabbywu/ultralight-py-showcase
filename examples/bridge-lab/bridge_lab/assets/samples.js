window.SAMPLES = [
 {id:'sync', title:'同步函数', expected:'42；改成 30 + 22 得到 52', code:'const value = lab.add(20, 22);\nprint(value);'},
 {id:'async', title:'异步 Promise', expected:'request started → result: 42', code:"print('request started');\nconst value = await lab.delayed_double(21, 150);\nprint('result:', value);"},
 {id:'object', title:'实例属性', expected:'before: 0 → after: 2', code:"print('before:', lab.counter.value);\nlab.counter.increment(2);\nprint('after:', lab.counter.value);"},
 {id:'container', title:'实时容器', expected:'length: 1 / last: 7 / snapshot: [7]', code:"const history = lab.counter.history;\nhistory.append(7);\nprint('length:', Python.len(history));\nprint('last:', Python.getitem(history, -1));\nprint('snapshot:', JSON.stringify(Python.to_value(history)));"},
 {id:'error', title:'异常传播', expected:'caught: 真实 Python 除零异常', code:"try {\n  lab.divide(1, 0);\n} catch (error) {\n  print('caught:', error.message);\n}"},
 {id:'snapshot', title:'字典快照', expected:'Bridge Lab / true / 完整 JSON', code:"const profile = lab.get_profile();\nconst plain = Python.to_value(profile);\nprint('name:', plain.name);\nprint('is plain JS:', Object.keys(plain).length > 0);\nprint(JSON.stringify(plain));"}
];
