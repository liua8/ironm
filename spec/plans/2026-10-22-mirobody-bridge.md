# iron-m 第一步：mirobody 底座接上 IronM Agent 实施计划

> **已调整（2026-10-22，项目负责人决定）**：IronM 只沿用 Agent 的设计思路，不搬 IronM 的代码。本计划的 Task 1（建项目与数据库）、Task 3（运行 mirobody）已按本文件完成；Task 2、4、5、6、7 作废，替换 Agent 的工作另写规格与计划。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建项目 iron-m，在本机把 mirobody 跑起来，通过它官方的 Agent 插件接口接上 IronM 的多 Agent 问答系统。做到在 mirobody 自带的网页上提问，由 IronM 作答，回答能引用 mirobody 里的健康数据，点开引用能看到是哪天、哪条数据。

**Architecture:**
- **mirobody 不改源码**：作为 git 子模块固定在 1.5.8（提交 `7775b50`），以可编辑方式安装。
- **IronM 代码迁入 iron-m**：从 IronM 提交 `2be2826` 做快照迁入，这是已提交的状态，不含另一个会话尚未提交的改动。
- **新增桥接层 `ironm/bridge/`**：
  - 实现 mirobody 的 `mirobody.agents` 插件；
  - 每轮先从 mirobody 读这个人近 30 天的健康数据统计（每行带引用编号 rid）；
  - 再把读到的数据交给 IronM 的问答链路，作为"健康记录"工具的事实；
  - 最后把 IronM 的回答转成 mirobody 的流式块，健康数据的依据写成 `<statement>…<cite>[r3]</cite></statement>`，网页据此显示可点开的来源。
- **IronM 的数据暂时还在它自己的 SQLite 文件里**：对话记忆、画像、运行记录都在这里。§25"IronM 自己的数据建在同一个库"是下一步。

**Tech Stack:** Python 3.13 + uv；mirobody 1.5.8（FastAPI、asyncpg、LangChain 由它自带）；PostgreSQL 18 + pgvector 0.8.6（用 micromamba 从 conda-forge 装在项目目录内，不需要管理员权限）；git-lfs；IronM 现有依赖（pydantic v2、pyyaml、pytest、mypy、ruff、import-linter）。

**Spec:**
- `spec/spec.md` 的 `[2026-10-22]` §25（Task 1 从 IronM 仓库复制过来），以及 §13、§15、§19；
- 对照依据：IronM 仓库 `docs/对比_基于mirobody改造_v1.0.md`（该文件不进版本库，执行者在本机读）。

## Global Constraints

- **Python 与依赖**：Python `>=3.13`；mirobody 固定在子模块 `vendor/mirobody`，提交 `7775b50`（版本 1.5.8）。**不修改 `vendor/mirobody` 下任何文件**。确实需要改时停下来，登记原因并请项目负责人确认（spec §25 约束、§23 第 20 项）。
- **许可**：mirobody 的 LICENSE、NOTICE 与版权声明原样保留。iron-m 自身的许可证由项目负责人另定，本计划不加。
- **密钥**：密钥只放 `.env`（不进版本库，权限 600），只从环境变量读取；不写进配置、结果和日志，也不打印。
- **日志**：日志与运行记录不含健康数据原文和用户原话，只记编号、计数、耗时和类型名。
- **测试**：测试一律不调用真实模型和真实的 mirobody 数据库；真实服务只在 Task 7 的端到端脚本里用。
- **急症**：急症与拒答仍用固定回答，这次请求不调用任何模型（spec §15）。
- **端口**：
  - 数据库只监听 `127.0.0.1:55432`；
  - mirobody 开发服务用 `127.0.0.1:18090`；
  - 不用 8765，那个端口常有别人开着的 IronM 服务。
- **种子数据**：只用合成数据（脚本生成，固定随机种子），不用任何真实用户数据。
- **提交**：
  - 提交说明用中文，结尾带 `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`；
  - 不推送，远端仓库由项目负责人以后决定；
  - 仓库将来可能公开，不得包含团队内部信息。
- **语言**：面向用户的文字一律用中文。

## Review Focus

1. **这个人在 mirobody 里没有任何健康数据时**问"我最近睡得怎么样"：应如实说没有记录，不出现编出来的数字，也不出现 `<cite>`。由 Task 5 的测试覆盖。
2. **读 mirobody 数据出错时**（数据库断开、查询报错）：IronM 照常作答，多一条"没读到你的健康数据"的提示，不整轮失败，不把异常原文给用户。由 Task 6 的测试覆盖。
3. **消息不是一段纯文字时**（多段内容、只有附件、空消息）：取出其中的文字部分；没有文字时给提示，不调用链路。由 Task 6 的测试覆盖。
4. **同一个人同时开两个对话**：两轮并发执行都能完成；SQLite 连接在各自的工作线程里打开，不跨线程共用。由 Task 6 的测试覆盖。
5. **苹果与其他设备的心率变异性**（SDNN 和 RMSSD）：作为两条不同的事实显示，名称里标明算法，不合并、不比较。由 Task 4 的测试覆盖。

---

## 文件结构

