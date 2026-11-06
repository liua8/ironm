# iron-m

以 [mirobody](https://github.com/thetahealth/mirobody)（Apache-2.0）为数据底座的健身教练 Agent。mirobody 负责健康数据的接入、存储、查询、对话与网页；它自带的 Agent 由 iron-m 的单 Agent（Skill + 工具）替换，通过 mirobody 官方的 `mirobody.agents` 插件接口接入。

mirobody 放在 `vendor/mirobody`（基于上游 1.5.8，提交 `7775b50`；是本仓库里的普通目录，不是子模块，见 `vendor/mirobody/IRON-M.md`），其 LICENSE、NOTICE 与版权声明原样保留。

## 在自己电脑上跑（给想用的人）

还没有大家共用的服务器，想用的人先在自己电脑上跑，用浏览器打开网页版（spec §177）。不熟悉终端的，照 [deploy/self-host.md](deploy/self-host.md) 一步步做（装工具、申请模型密钥、遇到问题怎么办都写了）。

**要什么**：一台 Mac 或 Linux 电脑（Windows 暂时不行）、能上网、git 和 [git-lfs](https://git-lfs.com)、[uv](https://docs.astral.sh/uv/getting-started/installation/)，以及一个你自己的模型密钥（比如 DeepSeek，问 IronM 时用）。磁盘留 3 GB 左右。

没有 uv 的先装（装好后重新打开终端）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

拿代码、启动（第一次要装 Python 环境、数据库、下配图，十几分钟；以后几秒钟）：

```bash
git lfs install
git clone <iron-m 仓库地址> iron-m && cd iron-m
scripts/start.sh
```

看到"用浏览器打开"后打开 <http://127.0.0.1:18090/iron/>：

1. **注册**：邮箱就是登录名，设一个密码（没配发信时不发验证码，也不能找回密码，记好密码）。
2. **填模型**：「我 → 模型和 API」填你自己的模型和密钥，测试连接通过就能问 IronM。

**停**：在跑脚本的终端窗口按 Ctrl+C（服务和数据库一起停）。**再用**：再跑一次 `scripts/start.sh`。

| 想做什么 | 怎么做 |
|---|---|
| 端口被占了 | `IRONM_PORT=18200 IRONM_PG_PORT=55500 scripts/start.sh` |
| 第一次不下配图 | `scripts/start.sh --no-images`；以后补：`.venv/bin/python scripts/fetch_images.py` |
| 更新到新版本 | 先停，`git pull`，再 `scripts/start.sh` |
| 彻底删掉 | 先停，删掉整个 `iron-m` 目录（数据库、密钥、图片都在里面） |

**要知道的**：

- 数据（账号、训练、饮食、身体数据、和 IronM 的对话）只存在这台电脑的 `.pg/` 里，**没有备份**，电脑坏了就没了；`.env` 里是这台电脑的数据库密码和密钥，别发给别人、别删。
- 问 IronM 的话、拍的照片会发给你自己填的模型服务商；联网查天气时只发城市的经纬度。
- 服务只听本机（127.0.0.1），同一个 Wi‑Fi 里的别人和手机 App 都连不上。

## 本机运行（开发）

需要：uv、git-lfs、micromamba（都可装在 `~/.local/bin`，不需要管理员权限）。

```bash
git lfs install && git lfs pull   # vendor/mirobody 里两个大数据文件走 git-lfs
cp .env.example .env    # 填写各项，然后 chmod 600 .env
make setup              # Python 环境
make pg-install pg-init # 本机 PostgreSQL 18 + pgvector，只监听 127.0.0.1:55432
make run                # http://127.0.0.1:18090
```

演示账号：`you@mirobody.ai`，验证码 `111111`（mirobody 自带的演示数据，均为合成数据）。
