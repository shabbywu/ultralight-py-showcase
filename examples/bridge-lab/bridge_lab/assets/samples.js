window.SAMPLES = [
 {id:'sync', title:'同步函数', expected:'42；改成 30 + 22 得到 52', code:'const value = lab.add(20, 22);\nprint(value);'},
 {id:'async', title:'异步 Promise', expected:'request started → result: 42', code:"print('request started');\nconst value = await lab.delayed_double(21, 150);\nprint('result:', value);"},
 {id:'object', title:'实例属性', expected:'before: 0 → after: 2', code:"print('before:', lab.counter.value);\nlab.counter.increment(2);\nprint('after:', lab.counter.value);"},
 {id:'container', title:'实时容器', expected:'length: 1 / last: 7 / snapshot: [7] / from Python: 1 / shared: true 7 true', code:"const history = lab.counter.history;\nhistory.push(7);\nprint('length:', history.length);\nprint('last:', history.at(-1));\nprint('snapshot:', JSON.stringify(history));\nlab.counter.increment();\nprint('from Python:', history.at(-1));\nconst items = [], options = {enabled: false};\nconst result = lab.counter.share(items, options);\nprint('shared:', result === items, items[0], options.enabled);"},
 {id:'error', title:'异常传播', expected:'caught: 真实 Python 除零异常', code:"try {\n  lab.divide(1, 0);\n} catch (error) {\n  print('caught:', error.message);\n}"},
 {id:'snapshot', title:'实时字典', expected:'Bridge Lab / true / 完整 JSON', code:"const profile = lab.get_profile();\nprint('name:', profile.name);\nprint('keys visible:', Object.keys(profile).length > 0);\nprint(JSON.stringify(profile));"}
];