```
iron-m/
  .gitignore  .env.example  README.md  CLAUDE.md  Makefile  pyproject.toml
  vendor/mirobody/                 git 子模块，提交 7775b50，不改
  scripts/pg.sh                    本机数据库：install / init / start / stop / check
  scripts/run_mirobody.sh          读 .env，从 vendor/mirobody 目录启动 `mirobody dev`
  scripts/seed_health.py           给演示账号写入 30 天合成的可穿戴数据
  scripts/e2e_chat.py              真实服务上的端到端核对（登录、提问、解析引用）
  spec/spec.md  spec/testing.md    第二版需求（来自 IronM 的 [2026-10-22] 块）
  spec/plans/                      本计划
  ironm/ rules/ config/ migrations/ schemas/ sim/ evals/ tools/ tests/
                                   来自 IronM 提交 2be2826 的快照
  ironm/contracts/records.py       新：健康记录事实的契约（纯数据）
  ironm/agents/tools.py            改：新增"健康记录"工具；ToolInput 带上健康记录
  ironm/agents/answering.py        改：数据分析师、恢复师可用这个工具；answer_as 透传健康记录
  ironm/orchestrator/chat.py       改：ChatDeps 增加 records 字段
  ironm/orchestrator/opinions.py   改：把 deps.records 交给 answer_as
  ironm/api/runtime.py             新：从 create_app 抽出的问答运行时（启动时加载一次）
  ironm/api/app.py                 改：改用 ChatRuntime，行为不变
  ironm/bridge/__init__.py
  ironm/bridge/records.py          新：从 mirobody 取健康数据统计，生成带 rid 的事实
  ironm/bridge/render.py           新：把 ChatReply 转成 mirobody 的流式块
  ironm/bridge/agent.py            新：IronMAgent，mirobody 的 Agent 插件
  tests/bridge/                    新：桥接层测试
```

`ironm/bridge` 是最上层，只有它能导入 `mirobody`。`ironm/contracts/records.py` 不依赖 mirobody。把这两条写进 pyproject 的 import-linter 契约。

---

### Task 1：建立 iron-m 项目与本机数据库

**Files:**
- Create: `.gitignore`、`.env.example`、`README.md`、`CLAUDE.md`、`Makefile`、`scripts/pg.sh`、`spec/spec.md`、`spec/testing.md`
- Create: 子模块 `vendor/mirobody`

**Interfaces:**
- Produces:
  - `scripts/pg.sh {install|init|start|stop|check}`；
  - 连接串 `postgres://ironm:${PG_PASSWORD}@127.0.0.1:55432/mirobody`；
  - `make pg-start`、`make pg-stop`。

- [ ] **Step 1：初始化仓库与子模块**

```bash
cd <iron-m 目录> && git init -b main
git submodule add https://github.com/thetahealth/mirobody vendor/mirobody
git -C vendor/mirobody checkout 7775b50
```

预期：`git -C vendor/mirobody log -1 --format=%h` 输出 `7775b50`。

- [ ] **Step 2：安装 git-lfs，拉取 mirobody 的词表数据**

- 到 git-lfs 的 GitHub 发布页下载 darwin-arm64 包。选发布满两周以上的最新版本，并用发布页给出的 sha256 校验。
- 只把 `git-lfs` 可执行文件放进 `~/.local/bin`，然后运行：

```bash
git lfs install --local && git -C vendor/mirobody lfs pull
```

预期：`git -C vendor/mirobody lfs ls-files` 列出的文件不再是指针，体积为数 MB 以上。

- [ ] **Step 3：写 `scripts/pg.sh`**

- `install`：
  - 下载 micromamba（osx-arm64，发布页提供 sha256，需校验）到 `~/.local/bin`；
  - 运行 `micromamba create -y -p .pg/env -c conda-forge postgresql=18 pgvector=0.8.6`。
- `init`：
  - `initdb -D .pg/data -U ironm --pwfile=<(printf %s "$PG_PASSWORD") -A scram-sha-256`；
  - 在 `postgresql.conf` 里写 `listen_addresses='127.0.0.1'` 和 `port=55432`；
  - 建库 `mirobody`。
- `start`、`stop`：用 `pg_ctl`，日志写 `.pg/log`。
- `check`：用 `psql` 在库 `mirobody` 里执行 `CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS pgcrypto;`，然后打印 `SELECT extversion FROM pg_extension WHERE extname='vector'`。
- 脚本从 `.env` 读 `PG_PASSWORD`。读不到就报错退出，不使用默认密码。

- [ ] **Step 4：写 `.gitignore`、`.env.example`、`Makefile`**

- `.gitignore`：`.env`、`.pg/`、`data/`、`.venv/`、`__pycache__/`、`docs/`。
- `.env.example`：只列变量名，不写值：
  - `PG_PASSWORD`、`JWT_KEY`、`CONFIG_ENCRYPTION_KEY`、`DEEPSEEK_API_KEY`、`MOONSHOT_API_KEY`、`SILICONFLOW_API_KEY`；
  - `IRONM_DB_PATH`、`IRONM_RULES_DIR`、`IRONM_MODELS_PATH`、`IRONM_KB_DIR`。
- `Makefile` 目标：`env`、`pg-install`、`pg-init`、`pg-start`、`pg-stop`、`setup`、`check`、`test`、`run`、`seed`、`e2e`。其中：
  - `env`：用 `openssl rand -hex` 生成 `.env`，内容是上面的密钥与路径，模型密钥留空；然后执行 `chmod 600 .env`。
  - `setup`、`check`、`test`、`run`、`seed`、`e2e`：本步先放占位，后续任务填写。

