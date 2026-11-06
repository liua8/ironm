.PHONY: start setup pg-install pg-init pg-start pg-stop pg-check run stop health replay replay-agent

start:            ## 在自己电脑上跑（§177）：第一次装好环境、数据库、.env、配图再启动，以后直接启动；Ctrl+C 停
	scripts/start.sh $(ARGS)

setup:            ## 安装 Python 环境（mirobody 以可编辑方式安装自 vendor/mirobody）
	uv sync

pg-install:       ## 在 .pg/ 里装 PostgreSQL 18 + pgvector（需要 micromamba）
	scripts/pg.sh install

pg-init:          ## 初始化数据库（只做一次）
	scripts/pg.sh init

pg-start:
	scripts/pg.sh start

pg-stop:
	scripts/pg.sh stop

pg-check:         ## 核对三个扩展：vector、pg_trgm、pgcrypto
	scripts/pg.sh check

run:              ## 启动：http://127.0.0.1:18090/iron/ 是 iron-m 页面，/ 是 mirobody 自带网页（演示账号 you@mirobody.ai，验证码 111111）
	scripts/run_mirobody.sh

stop:             ## 停止后台运行的 mirobody
	-pkill -f "ironm_agent.server --host 127.0.0.1 --port 18090"

health:
	curl -fsS http://127.0.0.1:18090/api/health

replay:           ## 回归回放（§138）：对话用例用重放账号在本机服务上跑、后台用例在本进程跑，留报告并和以前的结果比（每轮取最近一次）；花真实模型的钱
	.venv/bin/python scripts/replay.py $(ARGS)

replay-agent:     ## 只跑后台用例（到期复查、练完定下次）：不用重放账号和本机服务
	.venv/bin/python scripts/replay.py --agent-only $(ARGS)
