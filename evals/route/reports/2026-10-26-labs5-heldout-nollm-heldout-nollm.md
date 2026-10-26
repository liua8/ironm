# 路由测评：labs5-heldout-nollm-heldout-nollm

标注题 48 道（被安全前置、风险拦截、追问截住的题和靠上下文的题不在内）。

| 方式 | 主责准确率 | 主责对 | 必须请到的都请了 | 多请的人次 | 平均请几位 | 错当成闲聊等 | 问题类型对（闲聊等） |
|---|---|---|---|---|---|---|---|
| 关键字 | 0.714 | 30/42 | 36/42 | 7 | 1.0 | 0 | 1/6 |
| 语义向量 | 0.929 | 39/42 | 37/42 | 1 | 1.0 | 0 | 0/6 |
| 加权（去掉模型） | 0.881 | 37/42 | 38/42 | 5 | 1.29 | 0 | 1/6 |

## 加权（三路）选错主责或漏请的题

- **N07** 我这一个月掉了几斤：选了 trainer、nutrition；应为 nutrition
- **N10** 夏天跑步出汗多要不要补电解质：选了 trainer；应为 nutrition
- **R02** 网球肘还能练上肢吗：选了 trainer；应为 recovery、trainer
- **R03** 落枕了今天还能去健身房吗：选了 trainer；应为 recovery
- **R05** 跑步时突然胸口发闷要紧吗：选了 trainer；应为 recovery
- **R06** 做完臀桥腰有点酸是正常的吗：选了 trainer；应为 recovery、trainer
- **R10** 我早上的心跳比平时快了十几下：选了 trainer、recovery；应为 recovery
- **X02** 膝盖做过手术，现在想减肥，怎么运动怎么吃：选了 trainer；应为 recovery、trainer、nutrition
- **X04** 准备参加健美比赛，备赛期怎么练怎么吃：选了 trainer；应为 trainer、nutrition
- **O02** 你们这个是怎么收费的：选了 trainer；应为 app
- **O03** 帮我写一首关于春天的诗：选了 trainer；应为 out_of_scope
- **O04** 辛苦啦，今天就到这：选了 trainer；应为 chat
- **O05** 我的数据你们存在哪里：选了 trainer、nutrition；应为 app
- **O06** 明天天气怎么样：选了 trainer；应为 out_of_scope