- [ ] **Step 5：写需求与约定文件**

- `spec/spec.md`、`spec/testing.md`：
  - 文件头照抄 IronM 的两个文件头；
  - 正文复制 IronM 仓库工作区中两文件的 `[2026-10-22]` 日期块；
  - 其中 §24（IronM 旧网页版的整理）只保留标题，下面写一行"本节属于 IronM 仓库的旧网页版，不适用于本项目"；
  - 块的开头加一行"来源：IronM 仓库 spec，2026-10-22"。
- `CLAUDE.md` 写明以下约定：
  - 需求在 `spec/`，按日期块对应；
  - 先写 spec 再动手；
  - `vendor/mirobody` 不改；
  - 仓库将来可能公开，内部信息和真实数据不进库；
  - 提交说明的格式；
  - 回复用中文。
- `README.md` 写三件事：这个项目是什么、怎么启动（引用 Makefile 目标），以及对 mirobody（Apache-2.0）的致谢。

- [ ] **Step 6：验证数据库**

```bash
make env && make pg-install && make pg-init && make pg-start && scripts/pg.sh check
```

预期：输出 `0.8.6`，且三条 `CREATE EXTENSION` 都没有报错。

- [ ] **Step 7：提交**

```bash
git add .gitignore .env.example README.md CLAUDE.md Makefile scripts/pg.sh spec .gitmodules vendor/mirobody
git commit -m "建立 iron-m：mirobody 1.5.8 作为子模块，本机 PostgreSQL 18 + pgvector 脚本，第二版需求"
```

---

### Task 2：迁入 IronM 代码快照，装好 mirobody，原有检查全部通过

**Files:**
- Create：IronM 提交 `2be2826` 的快照，包括 `ironm/`、`rules/`、`config/`、`migrations/`、`schemas/`、`sim/`、`evals/`、`tools/`、`tests/`、`.python-version`、`.editorconfig`、`.pre-commit-config.yaml`
- Create: `pyproject.toml`（以 IronM 的为底稿）

**Interfaces:**
- Produces:
  - `uv run` 环境中 `import mirobody` 和 `import ironm` 都可用；
  - `make check` 等价于 IronM 的标准检查（ruff、mypy、import-linter、pytest）。

- [ ] **Step 1：导出快照**

```bash
mkdir -p <iron-m 目录>/.import
git -C <IronM 目录> archive 2be2826 ironm rules config migrations schemas sim evals tools tests \
  .python-version .editorconfig .pre-commit-config.yaml pyproject.toml Makefile | tar -x -C <iron-m 目录>/.import
```

- 从 `.import` 里挑出代码目录和点文件搬到项目根。
- `pyproject.toml` 和 `Makefile` 不直接覆盖，作为下两步的底稿。
- 搬完删除 `.import`。
- 不带 `cs/`、`app/`、`spec/`、`.github/`、`uv.lock`。

预期：`ls ironm` 能看到 `agents api contracts core engine knowledge llm memory orchestrator rules safety scheduler skills store`。

- [ ] **Step 2：写 `pyproject.toml`**

- 在 IronM 原文件基础上改：
  - `name = "iron-m"`；
  - dependencies 增加 `"mirobody[app]"`；
  - 增加 `[tool.uv.sources] mirobody = { path = "vendor/mirobody", editable = true }`；
  - 增加 `[project.entry-points."mirobody.agents"] ironm = "ironm.bridge.agent"`，这一项在 Task 6 生效。
- import-linter 增加两条契约：
  - `ironm.bridge` 是最高层；
  - 除 `ironm.bridge` 外，任何模块都不能导入 `mirobody`（用 forbidden 契约）。
- mypy：`[[tool.mypy.overrides]] module = "mirobody.*"` 设 `follow_imports = "silent"`，不检查 mirobody 自身的代码。

- [ ] **Step 3：写 `Makefile` 的 `setup`、`check`、`test`**

- 照搬 IronM 的写法：`setup` = `uv sync`，`check` = ruff + mypy + lint-imports + pytest。
- pytest 不收集 `vendor/`：在 pyproject 的 `[tool.pytest.ini_options]` 写 `testpaths = ["tests"]`。

- [ ] **Step 4：安装并跑原有检查**

Run: `make setup && make check`

预期：全部通过。测试数与 IronM 在 `2be2826` 上运行 `make test` 的数目相同，执行者先在 IronM 仓库运行一次，记下这个数。

- [ ] **Step 5：提交**

```bash
git add -A ':!vendor' && git commit -m "迁入 IronM 代码快照（IronM 提交 2be2826），以可编辑方式依赖 mirobody 1.5.8；原有检查全部通过"
```

---

### Task 3：mirobody 在本机跑起来（自带网页 + 演示账号）

**Files:**
- Create: `scripts/run_mirobody.sh`
- Modify: `Makefile`（`run` 目标）、`.env.example`

**Interfaces:**
- Produces:
  - `make run` 在 `http://127.0.0.1:18090` 启动 mirobody 的开发服务，包括网页、接口和后台任务；
  - 演示账号 `you@mirobody.ai`，验证码 `111111`。

- [ ] **Step 1：写 `scripts/run_mirobody.sh`**

