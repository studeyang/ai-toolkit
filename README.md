# ai-toolkit

我开发并维护的 AI Agent 技能（Skills）与模型上下文协议服务（MCP Servers）集合。

每个条目都围绕一个真实的、反复出现的工程问题，目标是把"每次都要重新摸索的事"变成"一句话就能复用的事"。

## 仓库结构

```
ai-toolkit/
├── skills/                  # AI Agent 技能（Claude Skills 格式）
│   └── disconf/
│       ├── SKILL.md          # 技能定义与使用指南
│       ├── scripts/          # 可执行脚本
│       └── references/       # 按需加载的参考文档
├── mcps/                    # MCP Servers（stdio）
│   ├── mysql/                # 通用只读 MySQL 查询
│   ├── archery/              # Archery SQL 查询封装
│   └── confluence/           # Confluence 检索（第三方 mcp-atlassian）
├── AGENTS.md                # 开源规范：安全红线、提交自检、CI 局限
└── .github/workflows/        # CI：敏感信息扫描 + 语法检查
```

> 在本仓库提交代码前，请先读 [AGENTS.md](AGENTS.md)。里面写清了哪些信息绝对不能进仓库、提交前必跑的自检命令，以及 CI 到底拦不住什么。

## 技能列表

| 技能 | 一句话说明 | 依赖 |
|---|---|---|
| [disconf](skills/disconf/) | 查询和修改 Disconf 分布式配置中心的配置，带 dry-run 和删除护栏 | Python 3.8+ |

### disconf

Disconf 是百度开源的分布式配置管理平台，只有 Web 界面，没有 CLI 也没有 MCP。这个技能封装了它全部 20 个 HTTP 接口，把 JSESSIONID 会话管理、JSON 解析、密码脱敏都处理掉了。

```bash
export DISCONF_HOST=http://disconf.example.com
export DISCONF_USER=your_account
export DISCONF_PASSWORD=your_password

python scripts/disconf.py apps                          # 列出应用
python scripts/disconf.py resolve --app my-app --env rd # 名字→id
python scripts/disconf.py get --config-id 3256          # 读配置
python scripts/disconf.py update --config-id 3256 --value "pool.size=20" --dry-run
```

内置的安全护栏：改配置默认走 dry-run 预演、删除必须二次确认 configId、密码字段自动脱敏。因为改 Disconf 会直接推送到 Zookeeper 并对所有客户端实时生效，没有回滚。

细节见 [skills/disconf/SKILL.md](skills/disconf/SKILL.md)。

## MCP 服务列表

| 服务 | 一句话说明 | 依赖 |
|---|---|---|
| [mysql](mcps/mysql/) | 通用只读 MySQL 查询，10 个工具，支持多环境对比 | `mcp>=2`, `pymysql` |
| [archery](mcps/archery/) | 把 Archery 的 HTTP 查询接口封装成标准 MCP | 纯标准库 + `mcp>=2` |
| [confluence](mcps/confluence/) | 通过第三方 `mcp-atlassian` 接入 Confluence Server | `uvx` 自动拉取 |

三个服务都遵循同一条原则：**地址和凭据只从环境变量或本地配置文件读取，源码里不留任何默认值**。

### mysql

```bash
python -m pip install -r mcps/mysql/requirements.txt

# 方式一：环境变量直连
export MYSQL_HOST=db.example.com MYSQL_USER=reader MYSQL_PASSWORD=xxx MYSQL_DATABASE=your_db
python mcps/mysql/mysql_mcp_server.py

# 方式二：配置文件（多连接，可切换）
cp mcps/mysql/mysql_mcp_config.example.json ~/.mysql_mcp_config.json
export MYSQL_MCP_CONFIG=~/.mysql_mcp_config.json
```

默认只读：非 `SELECT`/`SHOW`/`DESCRIBE`/`EXPLAIN`/`WITH`/`TABLE` 的语句一律拒绝，需要写入必须在连接配置里显式设 `allow_write: true`。

### archery

Archery 只提供普通 HTTP JSON 接口，不实现 MCP 协议，所以这里做了薄封装。

```bash
export ARCHERY_ROOT=http://archery.example.com
export ARCHERY_TOKEN=ark_xxx
python mcps/archery/archery_client.py --instance "mysql-host-01:3306" --db your_db --sql "select 1"
```

踩过的坑都写进 README 了：实例名必须带端口、`SELECT *` 会被服务端拦截（工具会自动展开字段）、限流返回的是 401 而不是 429。

### confluence

本仓库不含源码，只是把第三方 `mcp-atlassian` 的接入方式文档化（PAT 鉴权、空间过滤、`uvx` 隔离运行）。

## 安装使用

技能遵循 Claude Skills 的通用格式（`SKILL.md` + `scripts/` + `references/`），可以被任何支持该格式的 Agent 直接读取。

**方式一：克隆到本地技能目录**

```bash
git clone https://github.com/studeyang/ai-toolkit.git
ln -s "$(pwd)/ai-toolkit/skills/disconf" ~/.workbuddy/skills/disconf   # macOS / Linux
```

Windows 用 `mklink /D`，或直接把 `skills/<name>` 目录复制过去。

**方式二：只取单个技能**

```bash
npx degit studeyang/ai-toolkit/skills/disconf ~/.workbuddy/skills/disconf
```

MCP 不需要"安装"，在客户端的 `mcp.json` 里指向对应脚本的绝对路径即可，配置示例见各目录 README。

## 贡献

欢迎提 Issue 和 PR。完整规范见 [AGENTS.md](AGENTS.md)，摘要如下：

- 不要提交内网域名、IP、账号密码、内部应用名、工号、本机绝对路径（CI 会自动扫，但它只是事后报警）
- 脚本语法检查通过（`python -m py_compile` / `node --check`）
- `SKILL.md` 的 frontmatter 有 `name` 和 `description`
- MCP 目录里只提交 `*_mcp_config.example.json`，真实配置文件已在 `.gitignore` 中
- 提交信息正文同样不能含敏感信息

**维护者注意**：CI 会用 `secrets.PRIVATE_PATTERNS` 扫自己公司的域名/应用名。该 Secret 每行一个正则片段，例如：

```
your-company\.com
internal-app-name
```

未配置时只跑通用规则（内网 IP 段、硬编码密码、私钥、本机路径），不会报错。

## 许可证

[MIT](LICENSE)

各条目若引用了第三方项目，其许可证在对应目录内单独标注。例如 disconf 技能只是调用 Disconf 的 HTTP 接口，没有复制其代码，与上游 Apache-2.0 项目无隶属关系；confluence 目录仅文档化 `mcp-atlassian` 的用法，不含其源码。
