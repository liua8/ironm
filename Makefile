.PHONY: setup pg-install pg-init pg-start pg-stop pg-check run stop health

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

run:              ## 启动 mirobody：http://127.0.0.1:18090（演示账号 you@mirobody.ai，验证码 111111）
	scripts/run_mirobody.sh

stop:             ## 停止后台运行的 mirobody
	-pkill -f "mirobody dev --host 127.0.0.1 --port 18090"

health:
	curl -fsS http://127.0.0.1:18090/api/health