- `set -a; . ./.env; set +a`，再导出以下变量：
  - `SEED_DEMO_DATA=true`；
  - `IRONM_RULES_DIR`、`IRONM_MODELS_PATH`、`IRONM_DB_PATH`，都用项目内的绝对路径；
  - `PG_URL=postgres://ironm:${PG_PASSWORD}@127.0.0.1:55432/mirobody`。
- `cd vendor/mirobody`。必须在这个目录下启动，才能提供 `frontend/` 网页。
- 执行 `exec ../../.venv/bin/mirobody dev --port 18090`。
- 演示验证码来自 mirobody 自带 `config.yaml` 里的 `EMAIL_PREDEFINE_CODES`，不需要另配。

- [ ] **Step 2：启动并检查健康接口**

Run: 在后台运行 `make run`，然后执行 `curl -fsS http://127.0.0.1:18090/api/health`

预期：返回的 JSON 中 `version` 为 `1.5.8`。

- [ ] **Step 3：网页走查**

- 打开 `http://127.0.0.1:18090`，在"Email code"页用 `you@mirobody.ai` 和 `111111` 登录。
- 预期：能进入首页，"数据"页能看到演示账号自带的记录。
- 此时回答问题的还是 mirobody 自带的 Agent。没有模型密钥时回答失败属于预期，这一步只验证登录和数据。

- [ ] **Step 4：提交**

```bash
git add scripts/run_mirobody.sh Makefile .env.example && git commit -m "本机运行 mirobody 开发服务（端口 18090、演示账号），从子模块目录提供自带网页"
```

---

### Task 4：从 mirobody 取健康数据统计，生成带引用编号的事实

**Files:**
- Create: `ironm/contracts/records.py`、`ironm/bridge/__init__.py`、`ironm/bridge/records.py`
- Test: `tests/bridge/__init__.py`、`tests/bridge/test_records.py`

**Interfaces:**
- Produces（`ironm/contracts/records.py`，纯数据，不依赖 mirobody）:

```python
class RecordFact(ContractModel):
    rid: str          # mirobody 在本次对话里给这行数据的编号，如 "r3"
    indicator: str    # mirobody 指标名，如 "restingHeartRates"
    label: str        # 中文名，如 "静息心率"
    text: str         # 给人看的一句，如 "静息心率：近 30 天平均 58 次/分（最低 54、最高 63，共 30 条）"

class HealthSnapshot(ContractModel):
    window_days: int
    facts: tuple[RecordFact, ...] = ()
    unavailable: bool = False   # 读取出错时为 True（与"没有数据"区分）

    def citations(self, indicators: Collection[str] | None = None) -> tuple[Citation, ...]
        # kind="record", ref=f"rec:{rid}", label=fact.text, detail="来自 mirobody 的健康记录"
```

- Produces（`ironm/bridge/records.py`）:

```python
INDICATORS: dict[str, tuple[str, str, int]]   # 指标名 → (中文名, 中文单位, 小数位)
# "restingHeartRates": ("静息心率", "次/分", 0)
# "hrvRMSSD": ("心率变异性（RMSSD）", "毫秒", 0)
# "hrvSDNN": ("心率变异性（SDNN，苹果）", "毫秒", 0)
# "sleepDuration": ("睡眠时长", "小时", 1)
# "steps": ("步数", "步", 0)
# "bodyMasss": ("体重", "公斤", 1)

class RecordQuery(Protocol):
    async def envelope(self, user_info: Mapping[str, Any], **args: Any) -> Any: ...

async def fetch_snapshot(query: RecordQuery, user_id: str, session_id: str, *,
                         today: date, days: int = 30) -> HealthSnapshot
```

- **调用方式**：
  - 调用 `query.envelope({"user_id": user_id, "session_id": session_id}, indicators=list(INDICATORS), view="stats", start=(today - days + 1).isoformat(), end=today.isoformat())`；
  - 生产环境的 `query` 是 `mirobody.agent.tools.health_indicators_service.HealthIndicatorsService()`，由 Task 6 传入。
- **统计行字段**（见 mirobody `collect/query.py` 的 `_stats_row`）：`name`、`count`、`min`、`max`、`avg`、`unit`、`rid`。

- [ ] **Step 1：写失败的测试**

