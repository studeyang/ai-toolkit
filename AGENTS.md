# AGENTS.md

给在本仓库工作的 AI Agent（以及人类贡献者）的行为规范。

**这是一个公开仓库。** 任何提交上去的内容，包括 git 历史，都可能被永久检索到。下面每一条规则都对应一次真实踩过的坑，不是理论。

---

## 一、安全红线（最高优先级）

### 1.1 绝不把真实敏感信息写进任何被提交的文件

禁止出现：内网域名、内网 IP、公司名、内部应用名、工号、真实账号密码、Token、私钥、个人本机绝对路径。

需要示例时，一律用占位符：

| 类型 | 占位写法 |
|---|---|
| 域名 | `https://confluence.example.com`、`http://archery.example.com` |
| 主机 | `<host>`、`mysql-host-01:3306` |
| 数据库/表 | `your_database`、`your_table` |
| 账号/密码 | `<user>`、`<password>`、`your_account` |
| Token | `<PAT>`、`ark_xxx` |
| 空间/应用名 | `SPACE_A,SPACE_B`、`my-app` |
| 文件路径 | `/absolute/path/to/...`、`%USERPROFILE%\.local\bin\uvx.exe` |

### 1.2 不要把敏感词清单本身写进公开源码

这是最反直觉、也最容易犯的一条。

**错误做法**：为了拦截公司域名，把域名明文写进 CI 的扫描正则。

```yaml
# 错！等于把公司名挂到仓库首页
net=$(git grep -niEI '你的公司域名\.com|10\.0\.0\.0/8' ...)
```

**正确做法**：代码里只放通用规则（内网 IP 段这类不含具体公司信息的模式），需要针对具体公司/应用的词放进 GitHub Secret。

```yaml
env:
  PRIVATE_PATTERNS: ${{ secrets.PRIVATE_PATTERNS }}
```

Secret 里每行一个正则片段，CI 运行时拼接：

```bash
re=$(printf '%s' "$PRIVATE_PATTERNS" | tr '\n' '|' | sed 's/|$//')
```

未配置 Secret 时，通用规则照旧生效，不要因此报错退出。

### 1.3 真实配置文件绝不提交

命名规范：真实配置叫 `<name>_mcp_config.json`，仓库里只放 `<name>_mcp_config.example.json`。

`.gitignore` 已包含：

```
**/*_mcp_config.json
!**/*_mcp_config.example.json
```

新增其他类型的本地配置时，同步补 `.gitignore`，并在 CI 的「检查不该提交的文件」步骤里加对应规则。

### 1.4 清理敏感信息要查三处，缺一不可

| 位置 | 检查方式 | 清理工具 |
|---|---|---|
| 文件内容 | `git grep -niEI "关键词" HEAD -- .` | `git filter-repo --replace-text` |
| **commit message** | `git log --format="%B" \| grep -iE "关键词"` | `git filter-repo --replace-message` |
| 对象库（blob） | 遍历 `git rev-list --all --objects` 逐个 `cat-file -p` | `git reflog expire --expire=now --all` + `git gc --prune=now --aggressive` |

**前两处必须分两次跑 filter-repo。** 只跑 `--replace-text` 会漏掉提交信息正文里的内容。

### 1.5 force push 不能从 GitHub 上删除旧内容

`git push --force` 只让分支不再指向旧 commit，**被覆盖的 commit 仍可通过 `GET /repos/{owner}/{repo}/commits/{sha}` 读到**，会作为悬空对象保留数周到数月。

想让旧内容彻底消失，只有两条路：

1. **删仓库重建**（最快最彻底，仓库小的时候首选）
2. 向 GitHub Support 申请清除缓存/悬空对象

判断依据：`git cat-file -t` 本地查不到 ≠ 平台上查不到。要实测 `curl -o /dev/null -w "%{http_code}" https://api.github.com/repos/{owner}/{repo}/commits/{sha}`，期望 `422`/`404`。

---

## 二、提交前自检清单

每一条都能在 30 秒内跑完，别省。

```bash
# 1. 看清楚要提交什么（不要盲 git add -A）
git status --short
git diff --cached --name-only

# 2. 扫敏感词（暂存区的最终内容，不是 diff）
git diff --cached | grep -iE "公司名|内网域名|工号|真实路径"

# 2b. 连这篇规范自身也要扫——写"错误示例"时很容易把真实域名写回去
grep -niE "公司名|内网域名|工号|真实路径" AGENTS.md README.md        # 应无输出

# 3. 清掉 py_compile 产生的缓存
find . -name "__pycache__" -type d -not -path "./.git/*" -exec rm -rf {} +

# 4. 语法检查
for f in $(git ls-files "*.py"); do python -m py_compile "$f"; done

# 5. 确认没有真实配置混进来
git ls-files | grep -E "_mcp_config\.json" | grep -v example   # 应无输出
```

