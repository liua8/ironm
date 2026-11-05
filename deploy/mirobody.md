# 把 IronM 并入 mirobody（不改 mirobody 的逻辑）

spec §168。思路：在 mirobody 的服务器上**另起一个 iron-m 进程**，用 mirobody 线上**同一份配置文件**启动
（同一个数据库、同一套密钥、同一个发信设置），再挂上 iron-m 的接口、网页和问答 Agent。

```
                 ┌──────────────── mirobody 原来的进程（不动）──────── mirobody 的网页、问答、化验单识别
用户 ── 反向代理 ─┤
                 └── iron.<域名> ── iron-m 进程（mirobody + iron-m）── IronM 的 App、网页、问答
                                         │
                       同一个 PostgreSQL、同一个 JWT_KEY  ⇒  同一张用户表，账号天然共用，不用同步
```

- mirobody 的代码一行不改（`vendor/mirobody` 和上游 1.5.8 一致）；它原来的进程、网页、问答都不受影响。
- mirobody 的账号直接登录 IronM；在 IronM 注册的账号也能登录 mirobody。
- IronM 的问答、估热量、认器械用**每个人自己填的模型**（§167），服务器不出模型费用；
  化验单识别、随手记一条是 mirobody 自己的功能，照旧用 mirobody 的模型。
- 回退：停掉 iron-m 进程即可，mirobody 照常。

## 一、动手之前

- [ ] mirobody 负责人同意（这是团队的线上服务，管的是健康数据）
- [ ] 先装**测试环境**，试顺了再上正式环境
- [ ] mirobody 那边给：
  - 线上用的配置文件（`mirobody serve` 后面跟的那几个 YAML，或等价的环境变量）——**直接用，不另抄密钥**
  - 一个子域名（比如 `iron.<mirobody 域名>`）和反向代理的改动权限
  - 线上 mirobody 的版本号（iron-m 基于 1.5.8，要对着线上版本跑一遍测试，见第五步）
- [ ] 确认线上配置里发信（SMTP）是配好的：注册、找回密码要发验证码

## 二、装 iron-m（单独的目录、单独的 Python 环境）

**不要**把 iron-m 装进 mirobody 正在用的 Python 环境：iron-m 用插件入口（`mirobody.agents`、`mirobody.tools`）
把自己登记成 mirobody 的问答 Agent，装进同一个环境，mirobody 原来的进程也会换成 IronM 的问答。

```bash
git clone <iron-m 仓库> /opt/iron-m        # 目录随意，和 mirobody 分开
cd /opt/iron-m
uv sync --frozen                          # 同 make setup；Python 3.13，建 /opt/iron-m/.venv，mirobody 从 vendor/mirobody 装
```

用代码目录跑（不要 pip 装成包）：`config/`、知识库、网页文件都在代码目录里。

## 三、启动

```bash
cd /opt/iron-m/vendor/mirobody            # mirobody 自带的网页按这个目录找
IRONM_DATA_DIR=/var/lib/iron-m \
  /opt/iron-m/.venv/bin/python -m ironm_agent.server \
    --config /etc/mirobody/config.yaml [/etc/mirobody/其余.yaml ...] \
    --host 127.0.0.1 --port 18100
```

- `--config` 后面放的就是 mirobody 线上 `mirobody serve` 用的那几个配置文件，顺序也一样；
  `--host/--port` 只决定 iron-m 这个进程监听哪里（叠在最后，不改 mirobody 的配置）。
- 环境变量（iron-m 自己的，都可选）：

  | 变量 | 作用 |
  |---|---|
  | `IRONM_DATA_DIR` | 上传的动作视频等文件放哪（默认代码目录下 `data/`），建议放到数据盘 |
  | `IRONM_ADMINS` | 能处理排行榜举报的管理员邮箱，逗号分隔 |
  | `TAVILY_API_KEY` | 问答时联网查资料；不配就不给这个工具 |

- iron-m 自己的表（`ironm_` 开头）第一次用到时自动建在同一个数据库里，和 mirobody 的表不冲突；
  用到的数据库扩展（vector、pg_trgm、pgcrypto）mirobody 本来就要。
- mirobody 的定时任务（拉设备数据、汇总指标）带分布式锁，两个进程同时跑不会重复做。

systemd 示例（`/etc/systemd/system/iron-m.service`）：

```ini
[Unit]
Description=IronM (iron-m on mirobody)
After=network.target postgresql.service

[Service]
WorkingDirectory=/opt/iron-m/vendor/mirobody
Environment=IRONM_DATA_DIR=/var/lib/iron-m
ExecStart=/opt/iron-m/.venv/bin/python -m ironm_agent.server --config /etc/mirobody/config.yaml --host 127.0.0.1 --port 18100
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## 四、反向代理

`iron.<域名>` 整个转到 iron-m 进程（App 用到 `/api/chat`、`/email/*`、`/password/*`、`/iron/*`，都在这个进程里）。
问答是边想边发（SSE），要关掉缓冲、放长超时。nginx 示例：

```nginx
server {
    server_name iron.<域名>;
    # 证书沿用 mirobody 的配置
    client_max_body_size 210m;          # 训练视频最多 200MB
    location / {
        proxy_pass http://127.0.0.1:18100;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_buffering off;            # 问答逐段显示
        proxy_read_timeout 120s;
    }
}
```

## 五、确认

- [ ] `curl https://iron.<域名>/iron/api/auth/options` 返回 `{"mail": true}`（false 说明发信没配上）
- [ ] 启动日志里有 `agent loaded: agent_class=IronMAgent`；**mirobody 原来进程**的日志里仍是它自己的 Agent
- [ ] 用一个 mirobody 已有账号在 `https://iron.<域名>/iron/` 登录成功；同一账号在 mirobody 原站也照常
- [ ] 在 IronM 「我 → 模型和 API」填一个模型、测试连接通过，问一句能回答
- [ ] 对着线上 mirobody 的版本跑 iron-m 测试：把 `vendor/mirobody` 换成线上版本后跑 `uv run pytest`、`uv run ruff check .`

## 六、App

打安卓安装包时把服务地址设成这个子域名（走 HTTPS，不用额外配置明文 http）：

```bash
cd /opt/iron-m/app   # 或开发机上的 app 目录
EXPO_PUBLIC_API_BASE=https://iron.<域名> <打包命令>
```

## 七、回退

停掉 iron-m 进程（`systemctl stop iron-m`）、去掉反向代理里的 `iron.<域名>`。mirobody 不受影响；
`ironm_` 开头的表留着不影响 mirobody，确定不用了再删。
