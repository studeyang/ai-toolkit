---
name: disconf
description: 查询和修改 Disconf 分布式配置管理平台的配置。当用户提到 disconf、配置中心、配置项、配置文件、想查某个应用的配置、想改测试/生产环境配置、排查配置是否正确、对比不同环境的配置差异、或问"这个配置在哪里配的"时，都应该使用本技能。只要涉及 Disconf 实例（开源 knightliao/disconf 及其企业定制版本）上的配置读取或修改，即使是查 db.properties、redis.properties 这类连接信息或功能开关，也应触发。
license: MIT
compatibility: 仅需 Python 3.8+（全部用标准库），无需安装任何第三方包。需要能访问你的 Disconf 服务地址。
---

# Disconf 配置中心

Disconf 是百度开源的分布式配置管理平台，广泛用于 Java/Spring 微服务场景。它本身只提供 Web 界面，没有通用的 MCP 或 CLI。本技能用一条命令完成查改配置，不必每次手拼 curl。

## 先配置，再使用

脚本不内置任何地址和账号，必须先告诉它连哪里：

```bash
export DISCONF_HOST=http://disconf.example.com   # 你的 Disconf 地址
export DISCONF_USER=your_account
export DISCONF_PASSWORD=your_password
```

也可以每次用 `--host / --user / --password` 传。环境变量方式更适合反复使用，注意不要把密码提交进 git。

## 为什么走脚本而不是裸 curl

Disconf 的鉴权完全依赖 `JSESSIONID` cookie：先 `POST /api/account/signin` 拿到会话，之后每个请求都要带上它。而且**未登录时它不返回 401**，而是抛 HTTP 500 加一整页 Tomcat 堆栈——直接 curl 很容易误判成"服务挂了"，白白排查半天。脚本把这些脏活封好了，输出统一成 JSON，方便 Agent 解析。

## 基本用法

脚本在 `scripts/disconf.py`（相对本技能目录）。

```bash
python scripts/disconf.py apps                              # 列出所有应用
python scripts/disconf.py envs                              # 列出所有环境
python scripts/disconf.py resolve --app my-app --env rd     # 应用名/环境名 → id + 可用版本
python scripts/disconf.py list --app-id 19 --env-id 1 --version 1_0_0_0
python scripts/disconf.py get --config-id 3256              # 读单条（密码自动脱敏）
python scripts/disconf.py get --config-id 3256 --show-value # 读明文
python scripts/disconf.py zk --app-id 19 --env-id 1 --version 1_0_0_0
                                                            # ZK 部署情况、哪些机器在订阅
python scripts/disconf.py find --keyword redis --app my      # 按 key 跨应用搜索
```

## 查配置的标准流程

配置的定位是 **应用 → 环境 → 版本 → key** 四级。拿不到 configId 时按序找：

1. `apps` 找到应用 id。记不住全名就用 `find` 或 `resolve` 做模糊匹配。
2. `envs` 找到环境 id。
3. `resolve --app xxx --env xxx` 一次拿到 appId/envId/versions，省两次往返。
4. `list` 拿配置清单，从 `key` 里挑出目标，记下 `configId`。
5. `get --config-id` 读内容。

`list` 的 **appId、envId、version 三个参数全部必填**，少传一个接口会返回"不能为null"。这是 Disconf 的接口设计，不是脚本限制。

另外注意：`list` 返回的 `value` 字段永远是空字符串，真实内容必须走详情接口。这是最容易踩的坑。

## 改配置——先想清楚风险

改 Disconf 不是改数据库里一行记录。它会**推送到 Zookeeper，所有订阅该应用的客户端立即生效**。没有灰度、没有审批、没有回收站、没有一键回滚。

**动手前必做三件事**

1. **先 `--dry-run`**，把 before/after 摆给用户看，确认改的是对的配置、对的环境。
2. **确认环境**。先跑 `envs` 搞清楚哪个环境是测试、哪个是生产。如果目标是生产，必须让用户明确点头。
3. **改配置文件要传完整内容**。`update` 对配置文件是**整段替换**，不是增量合并。只想改一行的，先 `get --show-value` 拉全文 → 本地改 → 整体写回。传个片段会把整个文件冲掉。

```bash
# 1. 预演看 diff
python scripts/disconf.py update --config-id 3256 --value "pool.size=20" --dry-run

# 2. 确认无误后落盘
python scripts/disconf.py update --config-id 3256 --value "pool.size=20"

# 配置文件建议从文件读，避免 shell 转义把内容改坏
python scripts/disconf.py update --config-id 3256 --value-file /tmp/new.properties --dry-run
```

**新建配置**

```bash
# 配置项
python scripts/disconf.py create --app-id 19 --env-id 1 --version 1_0_0_0 \
  --kind item --key "feature.switch" --value "true"

# 配置文件（文件名只能是 .properties 或 .xml，Disconf 前端也限定了）
python scripts/disconf.py create --app-id 19 --env-id 1 --version 1_0_0_0 \
  --kind file --file-name "app.properties" --value-file /tmp/app.properties
```

**删除配置**

删除必须二次确认，`--confirm` 的值要等于 configId。这是刻意设计的护栏，少打一个字它就不删。

```bash
python scripts/disconf.py delete --config-id 3256 --dry-run        # 先看要删什么
python scripts/disconf.py delete --config-id 3256 --confirm 3256    # 真删
```

## 密码与敏感信息

`get` 默认把 `password / passwd / secret / token / credential` 这类字段替换成 `(*已隐藏*)`，避免密码进入会话记录和日志。确实要看明文才加 `--show-value`，并且别把输出贴到公开场合。

脱敏按字段名匹配。`jdbc-key`、`redis.key` 这类是分片标识或普通键名，不会被误隐藏——早期版本用宽泛的 `key` 匹配，结果把 `jdbc-key-` 也藏了，现已修正。

## 接口速查

要直接调接口、或排查脚本行为不一致时看 → `references/api.md`

## 排查常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| HTTP 500 + Tomcat 堆栈 | 未登录或会话失效 | 脚本会自动重登一次；仍失败就查账号密码 |
| `app is empty` / `不能为null` | 必填参数没给全 | `list` 需要 appId+envId+version |
| `app xxx doesn't exist in db` | 应用名拼错 | 用 `apps` 列出真实名称 |
| 连不上 / 超时 | 网络不通或需要 VPN | 确认 `DISCONF_HOST` 可达 |
| `list` 里 value 是空的 | 接口特性 | 改用 `get --config-id` |

## 不要做的事

- **别跳过 `--dry-run` 直接改配置**，尤其配置文件——整段替换的语义很容易让内容丢失。
- **别忽略环境**。同一个应用在不同环境是完全两套配置，改错环境比改错值更严重。
- **别把 `--show-value` 的输出写进工单、聊天记录或截图**，里面通常有明文数据库密码。
- 别用测试环境的账号去试生产。

## 关于这个技能的边界

本技能只操作 Disconf 的 HTTP 接口，不修改其代码，与上游项目（Apache-2.0）无隶属关系。Disconf 服务端的部署、鉴权强化、审计不在本技能范围内。

如果你的 Disconf 实例强化过鉴权（比如加了 SSO、内网 ACL），脚本的 signin 流程可能需要相应调整——见 `references/api.md` 的鉴权章节。
