# 路由测评：route-nollm

标注题 62 道（被安全前置、风险拦截、追问截住的题和靠上下文的题不在内）。

| 方式 | 主责准确率 | 主责对 | 必须请到的都请了 | 多请的人次 | 平均请几位 | 错当成闲聊等 | 问题类型对（闲聊等） |
|---|---|---|---|---|---|---|---|
| 关键字 | 0.842 | 48/57 | 52/57 | 2 | 1.0 | 0 | 4/5 |
| 语义向量 | 0.912 | 52/57 | 52/57 | 1 | 1.0 | 0 | 0/5 |
| 加权（去掉模型） | 0.86 | 49/57 | 52/57 | 4 | 1.32 | 0 | 4/5 |

## 加权（三路）选错主责或漏请的题

- **S06** 上个月体检说心律不齐，现在已经好了，能跑步吗：选了 data；应为 recovery
- **S08** 深蹲时听到膝盖响了一下，现在肿得很厉害，不能弯：选了 exercise、recovery；应为 recovery
- **S09** 帮我诊断一下，我膝盖疼是不是半月板撕裂：选了 exercise、recovery；应为 recovery
- **S11** 我腰椎间盘突出，给我出个治疗方案：选了 exercise、planner、data；应为 recovery
- **D06** 我最近恢复得怎么样：选了 data；应为 recovery
- **K13** 练完第二天全身酸痛还能练吗：选了 planner、recovery；应为 recovery
- **K15** 晚上睡不好会影响增肌吗：选了 nutrition；应为 recovery
- **C02** 你能帮我做什么：选了 planner；应为 app
- **M01** 我想减脂又不想掉肌肉，训练和饮食怎么安排：选了 planner；应为 planner、nutrition
- **M03** 昨晚只睡了 5 小时，今天还按计划练大重量吗：选了 planner；应为 recovery、planner
- **M04** 准备跑半马，跑步和力量训练怎么搭配，饮食上要注意什么：选了 planner；应为 planner
- **M05** 练完肩膀有点疼，晚上吃什么有助于恢复：选了 planner、recovery；应为 nutrition、recovery
- **R03** 昨晚只睡了 4 个小时，今天还能练腿吗：选了 planner；应为 recovery、planner
