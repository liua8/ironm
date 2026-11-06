# 在自己电脑上用 IronM（网页版）

还没有大家共用的服务器，所以每个人在自己电脑上跑一份 IronM，用浏览器打开网页版（spec §177）。照下面一步步做就行，第一次大约 20 分钟，以后打开只要几秒。

> 适用：Mac（M 芯片或 Intel 都行）、Linux。Windows 暂时不行。
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
git clone https://github.com/liua8/ironm.git iron-m
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
