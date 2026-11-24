# mcps/

MCP（Model Context Protocol）Servers 放在这里，每个目录是一个独立的可引用单元。

## 现有服务

| 服务 | 类型 | 说明 | 依赖 |
|---|---|---|---|
| [mysql](mysql/) | stdio | 通用只读 MySQL 查询，10 个工具，支持多环境对比、索引/字段检索 | `mcp>=2`, `pymysql` |
| [archery](archery/) | stdio | 把 Archery 的 HTTP 查询接口封装成标准 MCP | 纯标准库 + `mcp>=2` |
| [confluence](confluence/) | stdio | 通过第三方 `mcp-atlassian` 接入 Confluence Server，本仓库无自建源码 | `uvx`（自动拉取） |

```
mcps/
├── mysql/
│   ├── mysql_mcp_server.py
│   ├── mysql_mcp_config.example.json   # 配置模板
│   ├── requirements.txt
│   └── README.md
├── archery/
│   ├── archery_mcp_server.py
│   ├── archery_client.py               # 纯标准库 HTTP 客户端，也可单独作 CLI
│   ├── requirements.txt
│   └── README.md
└── confluence/
    ├── requirements.txt
    └── README.md
```

## 新增 MCP 的约定

每个 MCP 是一个独立单元，各自带自己的 `requirements.txt` / `package.json`，互不共享依赖。建议结构：

```
mcps/
└── your-mcp/
    ├── requirements.txt  # 或 package.json
    ├── src/index.ts      # 入口（Python 直接放 <name>_mcp_server.py）
    └── README.md         # 工具列表 + 客户端配置示例
```

`README.md` 里至少写清楚：暴露了哪些工具、每个工具的参数、以及如何写进客户端的 `mcp.json`。

## 两条硬规矩

1. **不要硬编码任何地址和凭据。** 一律从环境变量或配置文件读，README 里只写占位符（`<host>` / `<token>` / `your_account`）。
2. **真实配置文件绝不提交。** 命名统一为 `<name>_mcp_config.json`，仓库里只放 `<name>_mcp_config.example.json`。`.gitignore` 和 CI 都会拦这道。

MCP 的配置文件通常含明文密码，一旦进 git 历史就永久可查，即使后续 commit 删掉也没用。
