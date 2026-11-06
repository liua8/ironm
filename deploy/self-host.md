# 在自己电脑上用 IronM（网页版）

**只是想用的话，不用看这份**：直接打开 <https://test-ironm.mirobody.ai> 注册就能用，手机浏览器也行。

这份是给想把数据只留在自己电脑上、自己跑一份 IronM 的人看的。有两种跑法，选一种：

| | 用 Docker（[跳到这一节](#用-docker-跑)） | 用脚本（下面第 1–7 步） |
|---|---|---|
| 适合 | Windows、Mac、Linux 都行；已经装了 Docker，或者不想装一堆小工具 | Mac、Linux；不想装 Docker |
| 要装 | Docker Desktop（一个软件，几个 G） | git、git-lfs、uv 三个小工具 |
| 启动 | `docker compose up -d`，关掉终端也照样跑 | `scripts/start.sh`，终端窗口要一直开着 |

两种跑法的数据各存各的，不互通。

下面先讲用脚本跑，第一次大约 20 分钟，以后打开只要几秒。

> 适用：Mac（M 芯片或 Intel 都行）、Linux。Windows 用 Docker 跑。
> 要准备：能上网；硬盘留 3 GB；一个你自己的大模型密钥（下面第 5 步教你申请）。

## 1. 打开"终端"

Mac：按 `⌘ + 空格`，输入"终端"（Terminal），回车。下面每一步的命令都是复制到终端里、按回车。

## 2. 装三个小工具（每台电脑只装一次）

**git**（拿代码用）：

```bash
git --version
```

Mac 上第一次跑会弹窗问要不要装"命令行开发者工具"，点"安装"，等它装完。已经显示版本号的就是装好了。

**git-lfs**（拿代码里的两个大数据文件用）：

- 装了 Homebrew 的 Mac：`brew install git-lfs`
- 没有 Homebrew 的 Mac：到 <https://git-lfs.com> 点 Download 下安装包，解压后在终端里进那个目录跑 `sudo ./install.sh`
- Linux（Ubuntu / Debian）：`sudo apt install git-lfs`

装好后跑一次：

```bash
git lfs install
```

**uv**（装 Python 用）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

装完**关掉终端再重新打开**。

## 3. 拿代码

```bash
git clone https://github.com/thetahealth/mirobody-ironm.git iron-m
cd iron-m
```

> 仓库还没公开时，要先请项目负责人把你的 GitHub 账号加成协作者，第一次 clone 会让你登录 GitHub。

## 4. 启动

```bash
scripts/start.sh
```

第一次它会依次：装 Python 环境 → 生成这台电脑自己的密码和密钥（存在 `.env`）→ 装数据库 → 下载动作、食物配图 → 启动。看到下面这几行就好了：

```
用浏览器打开：http://127.0.0.1:18090/iron/
```

**这个终端窗口别关**，关了 IronM 就停了。

## 5. 注册、填模型

1. 浏览器打开 <http://127.0.0.1:18090/iron/>，点"注册"：邮箱就是登录名，设一个至少 8 位的密码。
   现在不发验证码，**也不能找回密码，记好密码**。
2. 注册后先填身高、出生日期、体重。
3. 到「我 → 模型和 API」填你自己的模型（问 IronM、拍照估热量、认器械都要用，费用记在你自己的账户上）：
   - **服务商**选 DeepSeek（便宜，国内能直接用）：到 <https://platform.deepseek.com> 注册、充几块钱、在"API keys"里新建一个密钥，复制过来。
   - **对话模型**默认 `deepseek-flash`，不用改。
   - **看图模型**：DeepSeek 不能看图，要拍照估热量、认器械的，服务商可以改选"通义千问"或"智谱"（同样去它们的网站申请密钥）。不拍照可以不管。
   - 点"测试连接"，三项里"能不能通""能不能调工具"都写"可以"，再点"保存"。
4. 到底下的"IronM"问一句试试，比如"我想开始练，每周 3 天，在健身房"。

## 6. 以后怎么用

| 想做什么 | 怎么做 |
|---|---|
| 停 | 在跑着的终端窗口按 `Ctrl + C` |
| 再打开 | 打开终端，`cd iron-m`，再跑 `scripts/start.sh`，然后打开 <http://127.0.0.1:18090/iron/> |
| 更新到新版本 | 先停，`git pull`，再 `scripts/start.sh` |
| 彻底删掉 | 先停，删掉整个 `iron-m` 文件夹 |

## 7. 要知道的

- **数据只在你这台电脑上**（`iron-m/.pg/` 里），没有备份，电脑坏了、文件夹删了就没了。
- `.env` 是这台电脑的数据库密码和密钥，**别发给别人、别删**，删了以前的数据就打不开了。
- 你问 IronM 的话、拍的照片，会发给你自己填的模型服务商；查天气时只发城市的经纬度。
- 只有这台电脑自己能打开；同一个 Wi‑Fi 里的别人、手机 App 都连不上。

## 遇到问题

| 看到什么 | 怎么办 |
|---|---|
| `还没装 uv` | 回到第 2 步装 uv，装完重开终端 |
| `代码里有两个大数据文件要用 git-lfs 取` | 装 git-lfs，在 `iron-m` 里跑 `git lfs install && git lfs pull`，再启动 |
| `could not start server`、端口被占 | 换端口：`IRONM_PORT=18200 IRONM_PG_PORT=55500 scripts/start.sh`，然后打开 `http://127.0.0.1:18200/iron/` |
| 注册页写"邮件服务还没配好，暂时不能注册" | 代码太旧：先停，`git pull`，再 `scripts/start.sh` |
| 第一次打开首页，有一两块写"没读到" | 第一次要建数据表，几处同时建会撞上；刷新一次就好 |
| 配图有几张没下到 | 不影响用；以后跑 `.venv/bin/python scripts/fetch_images.py` 补 |
| 不想等配图下载 | `scripts/start.sh --no-images` |
| 问 IronM 说"先填你自己的模型" | 第 5 步第 3 条 |
| 测试连接"不行" | 看密钥有没有复制全、账户里有没有余额 |
| 忘了密码 | 现在找不回；只能删掉 `iron-m` 文件夹重新来（以前的数据也没了） |

## 用 Docker 跑

Windows、Mac、Linux 都行（spec §185）。第一次大约 20 分钟（下载、构建），以后几秒钟。

> 要准备：能上网；硬盘留 8 GB；一个你自己的大模型密钥（同上面第 5 步）。

### 1. 装 Docker Desktop（每台电脑只装一次）

到 <https://www.docker.com/products/docker-desktop/> 下载对应系统的安装包，装好后**打开 Docker Desktop**，等左下角显示正在运行（Engine running）。

- Windows：安装时勾选"使用 WSL 2"，装完按提示重启电脑。
- Linux：也可以不装 Docker Desktop，按 Docker 官网的说明装 Docker Engine 和 `docker-compose-plugin`（系统自带的老版本 `docker-compose` 不行）。
- 在公司电脑上用要注意：大公司商用 Docker Desktop 要买许可，个人和小团队免费。

打开终端（Windows 用"PowerShell"），确认装好了：

```bash
docker compose version
```

显示 `v2.` 开头或更新的版本号就行。

### 2. 拿代码

```bash
git clone https://github.com/thetahealth/mirobody-ironm.git iron-m
cd iron-m
```

> 没有 git 的，也可以在 GitHub 页面点 Code → Download ZIP，解压后在终端里进到那个文件夹。不用装 git-lfs，构建时会自己补齐两个大数据文件。

### 3. 启动

```bash
docker compose up -d
```

第一次会下载基础镜像、装 Python 依赖、建数据库，要等一阵。命令结束后再等一两分钟，浏览器打开 <http://127.0.0.1:18090/iron/>，看到登录页就好了。接着照上面第 5 步注册、填模型。

- 配图（动作、食物照片）在后台慢慢下，没下完也能先用，有的图会先空着；没下到的每次启动会再补。
- 数据库密码和密钥第一次启动时自动生成，存在 Docker 里，不用你管。
- 日志里 mirobody 说的 `/setup` 页面和"no LLM model"不用管，模型在 IronM 的「我 → 模型和 API」里填。

### 4. 以后怎么用

| 想做什么 | 怎么做（都在 `iron-m` 文件夹里跑） |
|---|---|
| 看它在干什么 | `docker compose logs -f ironm`，按 `Ctrl + C` 退出查看（不会停 IronM） |
| 停 | `docker compose down`（数据还在） |
| 再打开 | 先打开 Docker Desktop，再 `docker compose up -d` |
| 更新到新版本 | `git pull`，再 `docker compose up -d --build`；下压缩包的：下新的压缩包解压，在新文件夹里 `docker compose up -d --build`（数据接着用） |
| 备份数据库 | 先 `docker compose exec pg pg_dump -U ironm -f /tmp/backup.sql mirobody`，再 `docker compose cp pg:/tmp/backup.sql ironm-backup.sql`，`iron-m` 文件夹里就有一份备份（配图能重新下，不用备份） |
| 彻底删掉 | `docker compose down -v --rmi all`（账号、记录、配图、密钥和下载的镜像全删，找不回），再删掉 `iron-m` 文件夹 |

- Docker Desktop 开着时，IronM 会跟着它自动起来；不想要就 `docker compose down`。
- 每次更新会留下旧镜像占硬盘，隔一阵跑一次 `docker image prune` 清掉。

### 5. 可选设置

在 `iron-m` 文件夹里建一个名叫 `.env` 的文本文件，一行一项，改完 `docker compose up -d` 生效。最省事是复制一份样例再改：Mac、Linux 用 `cp .env.example .env`，Windows PowerShell 用 `copy .env.example .env`，然后用记事本打开改（`notepad .env`；别在记事本里"另存为"，会变成 `.env.txt`）。

| 写什么 | 做什么 |
|---|---|
| `IRONM_PORT=18200` | 18090 被占了就换一个，然后打开 `http://127.0.0.1:18200/iron/` |
| `IRONM_IMAGES=0` | 不下配图 |
| `EMAIL_SMTP_HOST=` 等几项 | 配发信邮箱，注册、找回密码会发验证码（写法见 `.env.example`） |
| `TAVILY_API_KEY=` | IronM 能联网查资料 |

`.env` 里别的项（数据库密码、密钥等，是给脚本跑法用的）Docker 不读。

### 6. 国内下载慢、下不了

第一次 `docker compose up -d` 卡在下载很久、或者报 `failed to resolve`、`timeout`、`TLS handshake` 之类，在 `.env` 里加这三行再跑一次：

```
DOCKER_MIRROR=docker.1ms.run/
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
APT_MIRROR=mirrors.aliyun.com
```

第一行是 Docker 镜像的加速地址（末尾的 `/` 要带），第二行是 Python 包的国内源，第三行是系统包的国内源。加速地址不灵了可以换一个别的公开加速地址。

构建时说"下不到 …（git-lfs 数据文件）"：照它打印的办法做（用 git 拿的代码就 `git lfs install && git lfs pull`；下压缩包的就用浏览器下它给的地址、放到它说的位置），再 `docker compose up -d --build`。

### 7. 遇到问题

| 看到什么 | 怎么办 |
|---|---|
| `Cannot connect to the Docker daemon`、`dockerDesktopLinuxEngine`、`docker: command not found` | Docker Desktop 没打开或没装好：打开它，等显示正在运行再跑 |
| `port is already allocated`、`ports are not available` | 18090 被占了：`.env` 里写 `IRONM_PORT=18200`，再 `docker compose up -d` |
| 浏览器打不开 | 刚起来要等一两分钟；`docker compose ps` 看 ironm 是不是 `healthy`，不是就看 `docker compose logs ironm` |
| 第一次打开首页，有一两块写"没读到" | 第一次要建数据表，几处同时建会撞上；刷新一次就好 |
| 忘了密码 | 现在找不回；只能 `docker compose down -v` 删光重来（以前的数据也没了） |

### 8. 要知道的

- 数据在 Docker 的数据卷里（名字以 `ironm_` 开头），不在 `iron-m` 文件夹里；删了文件夹数据还在，`docker compose down -v` 才删光。
- 没有自动备份：Docker Desktop 里的"Clean / Purge data"、卸载 Docker、`docker system prune --volumes` 都会把数据删掉，在意的话先用上面的命令备份数据库。
- 和用脚本跑一样：只有这台电脑自己能打开；问的话和照片会发给你自己填的模型服务商。
- 用脚本跑过的，那边的账号和数据不会搬过来，要重新注册。
