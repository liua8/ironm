# iron-m

以 [mirobody](https://github.com/thetahealth/mirobody)（Apache-2.0）为数据底座的多 Agent 健身教练。mirobody 负责健康数据的接入、存储、查询、对话与网页；它自带的单个 Agent 将由 iron-m 的多 Agent 系统替换（通过 mirobody 官方的 `mirobody.agents` 插件接口，不修改 mirobody 源码）。

mirobody 作为 git 子模块固定在 `vendor/mirobody`（1.5.8，提交 `7775b50`），其 LICENSE、NOTICE 与版权声明原样保留。

## 本机运行

需要：uv、git-lfs、micromamba（都可装在 `~/.local/bin`，不需要管理员权限）。

```bash
git submodule update --init && git -C vendor/mirobody lfs pull
cp .env.example .env    # 填写各项，然后 chmod 600 .env
make setup              # Python 环境
make pg-install pg-init # 本机 PostgreSQL 18 + pgvector，只监听 127.0.0.1:55432
make run                # http://127.0.0.1:18090
```

演示账号：`you@mirobody.ai`，验证码 `111111`（mirobody 自带的演示数据，均为合成数据）。
