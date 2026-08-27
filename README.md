# TG Daily Greeter

一个基于 **Telethon** 的 Telegram 个人账号定时问候工具。每次手动运行（GitHub Actions）时，根据当前莫斯科时间自动判断时段发送问候消息：0:00~12:59 发送早上内容、13:00~23:59 发送晚上内容，脚本启动后随机等待 1~5 分钟再发送。

专为 **GitHub Actions** 手动运行设计，零服务器成本，配置驱动，无需常驻进程。

## 功能特性

- **个人账号发送**（非 Bot），通过 Telethon + Session String 登录
- **多目标配置**，每人独立时区、消息池、随机抖动
- **俄语问候语库**，早安 15 条 + 晚安 15 条，每日随机选取
- **早晚双问候**，早上 / 晚上自动识别（莫斯科时间 0:00~12:59=早, 13:00~23:59=晚）
- **个人特殊日期**：可配置生日/纪念日等，当天发送专属问候；公共节假日不自动发送
- **新年假期专属问候**（12月31日—1月8日）
- **占位符变量**：`{name}`、`{date}`、`{weekday}`、`{time}` 等自动替换
- **随机抖动**，避免机械发送模式，降低风控风险
- **FloodWait 自动等待重试**（最多2次），用户无效/拉黑/注销等异常不重试，网络错误指数退避
- **全局 300 秒超时保护**，连接+发送阶段超时自动终止
- **执行报告**，每次运行后向"已保存消息"发送发送日志
- **Dry-run 模式**，本地测试只打印不发送
- **手动触发**，Actions 支持 `workflow_dispatch` 随时测试

### TG 防检测（模拟真人行为）

- **每日概率跳过**：默认 `skip_probability: 0.2`，即 20% 概率今天不发送（80% 的天数会正常发送）。运行时会打印随机数和阈值便于排查；设 0 则总是发送，设 1 则永不发送
- **启动随机等待**：脚本启动后随机等待 1-5 分钟再连接 Telegram，不会准点上线
- **好友间发送延迟**：每发完一个好友随机等待 2-5 秒再发下一个
- **打字指示器模拟**：发送前显示"正在输入..."1.5-4 秒，然后才发送消息
- **真实设备指纹**：每次连接随机选择 iPhone/Android 设备型号、系统版本、App 版本
- **真人行为预热**：连接后自动获取个人信息和最近对话列表，模拟官方 App 启动行为
- **发完即断**：所有消息发送完毕后立即断开连接，不保持在线
- **每好友内容不重复**：3 个好友从同一消息池随机抽取且互不重复

## 项目结构

```
tg-daily-greeter/
├── .github/workflows/
│   └── greet.yml             # 单一工作流 (仅手动触发, 早晚自动检测)
├── config/
│   └── config.example.yml   # 配置模板（复制为 config.yml）
├── messages/
│   ├── morning_ru.yml       # 俄语早安问候语库
│   ├── evening_ru.yml       # 俄语晚安问候语库
│   └── special_dates.yml    # 特殊日期说明与示例
├── src/
│   ├── config_loader.py     # 配置加载与校验
│   ├── message_selector.py  # 消息选择、特殊日期、占位符
│   ├── telegram_sender.py   # Telethon 封装、重试、FloodWait
│   ├── timezone_utils.py    # 时区与日期格式化
│   └── notifier.py          # 执行报告通知
├── main.py                   # 主入口
├── login.py                  # 本地登录，生成 Session String
├── requirements.txt
├── .gitignore
├── LICENSE
└── README.md
```

## 快速开始

### 1. 获取 Telegram API 凭证