```python
# tests/bridge/test_records.py —— 用假的 RecordQuery，返回带 status/data 属性的对象
def test_stats_rows_become_facts_with_rids() -> None:
    snap = run(fetch_snapshot(FakeQuery(rows=[
        {"name": "restingHeartRates", "count": 30, "min": 54, "max": 63, "avg": 58.2, "unit": "/min", "rid": "r3"},
        {"name": "sleepDuration", "count": 28, "min": 5.1, "max": 8.4, "avg": 6.86, "unit": "h", "rid": "r4"},
    ]), "42", "thread-1", today=date(2026, 10, 22)))
    assert [f.rid for f in snap.facts] == ["r3", "r4"]
    assert snap.facts[0].text == "静息心率：近 30 天平均 58 次/分（最低 54、最高 63，共 30 条）"
    assert snap.facts[1].text == "睡眠时长：近 30 天平均 6.9 小时（最低 5.1、最高 8.4，共 28 条）"
    assert FakeQuery.last_args["view"] == "stats" and FakeQuery.last_args["start"] == "2026-09-23"
    assert FakeQuery.last_user_info == {"user_id": "42", "session_id": "thread-1"}

def test_rows_without_rid_or_count_are_dropped() -> None: ...   # 没有 rid、count=0、指标不在 INDICATORS 中的行都不要

def test_error_envelope_gives_unavailable_snapshot() -> None:
    snap = run(fetch_snapshot(FakeQuery(status="error"), "42", "t", today=date(2026, 10, 22)))
    assert snap.unavailable and snap.facts == ()

def test_query_exception_gives_unavailable_snapshot() -> None: ...   # envelope 抛异常时同上，不向外抛

def test_sdnn_and_rmssd_stay_separate() -> None:   # Review Focus 5
    snap = run(fetch_snapshot(FakeQuery(rows=[
        {"name": "hrvSDNN", "count": 20, "min": 30, "max": 60, "avg": 45, "unit": "ms", "rid": "r1"},
        {"name": "hrvRMSSD", "count": 20, "min": 25, "max": 55, "avg": 38, "unit": "ms", "rid": "r2"},
    ]), "42", "t", today=date(2026, 10, 22)))
    assert [f.label for f in snap.facts] == ["心率变异性（SDNN，苹果）", "心率变异性（RMSSD）"]

def test_citations_are_record_kind() -> None:
    c = HealthSnapshot(window_days=30, facts=(fact("r3"),)).citations()[0]
    assert (c.kind, c.ref) == ("record", "rec:r3") and "58" in c.label
```

- [ ] **Step 2：运行，确认失败**

Run: `uv run pytest tests/bridge/test_records.py -v`

预期：FAIL（模块不存在）。

- [ ] **Step 3：实现**

- 按上面的 Interfaces 写 `ironm/contracts/records.py` 和 `ironm/bridge/records.py`。
- 数字按 `INDICATORS` 规定的小数位四舍五入；整数不带 `.0`。
- 出错时日志只记 `error_type`（异常类型名）。

- [ ] **Step 4：运行，确认通过**

Run: `uv run pytest tests/bridge/test_records.py -v && make check`

预期：PASS，标准检查也通过。

- [ ] **Step 5：提交**

```bash
git add ironm/contracts/records.py ironm/bridge tests/bridge && git commit -m "桥接：从 mirobody 读近 30 天健康数据统计，生成带引用编号的事实（SDNN 与 RMSSD 分开）"
```

---

### Task 5：把健康记录接进 IronM 的问答链路

**Files:**
- Modify: `ironm/agents/tools.py`、`ironm/agents/answering.py`、`ironm/orchestrator/chat.py`、`ironm/orchestrator/opinions.py`
- Test: `tests/test_health_record_tool.py`；在 `tests/test_qa_chain.py` 里追加端到端用例

**Interfaces:**
- Consumes: Task 4 的 `HealthSnapshot`、`RecordFact`。
- Produces:
  - `ToolInput.records: HealthSnapshot | None = None`（新字段，默认 None）；
  - `health_record_tool(inp: ToolInput) -> ToolResult | None`，在 `TOOLS` 中名为 `"health_record"`；
  - `answer_as(..., records: HealthSnapshot | None = None)`；
  - `ChatDeps.records: HealthSnapshot | None = None`。
  - 桥接层每轮用 `dataclasses.replace(deps, records=snapshot)` 传入。
- **问题词对应的指标**（写在 `tools.py` 中，与 `_BODY_WORDS` 同样的写法）：

| 问题里的词 | 指标 |
|---|---|
| 睡、失眠、熬夜 | `sleepDuration` |
| 心率、静息 | `restingHeartRates` |
| 心率变异、hrv、恢复、疲劳、累 | `hrvRMSSD`、`hrvSDNN` |
| 步、走路、活动量 | `steps` |
| 体重、胖、瘦、称 | `bodyMasss` |
| 身体数据、最近状态、我的数据、健康数据 | 全部指标 |

- **工具的行为**：
  - 有命中的事实时，返回 `ToolResult(name="health_record", citations=records.citations(命中的指标))`；
  - 没有命中的事实、`records` 为 None 或 `unavailable` 时，返回 None。
- **能用这个工具的 Agent**：`SPECS` 中数据分析师的 tools 为 `("bmi", "health_record")`，恢复师为 `("health_record",)`。

- [ ] **Step 1：写失败的测试**

```python
# tests/test_health_record_tool.py
def test_sleep_question_cites_sleep_fact_only() -> None:
    r = health_record_tool(tool_input("我最近睡得怎么样", records=snapshot(sleep="r4", rhr="r3")))
    assert r is not None and [c.ref for c in r.citations] == ["rec:r4"]

def test_general_status_question_cites_all_facts() -> None: ...   # "看看我最近的身体数据" → rec:r3、rec:r4

def test_no_records_or_unavailable_gives_none() -> None: ...       # records=None / unavailable=True / facts 为空 → None

def test_analyst_and_recovery_declare_the_tool() -> None:
    assert "health_record" in SPECS[AgentId.DATA_ANALYST].tools
    assert "health_record" in SPECS[AgentId.RECOVERY].tools
```

`tool_input`、`snapshot`、`deps_with`、`fake_gateway`、`opinion_citing`、`answer_text` 是本任务在测试文件中新写的小工具，写法参照 `tests/test_qa_chain.py` 中已有的假网关用例。

