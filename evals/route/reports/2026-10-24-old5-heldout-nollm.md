# 路由测评：old5-heldout-nollm

标注题 48 道（被安全前置、风险拦截、追问截住的题和靠上下文的题不在内）。

| 方式 | 主责准确率 | 主责对 | 必须请到的都请了 | 多请的人次 | 平均请几位 | 错当成闲聊等 | 问题类型对（闲聊等） |
|---|---|---|---|---|---|---|---|
| 关键字 | 0.738 | 31/42 | 35/42 | 6 | 1.0 | 0 | 1/6 |
| 语义向量 | 0.881 | 37/42 | 37/42 | 3 | 1.0 | 0 | 0/6 |
| 加权（去掉模型） | 0.762 | 32/42 | 37/42 | 8 | 1.38 | 0 | 1/6 |

## 加权（三路）选错主责或漏请的题

- **N05** 左旋肉碱真的能减肥吗：选了 data、planner、nutrition；应为 nutrition
- **N08** 体脂率从二十五降到二十要多久：选了 data；应为 nutrition
- **N10** 夏天跑步出汗多要不要补电解质：选了 planner；应为 nutrition
- **R02** 网球肘还能练上肢吗：选了 planner；应为 recovery、planner、exercise
- **R03** 落枕了今天还能去健身房吗：选了 planner；应为 recovery
- **R04** 踝关节扭伤一周了，什么时候能恢复跑步：选了 planner、recovery；应为 recovery
- **R05** 跑步时突然胸口发闷要紧吗：选了 exercise、planner；应为 recovery
- **R06** 做完臀桥腰有点酸是正常的吗：选了 exercise；应为 recovery、planner、exercise
- **R07** 最近总是睡不醒，白天没精神：选了 data、recovery；应为 recovery
- **R10** 我早上的心跳比平时快了十几下：选了 planner、data；应为 recovery、data
- **R11** 来例假的时候能不能练：选了 planner、recovery；应为 recovery
- **X02** 膝盖做过手术，现在想减肥，怎么运动怎么吃：选了 exercise；应为 recovery、planner、exercise、nutrition
- **X04** 准备参加健美比赛，备赛期怎么练怎么吃：选了 exercise、planner；应为 planner、exercise、nutrition
- **X05** 体重一个月没动了，是训练还是饮食的问题：选了 data；应为 nutrition、planner、exercise
- **O02** 你们这个是怎么收费的：选了 data；应为 app
- **O03** 帮我写一首关于春天的诗：选了 planner；应为 out_of_scope
- **O04** 辛苦啦，今天就到这：选了 planner；应为 chat
- **O05** 我的数据你们存在哪里：选了 data；应为 app
- **O06** 明天天气怎么样：选了 exercise；应为 out_of_scope
