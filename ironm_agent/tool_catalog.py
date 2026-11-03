"""AI 健身管家的工具清单（spec [2026-10-23] §25）：mirobody 和 iron-m 的工具放在一起看。

每个工具写明：对话里哪些专业角色能用（agent 名字，空表示对话里不用）、在 MCP 上叫什么（空表示不在 MCP 上）、
读不读本人的数据、来自哪里、备注。有测试检查这份清单和实际登记的一致。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tool:
    title: str
    source: str  # iron-m / mirobody
    agent: str = ""  # 对话里给专业角色用时的工具名
    roles: frozenset[str] = frozenset()  # 能用的角色
    mcp: str = ""  # 在 MCP 上的名字
    personal: bool = False  # 读不读本人的数据
    note: str = ""


EXPERTS = frozenset({"trainer", "nutrition", "recovery", "general"})

CATALOG: tuple[Tool, ...] = (
    # ---- iron-m ----
    Tool("健身知识库", "iron-m", "search_knowledge", EXPERTS, "search_fitness_knowledge",
         note="对话里每个角色只查自己领域的资料"),
    Tool("时间线", "iron-m", "timeline", frozenset({"general"}), personal=True,
         note="生病、伤病和近期的事、说疼、训练、管家的调整按日期排在一起，只读（§97）"),
    Tool("联网搜索（白名单）", "iron-m", "search_web", frozenset({"general"}),
         note="知识库查不到时由管家决定联网查权威机构（§91）；配了 TAVILY_API_KEY 才有，结果标未审"),
    Tool("动作库", "iron-m", "search_exercises", frozenset({"trainer", "recovery", "general"}),
         "search_exercises"),
    Tool("指标计算", "iron-m", "compute_metrics", EXPERTS, personal=True,
         note="BMI、基础代谢、热量和蛋白质目标等；对话里一般直接用共享档案里的结果"),
    Tool("估算最大重量与该用多重", "iron-m", "estimate_strength", frozenset({"trainer", "general"}),
         "estimate_strength", personal=True),
    Tool("训练计划检查", "iron-m", "check_plan", frozenset({"trainer", "general"}),
         "check_training_plan", personal=True),
    Tool("选初步方案", "iron-m", "plan_templates", frozenset({"trainer", "general"}),
         "plan_templates", personal=True, note="从方案库挑方案、按器械和伤病换动作，做成计划草稿（§77）"),
    Tool("训练规律汇总", "iron-m", "training_patterns", frozenset({"trainer", "recovery", "general"}),
         "training_patterns", personal=True),
    Tool("替代动作", "iron-m", "find_substitutes", frozenset({"trainer", "recovery", "general"}),
         "find_substitutes", personal=True),
    Tool("营养计算", "iron-m", "nutrition_calc", frozenset({"nutrition", "general"}),
         "nutrition_calc", personal=True),
    Tool("疼痛判断", "iron-m", "pain_check", frozenset({"recovery", "general"}), "pain_check",
         personal=True, note="运动场景分流，不做诊断"),
    Tool("指标趋势", "iron-m", "trend_analysis", EXPERTS, "trend_analysis", personal=True),
    Tool("综合解读", "iron-m", "explain_trends", EXPERTS, "explain_trends", personal=True,
         note="和自己比、和标准比，认出的情况、可能的原因和自动调整（§84）"),
    # 动作工具（§120）：跟着规程装，只给管家；改数据都出预览、他确认才保存，不在 MCP 上
    Tool("交改计划", "iron-m", "propose_plan_edit", frozenset({"general"}), personal=True,
         note="装了排训练计划才有；只交改动，代码套用、检查后出预览"),
    Tool("交新计划", "iron-m", "propose_new_plan", frozenset({"general"}), personal=True,
         note="装了排训练计划才有；没确认条件不出预览，检查没过退回一次"),
    Tool("先确认排计划的条件", "iron-m", "ask_plan_terms", frozenset({"general"}),
         note="装了排训练计划才有；标记这一轮在确认条件，没列好系统用固定的五项"),
    Tool("记训练", "iron-m", "log_workout", frozenset({"general"}), personal=True,
         note="装了记训练与复盘才有；数字只来自他的话，出预览、确认才记"),
    Tool("记今天的状态", "iron-m", "record_state", frozenset({"general"}), personal=True,
         note="每轮都给；取代回答里的 said，作答后写今日状态、生病和说疼的记录（§122）"),
    Tool("记身体数据", "iron-m", "log_body", frozenset({"general"}), personal=True,
         note="每轮都给；体重、腰围这类数写进健康记录，数只能是他说的（§122）"),
    Tool("记一餐", "iron-m", "log_meal", frozenset({"general"}), personal=True,
         note="每轮都给；模型认食物和克数，代码按食物库算（§122）"),
    Tool("只改今天", "iron-m", "adjust_today", frozenset({"general"}), personal=True,
         note="装了今天练不练才有；他同意或要求才调，原计划不变（§122）"),
    Tool("调热量", "iron-m", "propose_kcal_change", frozenset({"general"}), personal=True,
         note="装了饮食方案才有；累计 ±500、不低于安全下限（§122）"),
    Tool("记一条记忆", "iron-m", "remember", frozenset({"general"}), personal=True,
         note="每轮都给（暂停记忆、系统拼的问法不给）；调用时预核，回答写完再核对写入（§145）"),
    Tool("定下次目标", "iron-m", personal=True,
         note="不在对话里：记下一次训练后后台叫醒管家时才给（set_next_target）；动作要在计划里、加重不超过一成（§132）"),
    Tool("本人的训练", "iron-m", mcp="query_my_training", personal=True,
         note="对话里由共享档案提供，不作为工具"),
    Tool("本人某天的饮食", "iron-m", mcp="query_my_meals", personal=True),
    Tool("本人的目标进度", "iron-m", mcp="query_my_goal", personal=True),
    Tool("管家的当前方案与调整经历", "iron-m", mcp="query_coach_plan", personal=True,
         note="对话里由共享档案提供（§23 第 3 步）"),
    # ---- mirobody ----
    Tool("健康记录", "mirobody", "query_health_indicators", frozenset({"trainer", "nutrition", "recovery", "general"}),
         "query_health_indicators", personal=True, note="化验、体征、穿戴设备数据，本人报告的症状和日记"),
    Tool("用药记录", "mirobody", "query_medications", frozenset({"recovery", "general"}),
         "query_medications", personal=True, note="判断运动风险：降压药、胰岛素等；不建议改药"),
    Tool("医学知识", "mirobody", "search_medical_knowledge", frozenset({"recovery", "nutrition", "general"}),
         "search_medical_knowledge", note="MedlinePlus、FDA 药品说明书，联网时还有文献和临床试验；部署配置了才有"),
    Tool("读医学资料原文", "mirobody", mcp="read_medical_source", note="部署配置了才有"),
    Tool("基因数据", "mirobody", mcp="query_genetic_data", personal=True, note="不用于训练和饮食建议"),
    Tool("药物基因组", "mirobody", mcp="query_pharmacogenomics", personal=True, note="不用于训练和饮食建议"),
    Tool("检验项目名称统一", "mirobody", mcp="resolve_indicator", note="导入数据时用"),
    Tool("单位换算", "mirobody", mcp="convert_unit"),
    Tool("单位统一", "mirobody", mcp="normalize_unit"),
)  # fmt: skip