```python
# tests/test_qa_chain.py 中追加
def test_sleep_question_answers_with_record_citation() -> None:
    reply = respond("u1", "我最近睡得怎么样", deps_with(records=snapshot(sleep="r4"),
                    gateway=fake_gateway(opinion_citing("rec:r4", "近 30 天平均 6.9 小时"))))
    assert any(c["ref"] == "rec:r4" for c in reply.citations)
    assert reply.layer != "l0"   # 由模型作答，不是卡片

def test_sleep_question_without_records_has_no_invented_numbers() -> None:   # Review Focus 1
    reply = respond("u1", "我最近睡得怎么样", deps_with(records=HealthSnapshot(window_days=30),
                    gateway=fake_gateway(opinion_citing("rec:r9", "平均 7 小时"))))
    assert not any(c["ref"].startswith("rec:") for c in reply.citations)
    assert "7 小时" not in answer_text(reply)   # 引用了不存在的依据，这条意见作废
```

- [ ] **Step 2：运行，确认失败**

Run: `uv run pytest tests/test_health_record_tool.py tests/test_qa_chain.py -k "record or sleep" -v`

预期：FAIL。

- [ ] **Step 3：实现**

- 按 Interfaces 修改四个文件：
  - `answer_as` 把 `records` 放进 `ToolInput`；
  - `opinions.py` 调用 `answer_as` 时传入 `deps.records`。
- 先确认数字校验接受工具 citations 里 `label` 中的数字，`calc:bmi` 已经这样用了，健康记录的数字照同样方式被接受。
- 如果领域打分没有把"我最近睡得怎么样"分给恢复师，就在意图或领域词表里补上"睡得"一类的说法，并在 `tests/intent_cases.yaml` 加上这一句。

- [ ] **Step 4：运行，确认通过**

Run: `uv run pytest tests/test_health_record_tool.py tests/test_qa_chain.py -v && make check`

预期：PASS，原有测试不受影响。

- [ ] **Step 5：提交**

```bash
git add ironm tests && git commit -m "问答链路接入健康记录：数据分析师与恢复师可引用 mirobody 的数据；没有数据时不编数字"
```

---

### Task 6：IronM Agent 插件（替换 mirobody 自带的 Agent）

**Files:**
- Create: `ironm/api/runtime.py`、`ironm/bridge/render.py`、`ironm/bridge/agent.py`
- Modify: `ironm/api/app.py`（改用 `ChatRuntime`，行为不变）、`pyproject.toml`（entry point 已在 Task 2 写好，这里确认生效）
- Test: `tests/bridge/test_render.py`、`tests/bridge/test_agent.py`

**Interfaces:**
- Consumes：
  - Task 4 的 `fetch_snapshot`、`RecordQuery`；
  - Task 5 的 `ChatDeps.records`；
  - IronM 现有的 `respond(user_id, text, deps) -> ChatReply`、`after_reply(user, text, reply, deps, now=...)`、`RunRecord`（字段 `agents: tuple[tuple[AgentId, str], ...]`）。
- Produces（`ironm/api/runtime.py`）：

```python
class ChatRuntime:
    """问答运行时：启动时加载一次（规则、词表、模型配置、问答卡、动作库、检索索引），每次请求给出 ChatDeps。"""
    settings: Settings        # 桥接层用 settings.db_path 打开 SQLite
    clock: Clock              # 桥接层调用 after_reply 时传入 now=clock.now
    @classmethod
    def load(cls, settings: Settings, environ: Mapping[str, str], clock: Clock, ids: IdGenerator) -> ChatRuntime
    def migrate(self) -> None                                   # 对 settings.db_path 执行迁移
    def deps(self, conn: sqlite3.Connection) -> ChatDeps        # 即 app.py 中原来的 chat_deps(conn)
    def warm(self) -> None                                      # 配置了向量服务时在后台预计算段落向量
```

  `create_app` 里原来从加载规则到构建 retriever 的代码，以及 `chat_deps`，都搬进这个类；`create_app` 改为调用它。

- Produces（`ironm/bridge/render.py`）：

```python
HEADINGS: dict[str, str]   # conclusion→"结论"，for_you→"针对你"，why→"为什么"，how→"怎么做"，
                           # caution→"注意"，uncertain→"不确定"；answer/notice/clarify 不加标题
ROLE_NAMES: dict[AgentId, str]   # 中文角色名，如 DATA_ANALYST→"数据分析师"
STATUS_TEXT: dict[str, str]      # model→"写出了意见"，tool→"给出了计算结果"，card→"用了问答卡"，missing→"没有发言"

def to_blocks(reply: ChatReply, run: RunRecord | None, *, records_unavailable: bool) -> list[dict[str, Any]]
```

  块的顺序：
  1. 每个参与的 Agent 一对块：`{"type":"tool_call","id":f"role-{i}","name":角色名,"args":{}}` 和 `{"type":"tool_result","tool_call_id":f"role-{i}","content":状态文字,"status":"ok"}`；
  2. `records_unavailable` 时一个 `{"type":"notice","text":"这次没读到你的健康数据，下面的回答没有用到它。"}`；
  3. `reply.degraded` 时一个 `{"type":"notice","text":"这次回答受限，详见回答中的说明。"}`；
  4. 一个 `text` 块：先写安全或拒答各段（`reply.sections`），再写回答各部分（有标题的用 `**标题**` 开头），最后写"依据"：
     - `kind == "record"` 的依据写成 `<statement>{label}<cite>[{rid}]</cite></statement>`；
     - 其他依据写成 `- {label}`。