**验证 `.gitignore` 真的生效**（不要相信它看起来对）：

```bash
# 放一个假的真实配置，确认被标记为 !!
touch mcps/mysql/mysql_mcp_config.json
git status --ignored --short mcps/mysql/
git add -A --dry-run | grep mysql    # 真实配置不该出现在输出里
rm mcps/mysql/mysql_mcp_config.json
```

---

## 三、新增 Skill 的规范

目录结构：

```
skills/<name>/
├── SKILL.md          # 必需
├── scripts/          # 可执行脚本（可选）
└── references/       # 按需加载的参考文档（可选）
```

**SKILL.md 的 frontmatter 必须包含 `name` 和 `description`**，CI 会检查，缺了直接失败：

```yaml
---
name: disconf
description: 查询和修改 Disconf 分布式配置中心的配置...
---
```

其他要求：

- 脚本优先用**纯标准库**，减少使用者的安装成本
- 输出统一为 JSON，便于 Agent 解析
- 破坏性操作必须提供 `--dry-run`，删除类操作必须二次确认
- 涉及密码字段的输出默认脱敏，加显式参数才展开

---

## 四、新增 MCP 的规范

目录结构（每个 MCP 是独立可引用单元，各自带依赖，互不共享）：

```
mcps/<name>/
├── <name>_mcp_server.py    # 入口（或 src/index.ts）
├── requirements.txt        # 或 package.json，必需
├── <name>_mcp_config.example.json   # 配置模板（如需）
└── README.md               # 必需
```

**README 必须写清三件事**：

1. 暴露了哪些工具、每个工具的参数
2. 需要设置哪些环境变量（**只写占位符**）
3. 怎么写进客户端的 `mcp.json`

硬规矩：

- 地址和凭据**只从环境变量或本地配置文件读**，源码里不留任何默认值
- 缺少必填配置时给出可操作的中文提示，不要静默失败或回退到危险默认
- 只读类服务默认拒绝写操作，需要写入必须显式配置开启

---

## 五、代码与格式约定

- **换行符统一 LF**，`.gitattributes` 已配置。不要让 Windows 的 CRLF 混进来，否则其他人 clone 后整个文件都是 diff
- Python 3.10+，用 `from __future__ import annotations` 保持类型注解兼容
- 面向用户的错误信息用中文，且要能指导下一步动作
- 不要为了"看起来完整"而添加用不上的抽象层

---

## 六、Commit 规范

采用 Conventional Commits：

```
feat(mcps): 新增 xxx 服务
fix(ci): 修正 xxx 误报
docs(readme): 补充 xxx 说明
chore: 调整 xxx
```

- 一个 commit 做一件事，不要把重构和功能混在一起
- **提交信息正文同样不能含敏感信息**（这里翻过车）
- 提交前用 `git log --format="%B" | grep -iE "关键词"` 复查

---

## 七、CI 能力与局限

CI 包含两个 job：

| job | 内容 |
|---|---|
| `lint` | Python 语法检查、Skill 结构校验、MCP 结构校验 |
| `secret-scan` | 敏感信息扫描、不该提交的文件检查 |

**必须清楚 CI 拦不住什么**，别把它当安全网：

| 局限 | 说明 |
|---|---|
| 只在 push 到 main 后触发 | 是**事后报警**，不是事前拦截，代码已经进历史了 |
| 不扫 git 历史 | 只扫当前工作区已跟踪文件 |
| 不扫 commit message | `git grep` 看不到提交信息 |
| `.github/` 目录被排除 | 在 CI 配置里写域名反而抓不到 |
| fork 来的 PR 拿不到 Secret | 公司域名规则对贡献者的 PR 失效 |
| 跳过二进制文件 | 图片、压缩包里藏的内容抓不到 |
| `-i` 与 `-I` 极易混淆 | `-i` 忽略大小写，`-I` 跳过二进制。两者都要，写成 `-niEI` |

最后一条是真实 bug：曾经只写了 `-I`，导致全大写域名写法直接漏网。**改扫描规则后，务必造一个违规样本实测能命中，再造一个正常样本实测不误伤。**

---

## 八、网络与环境

- `git push` 偶发 `schannel: server closed abruptly` 或 `CONNECT tunnel failed, response 502`，**直接重试**通常就能成功，不是配置问题
- 未认证的 GitHub API 限流是 60 次/小时/IP。批量验证时改用 `raw.githubusercontent.com` 直取文件内容，或用 `github.com/.../commit/{sha}` 看状态码，不占 API 配额
- Windows 下 Python 进程和 Git Bash 看到的 `/tmp` 不是同一个目录，临时文件放工作区内

---

## 九、许可证

MIT。新引入第三方代码或依赖时，在对应目录的 README 里标注来源与许可证；只是调用第三方 HTTP 接口或复用其配置方式时，明确写清"不含其源码"及无隶属关系。
