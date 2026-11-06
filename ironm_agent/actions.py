"""动作工具（spec [2026-10-23] §120）：改计划、新计划、记训练由管家调用工具交给系统，跟着规程一起装。

规程（Skill）管怎么判断，工具管怎么做：装了排训练计划（plan-build）才有改计划、新计划，装了记训练与复盘
（log-review）才有记训练；规程开头的工具栏写着它带哪几个动作工具。工具这一层只收参数、计次、交给处理函数
（由 plugin 提供：套用、检查、存预览），处理结果当场交还给管家，它可以改了再交。
确认规则不变：出的是预览卡片，他确认才保存。日志只记工具名、结果和原因类别，不记内容。
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ironm_agent.body_state import STATE_SCHEMA_PROPS  # 只按管家交的写（§163）
from ironm_agent.checks import sentences

_log = logging.getLogger("ironm_agent.actions")

PLAN_EDIT = "propose_plan_edit"
NEW_PLAN = "propose_new_plan"
LOG_WORKOUT = "log_workout"
ASK_TERMS = (
    "ask_plan_terms"  # 要排新计划、先请他确认条件（取代原来 JSON 里的 "action": "new_plan"）
)
RECORD_STATE = "record_state"  # 今天的状态（§122，取代回答 JSON 里的 said）
LOG_BODY = "log_body"  # 体重、腰围这类读数进健康记录（§122）
LOG_MEAL = "log_meal"  # 对话里记一餐（§122）
ADJUST_TODAY = "adjust_today"  # 只改今天这一次训练（§122）
KCAL_CHANGE = "propose_kcal_change"  # 调每日热量目标（§122）
REMEMBER = "remember"  # 记忆（§145，取代回答 JSON 里的 memory）
SET_GOAL = "propose_goal"  # 改正式目标：目标类型和目标体重，出卡片确认（§151）
TEMP_CHANGE = "propose_temporary_change"  # 这几天临时这样练：带起止日期，出卡片确认，到期回到原计划（§163）
DIET_PLAN = "propose_diet_plan"  # 换饮食方案：从方案库挑一份，按热量目标算份数，出卡片确认（§190）
ACTION_TOOLS = (
    PLAN_EDIT, NEW_PLAN, LOG_WORKOUT, ASK_TERMS, RECORD_STATE, LOG_BODY, LOG_MEAL, ADJUST_TODAY,
    KCAL_CHANGE, REMEMBER, SET_GOAL, TEMP_CHANGE, DIET_PLAN,
)  # fmt: skip
ALWAYS = (
    RECORD_STATE,
    LOG_BODY,
    LOG_MEAL,
    REMEMBER,
    SET_GOAL,
)  # 他随时可能说到：每一轮都给（§122、§145）
UNCOUNTED = (RECORD_STATE, REMEMBER)  # 不占动作次数
AFTER = (RECORD_STATE, REMEMBER)  # 作答时不给：回答发出后由管家在后台读这句话再记（§166，省一轮往返）
MAX_ACTIONS = 6  # 每轮最多调用几次动作工具（不占查询次数；记今天的状态、记忆不算）

_DAY = "1 到 7，1 是周一"
_ITEM = {
    "type": "object",
    "properties": {
        "exercise": {"type": "string", "description": "动作名"},
        "sets": {"type": "integer", "description": "组数"},
        "reps": {"type": "string", "description": "次数，如 8–12"},
        "load": {"type": "string", "description": "重量或强度说明，不超过 15 个字，可空"},
        "note": {"type": "string", "description": "要点或限制，不超过 15 个字，可空"},
    },
    "required": ["exercise", "sets", "reps"],
}
_PLAN = {
    "type": "object",
    "description": "完整的每周计划（改现有计划时没改的部分照抄，不是只写改动）",
    "properties": {
        "title": {"type": "string", "description": "计划名，不超过 12 个字"},
        "goal": {"type": "string", "description": "目标"},
        "days_per_week": {"type": "integer", "description": "每周几练"},
        "sessions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "day": {"type": "integer", "description": _DAY},
                    "name": {"type": "string", "description": "这一次练什么，如下肢"},
                    "minutes": {"type": "integer", "description": "大概多少分钟"},
                    "items": {
                        "type": "array",
                        "items": _ITEM,
                        "description": "最多 6 个动作，热身和放松不写成动作",
                    },
                },
                "required": ["day", "name", "minutes", "items"],
            },
        },
    },
    "required": ["title", "goal", "days_per_week", "sessions"],
}

PLAN_EDIT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": PLAN_EDIT,
        "description": (
            "改他现有的训练计划：只交要改的地方，系统套到当前计划上、检查后出预览卡片（他确认才保存），结果会告诉你。"
            "每条操作是六种之一（day 写 1 到 7，1 是周一；exercise 写当前计划里那天现有的动作名）："
            '{"kind": "swap", "day": 哪天, "exercise": "原动作", "to": "换成的动作", "why": "原因"}；'
            '{"kind": "move", "day": 哪天, "to_day": 挪到哪天, "why": "原因"}；'
            '{"kind": "add", "day": 哪天, "exercise": "加的动作", "sets": 组数, "reps": "次数", "why": "原因"}；'
            '{"kind": "edit", "day": 哪天, "exercise": "动作", "sets": 组数, "reps": "次数", "load": "重量说明", "why": "原因"}'
            '（只写要改的字段；改这天的时长写 {"kind": "edit", "day": 哪天, "minutes": 分钟}）；'
            '{"kind": "remove", "day": 哪天, "exercise": "动作（删整天时不写）", "why": "原因"}；'
            '{"kind": "reduce", "day": 哪天（整份计划都减时不写）, "ratio": 0.7 或 0.5, "why": "原因"}。'
            '要把某天改成练另一天正在练的内容（周三练推、周五练拉，"周三改成练背"）：用 move 把这两天对调，这是首选；'
            "要把某天改成练计划里没有的内容：用 swap 把那天的动作逐个换掉，原来那类动作要保留就用 add 加到别的训练日"
            "（一周里原来练到的胸、背、腿、臀、肩不能全丢掉）；删一个动作用 remove；edit 只改组次、重量、时长。"
            "swap 的 to、add 的 exercise 写你实际要换成的具体动作名（他没有杠铃就写哑铃版的）；给他的话和操作说的要是同一个动作。"
            "他没提到的地方一律不动；他的几条要求互相矛盾时照原话都写成操作，不要自己取舍，系统会请他说清楚。"
            "要重新排、换分化、六种说不清时，不用这个，用 propose_new_plan。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ops": {"type": "array", "items": {"type": "object"}, "description": "操作列表"},
                "busy": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "他说了哪几天没空（出差、有事），1–7；挪动不挪到那几天；没说写 []",
                },
                "scope": {
                    "type": "string",
                    "enum": ["once", "always", "unclear"],
                    "description": "他说了只改这一次写 once，说了以后都这样写 always，没说清写 unclear",
                },
            },
            "required": ["ops"],
        },
    },
}

NEW_PLAN_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": NEW_PLAN,
        "description": (
            "交一份完整的每周训练计划（新排、重排、换分化），系统检查后出预览卡片（他确认才保存），结果会告诉你；"
            "检查没过会把问题告诉你，改好再交一次。动作、组次、时长都要符合档案：器械、可练时间、伤病"
            "（有伤病的动作在 note 里写明限制或换掉）、今天的身体状态；每次最多 6 个动作。"
            "kind 写 new（他要新排一份：没有计划、要重来、长期条件变了）或 rewrite（在现有计划上换分化、整份重排）；"
            "new 而本会话还没确认过排新计划的条件时，系统不会出预览，会让你先列条件请他确认。"
            "照 plan_templates 给的草稿排的：不用抄整份 plan，写 template（草稿的方案编号）和 ops（要改的地方，"
            "写法同 propose_plan_edit 的操作，不用改就不写），系统套到草稿上再检查。交的时候系统会检查，不用先调 check_plan。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "plan": _PLAN,
                "template": {"type": "string", "description": "照方案库草稿交时：草稿的方案编号（写了就不用写 plan）"},
                "ops": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "照草稿交时要改的地方，写法同 propose_plan_edit；不用改就不写",
                },
                "changes": {
                    "type": "string",
                    "description": '一句话：这份计划是怎么排的、改了什么（如"周三从上肢推改成练背"）',
                },
                "kind": {
                    "type": "string",
                    "enum": ["new", "rewrite"],
                    "description": "new：新排一份（要先确认条件）；rewrite：在现有计划上换分化、整份重排",
                },
            },
            "required": ["changes", "kind"],  # plan 和 template 二选一（§165）
        },
    },
}

LOG_WORKOUT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": LOG_WORKOUT,
        "description": (
            "把他说的这次训练记下来：系统出预览卡片，他确认才记，结果会告诉你。"
            "记录里的数字只能来自他的话，他没说的就不填（写 null），不要猜。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "日期，默认今天，YYYY-MM-DD"},
                "session": {
                    "type": "string",
                    "description": "按计划练的是哪一次（档案里当前计划那次的名字），没有就空",
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "exercise": {"type": "string", "description": "动作名"},
                            "sets": {"type": ["integer", "null"], "description": "组数"},
                            "reps": {"type": "string", "description": "次数"},
                            "weight_kg": {
                                "type": ["number", "null"],
                                "description": "重量（公斤）",
                            },
                            "done_sets": {
                                "type": "array",
                                "items": {"type": "object"},
                                "description": '每组不同时逐组写 [{"reps": 次数, "weight_kg": 重量或 null}]，否则空列表',
                            },
                        },
                        "required": ["exercise"],
                    },
                },
                "done": {"type": "boolean", "description": "是否练完"},
                "rpe": {"type": ["integer", "null"], "description": "感受 1–10，他说了才写"},
                "minutes": {"type": ["integer", "null"], "description": "时长（分钟）"},
                "note": {"type": "string", "description": '备注（如"有点累"），可空'},
            },
            "required": ["items"],
        },
    },
}

ASK_TERMS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": ASK_TERMS,
        "description": (
            "他要一份新计划、但本会话还没确认过排新计划的条件时调用（不用交计划）：这一轮先请他确认条件，"
            "系统据此认出你在确认条件，下一轮他回「按这个排」时再交计划。"
        ),
        "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
    },
}

_CATEGORIES = ["injury", "special", "equipment", "schedule", "diet", "preference", "goal", "level",
               "style", "event", "followup"]  # fmt: skip
_JOINTS = ["joint.shoulder", "joint.elbow", "joint.wrist", "joint.cervical", "joint.lumbar", "joint.hip",
           "joint.knee", "joint.ankle"]  # fmt: skip
REMEMBER_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": REMEMBER,
        "description": (
            "他这句话说了关于他本人、以后要照顾到的情况时调用，一次可以交几条；提问、闲聊、别人的事、假设、否定的说法不记，"
            "已有的不重复记。只写他说了的：问句带出的不算（「肌酐高了怎么办」「久坐圆肩怎么改善」不记）；你的安排不写进去；"
            "圆肩驼背是体态不是 injury。一顿饭、一次训练不记（那是 log_meal、log_workout）。"
            "伤病（injury）写 parts、side（他说了左右才写）、哪些动作会疼 triggers、不能做的 avoid；"
            "孕期、心脏病、糖尿病、高血压、近期手术记成 special，写 codes（几种都写）。器械（equipment）说了在哪练写 place、有什么写 gear；可练时间（schedule）写 per_week、days、minutes。系统按原话核对部位，对不上会退回。"
            "目标方向（减脂、增肌……）和目标体重用 propose_goal，goal 记忆只记力量、动作、比赛这类目标和为什么。"
            "short 的（今天累、这周出差）系统记成近期的事，until：\"这周\"写周日、\"这两天\"写明天，看不出写 7 天后。"
            "长期的情况变了 update 那一条；他说好了、结束了、取消了，resolve 还在生效的近况和跟进，不新增\"已结束\"。"
            "答应回访、他要你提醒的记 followup；\"该问的、到期的跟进\"里你提了或他答了，用编号 resolve。"
            "画像里推测的（带？）他说对了、或长期的情况他说还是这样，按编号 confirm（quote 写他的原话，content 不写）；"
            "推测的他说不对，resolve 那条。"
            "系统先按规则核一遍，没通过的会告诉你原因；回答写完后再核对才写入。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": ["add", "update", "resolve", "confirm"]},
                            "target": {"type": "string", "description": "已有记忆编号（add 不写）"},
                            "category": {"type": "string", "enum": _CATEGORIES},
                            "content": {"type": "string", "description": "一句话≤40字，留部位左右重量时间"},
                            "quote": {"type": "string", "description": "他原话里一字不差的一段"},
                            "inferred": {"type": "boolean", "description": "推测的写 true"},
                            "lasting": {"type": "string", "enum": ["long", "short"],
                                        "description": "long（一直要照顾）或 short（某一天、这几天）"},
                            "until": {"type": "string", "description": "event、followup 的截止日 YYYY-MM-DD"},
                            "parts": {"type": "array", "items": {"type": "string", "enum": _JOINTS},
                                      "description": "injury：哪个关节（肩、手肘、手腕、颈椎、腰椎、髋、膝、踝），要是他说到的"},
                            "side": {"type": "string", "enum": ["左", "右", "两侧"],
                                     "description": "injury：左右；他没说就不写"},
                            "kind": {"type": "string", "enum": ["旧伤", "急性", "慢性", "术后"]},
                            "severity": {"type": "string", "enum": ["轻", "中", "重"]},
                            "triggers": {"type": "array", "items": {"type": "string"},
                                         "description": "injury：哪些动作会疼（他说的），如[\"深蹲\"]"},
                            "avoid": {"type": "array", "items": {"type": "string"},
                                      "description": "injury：不能做的（他或医生说的），如[\"跳跃\"]"},
                            "codes": {"type": "array", "items": {"type": "string", "enum": [
                                "pregnancy", "cardiac", "diabetes", "hypertension", "surgery"]},
                                      "description": "special（伤病里顺带说了也写）：孕期、心脏病、糖尿病、高血压、近期手术"},
                            "place": {"type": "string", "enum": ["gym", "home", "both"],
                                      "description": "equipment：在哪练（健身房、家里、都有）"},
                            "gear": {"type": "array", "items": {"type": "string", "enum": [
                                "哑铃", "壶铃", "弹力带", "杠铃", "单杠", "器械"]},
                                     "description": "equipment：有哪些（他说到的）；器械＝健身器械"},
                            "custom": {"type": "array", "items": {"type": "string"},
                                       "description": "equipment：上面没有的器材（如划船机），他说的原名"},
                            "per_week": {"type": "integer", "description": "schedule：每周能练几次"},
                            "days": {"type": "array", "items": {"type": "integer"},
                                     "description": "schedule：哪几天（1 是周一）"},
                            "minutes": {"type": "integer", "description": "schedule：每次多少分钟"},
                        },
                        "required": ["op"],
                    },
                },
            },
            "required": ["items"],
        },
    },
}  # fmt: skip

SET_GOAL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": SET_GOAL,
        "description": (
            "他说要换目标方向（减脂、增肌、增力、耐力、健康）或定目标体重和日期时调用：交了出一张改目标的预览卡片，"
            "写明热量会怎么变，他点确认才改个人中心的目标和目标体重。只交他说了的；问句、假设不交；"
            "力量、动作、比赛这类目标和为什么用 remember 记。他没说日期就先问一句，不要替他定。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "type": {"type": "string", "enum": ["fat_loss", "muscle", "strength", "endurance", "health"],
                         "description": "目标方向：减脂、增肌、增力、耐力、健康"},
                "value": {"type": "number", "description": "目标体重，他说的数（说斤写斤的数，unit 写斤）"},
                "unit": {"type": "string", "enum": ["公斤", "斤"]},
                "by": {"type": "string", "description": "目标日期 YYYY-MM-DD（按他说的几个月、哪天算）"},
                "why": {"type": "string", "description": "一句话：为什么改，像当面对他说"},
            },
        },
    },
}  # fmt: skip

RECORD_STATE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": RECORD_STATE,
        "description": (
            "他这句话说了自己今天的状况时调用（只写他说了的；问话、假设、别人的不写）：生病的症状和轻重、病好了没有、累、"
            "昨晚睡了几小时、今天能练多少分钟、状态好、哪里疼（部位、左右、在做哪个动作、多疼）。"
            "系统只按你交的写，不再自己从他的话里认；他说了却没交，就当没说。"
        ),
        "parameters": {"type": "object", "additionalProperties": False, "properties": STATE_SCHEMA_PROPS},
    },
}

LOG_BODY_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": LOG_BODY,
        "description": (
            "他说了自己量的体重、体脂率、腰围、静息心率、血压时调用：写进健康记录（数据页能改、删）。"
            "数只能是他这句话里说的，不换算、不猜；问句、假设、别人的不记。一个数调用一次。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["weight", "body_fat", "waist", "resting_hr", "systolic", "diastolic"],
                    "description": "体重（公斤）、体脂率（%）、腰围（厘米）、静息心率、收缩压、舒张压",
                },
                "value": {"type": "number", "description": "他原话里的数（说的是斤就写斤的数）"},
                "unit": {
                    "type": "string",
                    "enum": ["公斤", "斤"],
                    "description": "体重他说的单位，默认公斤",
                },
                "day": {"type": "string", "description": "哪天量的，YYYY-MM-DD；不写是今天"},
            },
            "required": ["kind", "value"],
        },
    },
}

LOG_MEAL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": LOG_MEAL,
        "description": (
            "他说了自己今天吃了什么时调用，记进今天的饮食记录（同一种餐今天只留一份；饮食页能改份量、删掉）。你只说哪一餐、有哪些食物、"
            '各多少克（按他说的量估，"一碗米饭"约 150 克）、炒菜和外卖的油量；热量由系统按食物库算，不用你算。'
            "库里可能没有的食物再给每 100 克的估值。结果会告诉你这一餐多少热量、今天还能吃多少。问吃什么、打算吃的、昨天以前吃的不记。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["早餐", "午餐", "晚餐", "加餐", "夜宵", "练前", "练后"],
                },
                "name": {"type": "string", "description": '这一餐的简短名字，如"牛肉面"'},
                "foods": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "常见叫法，如米饭、番茄炒蛋"},
                            "grams": {"type": "number", "description": "吃下去的克数"},
                            "portions": {
                                "type": "number",
                                "description": "他说的是几碗、几个、几盘时写份数（如米饭 1、包子 2），系统按食物库里一份的克数算，不用写 grams",
                            },
                            "oil": {"type": "string", "enum": ["少油", "正常", "多油"]},
                            "per100": {
                                "type": "object",
                                "description": "每 100 克的估值 {kcal, protein_g, carbs_g, fat_g}，库里没有时才用",
                            },
                        },
                        "required": ["name"],  # grams 和 portions 写一个（复核 11-05）
                    },
                },
            },
            "required": ["kind", "foods"],
        },
    },
}

ADJUST_TODAY_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": ADJUST_TODAY,
        "description": (
            "只改今天这一次训练（原计划不变，计划页能恢复今天原样）。只在他同意了你提的改法、或者明确要你改今天时调用；"
            "只是问今天练不练、你还在建议时不调用。可以换动作、改组次、去掉某个动作，或者整体按几成练（ratio 0.5–0.9，"
            "每个动作的组数按比例减）。换的动作系统会查器械和伤处，不合适会退回。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["swap", "edit", "remove"]},
                            "exercise": {
                                "type": "string",
                                "description": "今天那一次里现有的动作名",
                            },
                            "to": {"type": "string", "description": "swap 换成的动作"},
                            "sets": {"type": "integer", "description": "edit 改成几组"},
                            "reps": {"type": "string", "description": "edit 改成几次"},
                        },
                        "required": ["kind", "exercise"],
                    },
                },
                "ratio": {"type": "number", "description": "整体按几成练，0.5–0.9；不减就不写"},
            },
        },
    },
}

KCAL_CHANGE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": KCAL_CHANGE,
        "description": (
            "调他的每日热量目标（饮食页能撤销）。只在他同意了你提的调整、或者明确要求时调用。"
            "系统按上下限执行：累计调整不超过 ±500 千卡、不低于基础代谢和安全下限，结果会告诉你实际调到多少。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "delta": {
                    "type": "integer",
                    "description": "每天多吃（正数）或少吃（负数）多少千卡",
                },
                "reason": {"type": "string", "description": "一句话原因"},
            },
            "required": ["delta", "reason"],
        },
    },
}

TEMP_CHANGE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TEMP_CHANGE,
        "description": (
            "这几天临时这样练（出差只有哑铃、病后这一周减量、某个动作先停几天）：写开始和结束日期、改法、原因，"
            "系统套到当前计划上、检查后出临时调整的预览卡片，他确认才生效，过了结束日期自动回到原计划。"
            "改法写法和 propose_plan_edit 的 ops 一样（swap、move、add、edit、remove、reduce）。"
            "他说以后都这样就不用这个，用 propose_plan_edit 改计划本身；只改今天这一次用 adjust_today。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "start": {"type": "string", "description": "从哪天开始，YYYY-MM-DD（今天或以后）"},
                "end": {"type": "string", "description": "到哪天为止（含这天），YYYY-MM-DD，最长 28 天"},
                "ops": {"type": "array", "items": {"type": "object"}, "description": "改法列表，同 propose_plan_edit"},
                "why": {"type": "string", "description": "一句话原因，像当面对他说"},
            },
            "required": ["start", "end", "ops", "why"],
        },
    },
}

DIET_PLAN_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": DIET_PLAN,
        "description": (
            "把他的饮食计划（首页\"今天吃什么\"照着排的工作日、周末四顿）换成饮食方案库里的一份：交方案编号，"
            "系统按他的热量目标算好每顿几份，出一张预览卡片，他点确认才换，换了能撤销一次。"
            "他说想换、或者目标变了现在的计划对不上（档案里饮食计划的热量和热量目标差得多）时用；"
            "先用 diet_templates 看过目录和那一份，挑适合他目标和情况的。只能交方案库里的，不要自己编计划。"
            "孕期、未成年、肾病、糖尿病在用药的不交，先建议他问医生。没确认前计划没换，不要说已经换了。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "plan": {"type": "string", "description": "方案库里那一份的编号（如 bulk-home）"},
                "why": {"type": "string", "description": "一句话：为什么换这份，像当面对他说"},
            },
            "required": ["plan"],
        },
    },
}


SCHEMAS = {
    PLAN_EDIT: PLAN_EDIT_SCHEMA,
    NEW_PLAN: NEW_PLAN_SCHEMA,
    LOG_WORKOUT: LOG_WORKOUT_SCHEMA,
    ASK_TERMS: ASK_TERMS_SCHEMA,
    RECORD_STATE: RECORD_STATE_SCHEMA,
    LOG_BODY: LOG_BODY_SCHEMA,
    LOG_MEAL: LOG_MEAL_SCHEMA,
    ADJUST_TODAY: ADJUST_TODAY_SCHEMA,
    KCAL_CHANGE: KCAL_CHANGE_SCHEMA,
    REMEMBER: REMEMBER_SCHEMA,
    SET_GOAL: SET_GOAL_SCHEMA,
    TEMP_CHANGE: TEMP_CHANGE_SCHEMA,
    DIET_PLAN: DIET_PLAN_SCHEMA,
}
_CONFIRMED = (
    f"他刚回应了你列的条件清单，算确认，不要再问一遍：调用 {NEW_PLAN}（kind 写 new）交计划，他改了哪几项就按改了的排；"
    "他明说还没定（比如还要想想）才照他的话答、不交计划。"
)
_TERMS = "好，这一轮不交计划：回答以「排新计划前先确认一下」开头，把条件（目标、场景、器械、时间、伤病）列给他确认。"

# 回答里说已经做了：已经改好、帮你换成了、记下了、把周三挪到周四了……按句子看。
# 建议、问句、否定、说以前的事不算："可以换成""要不要我帮你记下？""不用改了""计划里周三之前改成了练背"
_CLAIM = re.compile(
    r"(?:已经|已|帮你|给你|这就|按你说的)[^。！？；\n]{0,12}?"
    r"(?:改好|改了|改成了|换成了|换好|换了|调了|挪到了|挪好|删掉了|删了|减好|排好|排了|记下|记好|记上|记录好|记录了|调整好|调好)"
    r"|(?:改好|记下|记好|排好|调整好|换好|记上|挪好)了"
    r"|(?:换成|挪到|改成|删掉|减到)[^。！？；\n，,]{1,12}?了"
)
_LOGGED = re.compile(r"记下|记好|记上|记录")  # 说的是记训练；其余算改计划
_CLAUSE = re.compile(r"[^，,、：:。！？；!?\n]+[。！？；!?]?")  # 分句带上句末的问号，问句照样认得出
# 同一个分句里有这些就不算：问句、建议、提议、否定、说以前的事（"计划里"不排除：宁可多提醒一次）
_NOT_CLAIM = re.compile(
    r"[吗？?]|就好了|就行了|就可以了|也行了"
    r"|可以|建议|要不要|需要的话|如果|要是|能不能|想不想"
    r"|不用|不必|无需|别|没|不要"
    r"|之前|上次|以前|原来|确认过"
)
_HIS = re.compile(r"(?<![帮给按])你")  # 主语是他："你已经换了两次分化"不是说系统改了
NUDGE_CLAIM = (
    "（系统核对，不是用户说的）你的回答里说已经改了或记下了，但这一轮没有成功调用对应的工具"
    f"（改计划 {PLAN_EDIT}、{NEW_PLAN}，只改今天 {ADJUST_TODAY}，调热量 {KCAL_CHANGE}，记训练 {LOG_WORKOUT}，"
    f"记一餐 {LOG_MEAL}，记体重这类数 {LOG_BODY}，记他的伤病、器械这类情况 {REMEMBER}；"
    "没有的先用 load_skill 装对应的规程）。"
    "要改就调用工具；不改就改口，不要说已经改了、记下了。"
)
NUDGE_PLAN = (
    "（系统核对，不是用户说的）他刚确认了排新计划的条件，这一轮要调用 "
    f"{NEW_PLAN} 交一份完整的计划；他其实换了话题的，就照他的话题答，不交计划。"
)
_LIMIT = "这一轮动作已经交了好几次，不能再交了；按已有的结果跟他说。"


def claimed(text: str) -> set[str]:
    """回答里说已经做了哪几种：plan（改了、排了计划）、log（记下了训练）。"""
    out: set[str] = set()
    for clause in _CLAUSE.findall(text):  # 按分句看：后面那句是建议、问句不影响前面说已经改了
        m = _CLAIM.search(clause)
        if m is None or _NOT_CLAIM.search(clause) or _HIS.search(clause[: m.start()]):
            continue
        out.add("log" if _LOGGED.search(m.group(0)) else "change")
    return out


# 记录类（记训练、一餐、读数、今天的状态）任何一样做成，说"记下了"都算；修改类（改计划、只改今天、调热量）同理。
# 细分到哪一样容易把常见回答判错、整段删掉（复核 11-03："记下了……今天的训练减到七成"被当成记训练）
_MET_BY = {
    "log": {"workout", "meal", "body", "state", "memory"},
    "change": {"plan", "today", "kcal"},  # 改目标只出了卡片、还没改，不算"改好了"（复核 11-03）
}


def unsatisfied(claims_: set[str], done: set[str]) -> set[str]:
    """说了做了、这一轮却没做成的那几种。"""
    return {k for k in claims_ if not _MET_BY.get(k, {k}) & done}


NOT_DONE = "这次没改成，也没记下来；你再说一次具体想怎么做，我来处理。"


def strip_claims(text: str, done: Iterable[str] = ()) -> str:
    """去掉说已经改了、记下了、其实没做成的那几句（做成了的那种留着）；全去掉了就如实说没做成。"""
    kept = [s for s in sentences(text) if not unsatisfied(claimed(s), set(done))]
    return "".join(kept).strip() or NOT_DONE


@dataclass(frozen=True)
class Outcome:
    """一次动作交给系统的结果。"""

    ok: bool
    text: str  # 交还给管家的话
    reason: str = (
        ""  # 退回的原因类别（日志、运行记录用），如 format / conflict / check / special / confirm
    )
    kind: str = ""  # 出了预览：plan / log；直接记下：saved（一餐、读数）；直接改了：changed（今天、热量）；state
    what: str = ""  # 做成的是哪一种（核对"说了做却没做"用）：meal / body / today / kcal / state
    note: str = ""  # 给他看的一句（没答出来时告诉他这一轮已经做了什么）
    cards: tuple[dict[str, Any], ...] = ()
    draft: str = ""  # 存下的预览编号
    calc: str = ""  # 系统算出来的数（一餐的热量、新的热量目标）：登记成计算结果，回答里能引〔C编号〕（复核 11-05）
    extra: dict[str, Any] = field(default_factory=dict)  # 处理函数之间传的数（改目标的新热量目标，§190），不给管家看


type Handler = Callable[["Desk", Mapping[str, Any]], Awaitable[Outcome]]


@dataclass
class Desk:
    """一轮里的动作工具：哪些装上了、调了几次、出了哪些预览、退回了几次。"""

    handlers: Mapping[str, Handler]
    has_plan: bool = False
    enabled: bool = True  # 危急情况这一轮不给动作工具（§5）
    must_plan: bool = False  # 他刚确认了排新计划的条件：没交计划时提醒一次
    unlocked: set[str] = field(default_factory=set)
    calls: int = 0
    rejected: Counter[str] = field(default_factory=Counter)  # 原因类别 → 次数
    plan: Outcome | None = None  # 这一轮最后一张计划预览
    goal: Outcome | None = None  # 这一轮最后一张改目标预览（§151）
    diet: Outcome | None = None  # 这一轮最后一张换饮食方案预览（§190）
    temps: list[Outcome] = field(default_factory=list)  # 这一轮出的临时调整预览（§163）
    logs: list[Outcome] = field(default_factory=list)
    saved: list[Outcome] = field(default_factory=list)  # 直接记下的：一餐、读数（§122）
    changed: list[Outcome] = field(default_factory=list)  # 直接改了的：今天、热量（§122）
    said: dict[str, Any] = field(
        default_factory=dict
    )  # 今天的状态，作答后写入（§122，原来的 said）
    memory: list[dict[str, Any]] = field(
        default_factory=list
    )  # 这一轮交的记忆，回答写完后核对写入（§145，原来回答里的 memory）
    memory_ok: Callable[[str], bool] | None = None  # 按回答核对记忆有没有通过的长期情况
    stale: list[str] = field(default_factory=list)  # 同一轮被后一张换掉的计划预览编号（要作废）
    replaced: list[str] = field(
        default_factory=list
    )  # 被这一轮接着改掉的上一轮预览：他看到新的之后才作废
    fallback: Callable[[], Awaitable[Outcome]] | None = (
        None  # 检查没过被退回的那份：没再交时用它出预览
    )
    ask_new_plan: bool = False  # 交了新计划但条件还没确认
    template_plans: dict[str, Any] = field(default_factory=dict)  # 这一轮方案库给的草稿：方案编号 → 计划（§165）
    on_calc: Callable[[str], str] | None = None  # 把系统算出来的数登记成计算结果，返回编号（Toolbox 接上）
    withheld: frozenset[str] = frozenset()  # 这一轮不给的（§166：记状态、记忆放到回答后），装规程也不开
    nudged: bool = False
    unacted: bool = False  # 说了改却没改，删了那几句
    trace: list[dict[str, str]] = field(default_factory=list)

    def allowed(self, name: str) -> bool:
        need = NEW_PLAN if name == ASK_TERMS else name  # 能交新计划才能先确认条件
        return self.enabled and need in self.handlers and (name != PLAN_EDIT or self.has_plan)

    def unlock(self, toolset: Iterable[str]) -> list[str]:
        """装上一份规程：它带的动作工具开放给管家，返回这次新开放的。"""
        new = [n for n in toolset if n in SCHEMAS and self.allowed(n) and n not in self.unlocked
               and n not in self.withheld]  # fmt: skip
        self.unlocked.update(new)
        return new

    def schemas(self) -> list[dict[str, Any]]:
        return [SCHEMAS[n] for n in ACTION_TOOLS if n in self.unlocked]

    @property
    def done(self) -> bool:
        return bool(self.done_kinds)

    @property
    def kinds(self) -> list[str]:
        """出了哪几种预览卡片（各配一句确认说明）。"""
        return ((["plan"] if self.plan is not None else []) + (["log"] if self.logs else [])
                + (["goal"] if self.goal is not None else []) + (["temp"] if self.temps else [])
                + (["diet"] if self.diet is not None else []))  # fmt: skip

    @property
    def done_kinds(self) -> set[str]:
        """做成了哪几种（核对"说了做却没做"用）：plan、workout、meal、body、today、kcal、state。"""
        out = {"plan"} if self.plan is not None else set()
        out |= {"workout"} if self.logs else set()
        out |= {"state"} if self.said else set()
        out |= {"goal"} if self.goal is not None else set()
        out |= {"temp"} if self.temps else set()
        out |= {"diet"} if self.diet is not None else set()
        return out | {x.what for x in (*self.saved, *self.changed) if x.what}

    def done_note(self) -> str:
        """这一轮已经直接记下、改了的（没答出来、退回固定说法时也告诉他，免得再说一遍又记一次）。"""
        got = [x.note or x.text for x in (*self.saved, *self.changed)]
        return "这一轮已经做了：" + "；".join(got) + "。" if got else ""

    @property
    def cards(self) -> list[dict[str, Any]]:
        out = list(self.plan.cards) if self.plan is not None else []
        for x in self.logs:
            out += x.cards
        out += [c for x in self.temps for c in x.cards]
        out += list(self.goal.cards) if self.goal is not None else []
        return out + (list(self.diet.cards) if self.diet is not None else [])  # 改目标在前：先确认目标再换饮食

    @property
    def tried_plan(self) -> bool:
        """这一轮想改计划或交新计划（不管成没成、给没给这个工具）。"""
        return any(x["tool"] in (PLAN_EDIT, NEW_PLAN, ASK_TERMS) for x in self.trace)

    @property
    def drafts(self) -> list[str]:
        out = [self.plan.draft] if self.plan is not None and self.plan.draft else []
        out += [self.goal.draft] if self.goal is not None and self.goal.draft else []
        out += [self.diet.draft] if self.diet is not None and self.diet.draft else []
        out += [x.draft for x in self.temps if x.draft]
        return out + [x.draft for x in self.logs if x.draft]

    async def run(self, name: str, args: Mapping[str, Any]) -> str:
        if name not in self.unlocked:
            self._note(name, "locked")
            if name == REMEMBER:  # 暂停记忆、系统拼的问法：不记，也不用装规程（复核 11-03）
                return (
                    "这一轮不记记忆（他暂停了记忆，或这句话不是他自己说的），不用再调，直接作答。"
                )
            return f"现在没有 {name} 这个工具；要用先装带它的规程（load_skill）。"
        if name == ASK_TERMS:  # 只是标记它在确认条件，不存东西、不计次
            if self.must_plan:  # 他刚回应了条件清单：算确认，该交计划了（真实模型回放 11-03）
                self._note(name, "confirmed")
                return _CONFIRMED
            self.ask_new_plan = True
            self._note(name, "ok")
            return _TERMS
        if name not in UNCOUNTED:  # 记今天的状态、记忆不计次
            self.calls += 1
        if self.calls > MAX_ACTIONS:
            self._note(name, "limit")
            return _LIMIT
        try:
            out = await self.handlers[name](self, args)
        except Exception as e:  # 存不了预览不影响回答
            _log.warning("action failed: tool=%s error_type=%s", name, type(e).__name__)
            self._note(name, "error")
            return "这次系统没能处理，没改成；如实跟他说这次没改成、可以再说一次。"
        if not out.ok:
            self.rejected[out.reason or "other"] += 1
            if out.reason == "confirm":
                self.ask_new_plan = True
            self._note(name, out.reason or "other")
            return out.text
        self.accept(out)
        self._note(name, "ok")
        if out.calc and self.on_calc is not None:  # 登记成这一轮的计算结果，告诉它编号
            return f"{out.text}（引用这些数时句末写〔{self.on_calc(out.calc)}〕）"
        return out.text

    def accept(self, out: Outcome) -> None:
        """记下一张出了的预览；同一轮后一张计划换掉前一张。"""
        if out.kind == "plan":
            if self.plan is not None and self.plan.draft and self.plan.draft != out.draft:
                self.stale.append(self.plan.draft)
            self.plan = out
        elif out.kind == "log":
            self.logs.append(out)
        elif out.kind == "goal":  # 同一轮后一张改目标换掉前一张
            if self.goal is not None and self.goal.draft and self.goal.draft != out.draft:
                self.stale.append(self.goal.draft)
            self.goal = out
        elif out.kind == "diet":  # 同一轮后一张换饮食方案换掉前一张
            if self.diet is not None and self.diet.draft and self.diet.draft != out.draft:
                self.stale.append(self.diet.draft)
            self.diet = out
        elif out.kind == "temp":
            self.temps.append(out)
        elif out.kind == "saved":
            self.saved.append(out)
        elif out.kind == "changed":
            self.changed.append(out)

    async def finish(self) -> None:
        """这一轮结束：计划检查没过被退回、它没再交，按交上来的那份出预览（同原来改一次不成照出，§12）。"""
        if self.plan is None and self.fallback is not None:
            try:
                out = await self.fallback()
            except Exception as e:
                _log.warning("action fallback failed: error_type=%s", type(e).__name__)
                return
            if out.ok:
                self.accept(out)
                self._note(NEW_PLAN, "fallback")

    def _note(self, name: str, result: str) -> None:
        self.trace.append({"tool": name, "result": result})
        _log.info("action: tool=%s result=%s", name, result)  # 只有工具名和结果类别

    def followup(self, answer: str) -> str | None:
        """管家写完回答后核对一次：刚确认了条件却没交计划、说了改却没改，提醒它一次（只提醒一次）。"""
        if self.nudged:
            return None
        if (
            self.must_plan
            and self.plan is None
            and not self.ask_new_plan
            and self.allowed(NEW_PLAN)
        ):
            self.unlocked.add(NEW_PLAN)
            self.nudged = True
            return NUDGE_PLAN
        if self.unmet(answer):
            self.nudged = True
            return NUDGE_CLAIM
        return None

    def unmet(self, answer: str) -> set[str]:
        """说了做了、这一轮却没做成的那几种（改计划和记训练分开看）。记了记忆要按回答核对通过才算（§145）。"""
        done = self.done_kinds | self._after()
        if self.memory and self.memory_ok is not None and self.memory_ok(answer):
            done = done | {"memory"}
        return unsatisfied(claimed(answer), done)

    def _after(self) -> set[str]:
        """§166：记状态、记忆放到回答后由系统记，说"记下了"不算没做（不再提醒、不删那句）。"""
        return {"state", "memory"} if self.withheld & set(AFTER) else set()

    def settle(self, answer: str) -> str:
        """提醒过还是说了改却没改：去掉那几句。"""
        if not self.unmet(answer):
            return answer
        self.unacted = True
        return strip_claims(answer, self.done_kinds | self._after())