- Produces（`ironm/bridge/agent.py`）：

```python
class IronMAgent:
    def __init__(self, *, runtime: ChatRuntime | None = None, record_query: RecordQuery | None = None,
                 **kwargs: Any) -> None        # 不传时：ChatRuntime.load(load_settings(os.environ), os.environ, SystemClock(), RandomIdGenerator())，
                                               # record_query=HealthIndicatorsService()；同一进程只加载一次（类级缓存）
    @classmethod
    def load_llm_clients(cls, models: dict[str, Any]) -> dict[str, Any]   # 返回 {}
    async def generate_response(self, user_id: str, messages: list[dict[str, Any]], language: str = "",
                                session_id: str = "", file_list: list[dict[str, Any]] | None = None,
                                provider: str = "", prompt_name: str = "", **kwargs: Any
                                ) -> AsyncGenerator[dict[str, Any], None]
```

  `generate_response` 的流程：
  1. 从 `messages[-1]["content"]` 取出文字：内容是字符串就直接用；是列表就拼接其中 `type=="text"` 的部分。没有文字时只输出 `{"type":"notice","text":"没有收到文字问题。"}`，然后结束。
  2. 调用 `snapshot = await fetch_snapshot(record_query, user_id, session_id, today=用户时区的今天)`。时区取 `kwargs.get("timezone")`，取不到时用 Asia/Shanghai。
  3. 调用 `await asyncio.to_thread(self._answer, f"mb-{user_id}", text, snapshot)`。`_answer` 在工作线程里：
     - 用 `ironm.store` 的 `connect(runtime.settings.db_path)` 自己打开 SQLite 连接；
     - 执行 `deps = replace(runtime.deps(conn), records=snapshot, record_run=截住并照常保存)`，用新的 `record_run` 截住 `RunRecord`，原来的保存照常执行；
     - 调用 `respond`，再执行 `after_reply`；
     - 返回 `(reply, run)`。

     `__init__` 加载 runtime 后调用一次 `runtime.migrate()`。
  4. 对 `to_blocks(...)` 的结果逐块 `yield`。
  5. 任何异常：日志只记 `error_type`，然后输出 `{"type":"error","message":"IronM 这次没能回答，请稍后再试。"}`。

- [ ] **Step 1：写失败的测试**

`reply_with`、`record`、`text_of`、`collect`、`agent`、`msg`、`fake_gateway` 是本任务在测试文件中新写的小工具：
- `agent(...)` 用假的 `ChatRuntime`（gateway 会记调用次数）和假的 `RecordQuery` 构造 `IronMAgent`；
- `collect` 把异步生成器收成列表。

`citations.parse` 返回的 `Segment` 有 `text`、`cites`、`statement` 三个字段。

```python
# tests/bridge/test_render.py
def test_record_citation_is_cited_markup_mirobody_can_parse() -> None:
    text = text_of(to_blocks(reply_with(citations=[record("rec:r4", "睡眠时长：近 30 天平均 6.9 小时")]), None,
                             records_unavailable=False))
    assert "<statement>睡眠时长：近 30 天平均 6.9 小时<cite>[r4]</cite></statement>" in text
    from mirobody.kernel import citations
    assert any("r4" in seg.cites for seg in citations.parse(text))   # 用 mirobody 自己的解析器核对格式

def test_roles_become_tool_call_pairs_in_chinese() -> None: ...   # run.agents=((DATA_ANALYST,"model"),) → name "数据分析师"、content "写出了意见"
def test_emergency_sections_come_first() -> None: ...            # reply.level="emergency" 时 text 以四段式第一段开头
def test_unavailable_records_add_notice() -> None: ...
```

```python
# tests/bridge/test_agent.py —— 假 runtime 的 gateway 记录调用次数；假 RecordQuery
def test_emergency_answers_without_any_model_call() -> None:
    blocks = collect(agent().generate_response("42", [{"role": "user", "content": "我胸口疼，现在还在疼"}], session_id="t"))
    assert "安全结论" in text_of(blocks) and fake_gateway.calls == 0

def test_sleep_question_streams_cited_answer() -> None: ...       # 带 rid 的 snapshot → text 里有 "<cite>[r4]</cite>"
def test_record_query_failure_still_answers_with_notice() -> None: ...   # Review Focus 2：查询抛异常 → 有 notice，有 text，没有 error
def test_list_content_and_empty_message() -> None: ...            # Review Focus 3：[{"type":"text","text":"我最近睡得怎么样"}] 能答；[] 和只有附件时 → 只有 notice
def test_two_concurrent_turns_both_finish() -> None: ...           # Review Focus 4：asyncio.gather 两轮，都有 text 块
def test_pipeline_error_hides_exception_text() -> None:
    blocks = collect(agent(respond_raises=RuntimeError("SELECT secret")).generate_response("42", msg("你好"), session_id="t"))
    assert blocks == [{"type": "error", "message": "IronM 这次没能回答，请稍后再试。"}]

def test_entry_point_is_registered() -> None:
    from importlib.metadata import entry_points
    assert [ep.value for ep in entry_points(group="mirobody.agents")] == ["ironm.bridge.agent"]
```