访问 [https://my.telegram.org/apps](https://my.telegram.org/apps)，登录后创建一个应用，获取：
- `api_id`（整数）
- `api_hash`（字符串）

### 2. 本地登录，生成 Session String

```bash
pip install -r requirements.txt
python login.py --api-id YOUR_API_ID --api-hash YOUR_API_HASH
```

按提示输入手机号（带国家区号，如 `+8613800138000`）和验证码。如果开启了两步验证，还需输入密码。

登录成功后会输出一长串 **Session String**，复制保存好。

> ⚠️ **安全警告**：Session String 等同于账号密码，绝不能公开或提交到仓库。

### 3. 创建 GitHub 私有仓库

```bash
# 在 GitHub 上创建一个私有仓库，然后：
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/你的用户名/tg-daily-greeter.git
git push -u origin main
```

> ⚠️ 必须是**私有仓库**，防止配置和消息内容泄露。

### 4. 配置 GitHub Secrets

进入仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**，添加以下 3 个密钥：

| Secret 名称 | 值 |
|---|---|
| `TG_API_ID` | 你的 api_id（整数） |
| `TG_API_HASH` | 你的 api_hash |
| `TG_SESSION_STRING` | 第 2 步生成的 Session String |

### 5. 配置好友信息

复制配置模板并编辑：

```bash
cp config/config.example.yml config/config.yml
```

编辑 `config/config.yml`，在 `targets` 下填入 3 位好友的信息：

```yaml
targets:
  - name: "Алексей"
    username: "@alexey_username"   # 或 chat_id: 123456789
    timezone: "Europe/Moscow"
    morning:                          # 早安时段消息池
      message_file: "messages/morning_ru.yml"
    evening:                          # 晚安时段消息池
      message_file: "messages/evening_ru.yml"
    jitter_minutes: 5
    special_dates:
      "03-15":
        morning: "С днём рождения, {name}! Желаю счастья и здоровья!"
        evening: "С днём рождения, {name}! Надеюсь, день прошёл замечательно."
```

> **早晚分开配置**：每个 target 可以配置 `morning` 和 `evening` 子配置，各自指定 `message_file` 或 `message_pool`。早安 workflow 传 `--period morning`，自动加载 `morning` 子配置；晚安 workflow 传 `--period evening`，自动加载 `evening` 子配置。如果没有配置子配置，则使用顶层的 `message_file`/`message_pool`（早晚通用）。

提交配置：

```bash
git add config/config.yml
git commit -m "Add target configuration"
git push
```

### 6. 测试运行

进入仓库 → **Actions** → 选择 **Daily Greeting** 工作流 → 点击 **Run workflow** 手动触发。

脚本会根据当前莫斯科时间自动判断时段（0:00~12:59 早上 / 13:00~23:59 晚上），等待 1~5 分钟后发送。查看运行日志，确认消息发送成功。同时检查 Telegram "已保存消息"中是否收到执行报告。

### 7. 完成

配置完成后，在 GitHub Actions 页面手动运行 **Daily Greeting** 工作流即可。脚本根据当前莫斯科时间自动判断时段：
- **0:00~12:59** 运行 → 随机等待 1~5 分钟 → 发送早安问候
- **13:00~23:59** 运行 → 随机等待 1~5 分钟 → 发送晚安问候

> 每次运行都会等待 1~5 分钟后才发送，模拟真人操作。

## 配置说明

### 全局配置

| 字段 | 说明 | 默认值 |
|---|---|---|
| `api_id` | Telegram API ID | （从环境变量读取） |
| `api_hash` | Telegram API Hash | （从环境变量读取） |
| `session_string` | Telethon Session String | （从环境变量读取） |
| `proxy` | 代理地址（可选） | 空（直连） |
| `timezone` | 默认时区 | `Europe/Moscow` |
| `default_jitter_minutes` | 默认随机抖动（分钟） | `5` |
| `dry_run` | 试运行模式 | `false` |

### Target 配置

| 字段 | 说明 | 必填 |
|---|---|---|
| `name` | 好友称呼，用于 `{name}` 占位符 | ✅ |
| `chat_id` | Telegram 对话 ID（整数） | chat_id/username 二选一 |
| `username` | Telegram 用户名（带 @） | chat_id/username 二选一 |
| `timezone` | 该好友时区（覆盖全局） | ❌ |
| `message_pool` | 内联消息列表（早晚通用，无 morning/evening 时使用） | message_pool/message_file 二选一 |
| `message_file` | 外部消息 YAML 文件路径（早晚通用） | message_pool/message_file 二选一 |
| `morning` | 早安时段专属配置，可含 `message_file`/`message_pool`，覆盖顶层 | ❌（推荐配置） |
| `evening` | 晚安时段专属配置，可含 `message_file`/`message_pool`，覆盖顶层 | ❌（推荐配置） |
| `jitter_minutes` | 该目标的随机抖动 | ❌ |
| `selection_mode` | `random` 或 `sequential` | ❌（默认 random） |
| `special_dates` | 个人特殊日期（MM-DD） | ❌ |

### 占位符

| 占位符 | 说明 | 示例输出 |
|---|---|---|
| `{name}` | 好友称呼 | `Алексей` |
| `{date}` | 俄语格式日期 | `27 августа 2026 г.` |
| `{weekday}` | 俄语星期 | `четверг` |
| `{time}` | 当前时间 | `07:00` |
| `{day}` | 日（数字） | `27` |
| `{month}` | 俄语月份（二格） | `августа` |
| `{year}` | 年（数字） | `2026` |

### 个人特殊日期

公共节假日（新年、胜利日、妇女节等）**不会**自动发送问候。只有你在 target 的 `special_dates` 中手动配置的个人日期（生日、纪念日等）才会触发专属问候：

```yaml
targets:
  - name: "Алексей"
    morning:
      message_file: "messages/morning_ru.yml"
    evening:
      message_file: "messages/evening_ru.yml"
    special_dates:
      "03-15":                                 # 3月15日（生日）
        morning: "С днём рождения, {name}!"   # 当天早安用这条
        evening: "С днём рождения, {name}! Добрых снов!"  # 当天晚安用这条
      "01-01":                                  # 如果想发新年问候，手动加
        message: "С Новым годом, {name}!"
```

格式说明：
- `special_dates` 键为 `"MM-DD"` 格式日期
- 每个日期下可配 `morning` / `evening`（分别用于早晚），或 `message`（早晚通用）
- 当天命中时，对应的专属问候会**替代**该时段的普通消息池消息

## 命令行用法

```bash
# 自动检测时段（莫斯科时间 0:00~12:59=早上, 13:00~23:59=晚上）
python main.py

# 手动指定时段发送
python main.py --period morning
python main.py --period evening

# 试运行（只打印不发送）
python main.py --period morning --dry-run

# 指定配置文件
python main.py --period morning --config path/to/config.yml

# 只发送给特定目标（测试用）
python main.py --period morning --target "Алексей"

# 忽略每日跳过概率（强制今天发送，测试用）
python main.py --period morning --no-skip

# 跳过所有延迟（启动休眠+好友间延迟，测试用）
python main.py --period morning --no-delay

# 组合使用：测试模式（不跳过+无延迟+试运行）
python main.py --period morning --no-skip --no-delay --dry-run

# 本地登录生成 Session String
python login.py --api-id 12345 --api-hash abcdef
```

> **自动检测说明**：不传 `--period` 时，脚本根据当前莫斯科时间自动判断。
> **0:00~12:59** 任意时间运行 → 发送早上问候；**13:00~23:59** 任意时间运行 → 发送晚上问候。
> 脚本启动后随机等待 1~5 分钟再发送。全天都有归属，不会出现无法判断的情况。

## 注意事项

1. **账号安全**：Session String 等同于密码，务必使用私有仓库和 GitHub Secrets，不要泄露。
2. **封号风险**：使用个人账号自动发送消息违反 Telegram 服务条款。本项目用于个人好友间的日常问候，频率低，风险较低，但仍需自行承担风险。避免短时间内大量发送。
3. **手动运行**：工作流仅支持手动触发（`workflow_dispatch`），无定时任务。在 Actions 页面选择 **Daily Greeting** 并点击 **Run workflow** 即可。
4. **免费额度**：私有仓库每月有 2000 分钟免费 Actions 时长，每次运行约 1 分钟，完全够用。
5. **时区**：莫斯科时间为 UTC+3，无夏令时。时段判定使用配置中的 `timezone`（默认 `Europe/Moscow`）。
6. **频繁"今日随机跳过"排查**：脚本运行时打印 `🎲 概率判定: 随机数=..., 跳过阈值=...`。若经常被跳过，说明 `config.yml` 中 `skip_probability` 偏大（它表示**跳过/不发送**的概率，不是发送概率）：`0`=总是发送，`0.2`=约80%天数发送，`1`=永不发送。测试阶段建议先设为 `0` 或用 `--no-skip` 运行。

## 技术栈

- **Python 3.12**
- **Telethon** — Telegram MTProto 客户端库
- **PyYAML** — YAML 配置解析
- **pytz** — 时区处理
- **GitHub Actions** — 手动运行环境

## License

MIT License