- [ ] **Step 2：运行，确认失败**

Run: `uv run pytest tests/bridge -v`

预期：Task 6 新增的测试全部 FAIL。

- [ ] **Step 3：抽出 `ChatRuntime`，`app.py` 改用它**

Run: `uv run pytest tests -q`

预期：IronM 原有测试全部通过，证明行为没变。

- [ ] **Step 4：实现 `render.py` 和 `agent.py`**

按 Interfaces 实现。

- [ ] **Step 5：运行，确认通过**

Run: `uv sync && uv run pytest tests/bridge -v && make check`

预期：PASS。`uv sync` 用来让 entry point 登记生效。

- [ ] **Step 6：提交**

```bash
git add ironm pyproject.toml tests && git commit -m "IronM Agent 插件：替换 mirobody 自带 Agent；急症不调模型；健康数据依据可点开；出错不暴露异常"
```

---

### Task 7：写入合成健康数据，在网页上走通，并勾选 spec

**Files:**
- Create: `scripts/seed_health.py`、`scripts/e2e_chat.py`
- Modify: `Makefile`（`seed`、`e2e` 目标）、`spec/testing.md`（只勾选核实过的项）

**Interfaces:**
- Consumes：
  - Task 3 的服务 `http://127.0.0.1:18090`；
  - mirobody 的接口 `POST /email/login`、`POST /email/verify`（请求体字段以 `mirobody/user/auth/email.py` 为准）；
  - `POST /api/data`：`{"records":[{"indicator","value","unit","time","source"}]}`，Bearer 令牌；
  - `POST /api/chat`：SSE，请求体字段以 `mirobody/agent/chat/model.py` 的 `ChatStreamRequest` 为准；
  - `GET /api/citations`：参数以 `mirobody/agent/chat/service.py` 为准。

- [ ] **Step 1：写 `scripts/seed_health.py`**

- 用 `you@mirobody.ai` 和 `111111` 登录，得到令牌。
- 为过去 30 天每天写入以下合成数据，`source` 都写 `"iron-m-seed"`：

| 指标 | 单位 | 取值 |
|---|---|---|
| `sleepDuration` | `h` | 5.0–8.5 |
| `restingHeartRates` | `/min` | 52–66 |
| `hrvRMSSD` | `ms` | 25–60 |
| `steps` | 无单位 | 3000–14000 |
| `bodyMasss` | `kg` | 70–72，每隔一天写一次 |

- 随机数用 `random.Random(20261022)` 固定种子。
- 重复运行前先检查是否已经写过：查 `GET /api/data` 里有没有 `iron-m-seed` 来源的数据，有就跳过，避免同一份数据写两遍。
- 只打印条数，不打印数值。

- [ ] **Step 2：写 `scripts/e2e_chat.py`，逐项核对并打印 ✓ 或 ✗**

1. 登录。
2. 问"我最近睡得怎么样"：读 SSE，拼出 text，含有 `<cite>[r`，且 tool_call 里有"恢复师"或"数据分析师"。
3. 用回答里的 rid 调 `/api/citations`：`code == 0`，返回的 data 中能看到睡眠指标。
4. 问"我胸口疼，现在还在疼"：text 含"安全结论"。
5. 读 IronM 的 SQLite 运行记录：这一轮没有作答模型的调用记录。

任何一项失败时退出码为 1。

- [ ] **Step 3：运行**

Run: 先确认 `make run` 在运行，然后执行 `make seed && make e2e`

预期：5 项全部 ✓。需要 `.env` 里有 `DEEPSEEK_API_KEY`；没有时第 2 项会走降级路径，脚本应打印"模型密钥未设置"并判为 ✗。

- [ ] **Step 4：网页走查（项目负责人）**

1. 打开 `http://127.0.0.1:18090`，登录演示账号。
2. 问"我最近睡得怎么样"：回答下方的"依据"里，睡眠那一条可以点开，显示来自 mirobody 的睡眠记录。
3. 能展开看到参与的专业角色。
4. 问急症问题，得到四段式回答。

记下发现的问题。

- [ ] **Step 5：勾选 spec**

在 `spec/testing.md` 的 §25 中，只勾选本步核实过的三项：
- 对话由 IronM 作答；
- 急症不调用模型；
- 能引用底座里的睡眠读数并点开。

其他项保持不勾。

- [ ] **Step 6：提交**

```bash
git add scripts/seed_health.py scripts/e2e_chat.py Makefile spec/testing.md
git commit -m "端到端：写入 30 天合成可穿戴数据，网页提问由 IronM 作答并能点开健康数据引用；勾选 §25 前三项"
```

---

## 完成后

- **独立审查**（沿用"冲刺末独立审查"）：由一个全新的审查者对照本计划和 spec §25 审查整个分支，修复问题后复核。
- **向项目负责人汇报**：
  - 端到端核对的结果和走查记录；
  - 这一步刻意没做的事（见下）。
- **刻意没做**（下一步再定）：
  - IronM 自己的数据迁到 PostgreSQL；
  - §25 的 8 处底座修补；
  - 白名单登录；
  - IronM 的结构化回答在 mirobody 网页上分节显示（需要自建前端）；
  - 当日计划。
