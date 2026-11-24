# Disconf Web API 参考

适用于 Disconf 2.6.x / 6.x 系列的 disconf-web 服务端。以下接口是从前端 JS（`assets/js/*.js`）里逆出来的，并在真实实例上逐条验证过。

文中 `{{host}}` 指你的 Disconf 地址。

## 鉴权

```
POST {{host}}/api/account/signin
Content-Type: application/x-www-form-urlencoded

name=<账号>&password=<密码>&remember=0
```

成功返回：

```json
{"message":{},"sessionId":"...","success":"true","result":{"visitor":{"id":6,"name":"admin","role":null}}}
```

同时下发 `Set-Cookie: JSESSIONID=...; Path=/; HttpOnly`。**后续所有请求靠这个 cookie 鉴权**。`sessionId` 只是回显，把它当查询参数传没有任何作用（实测无效，别浪费时间）。

### 未登录时的异常行为

未登录访问受保护接口时，Disconf **不返回 401**，而是 HTTP 500 + 一整页 Tomcat 堆栈。根因是 `LoginInterceptor` 试图输出 JSON 错误时缺 `org.codehaus.jackson.map.SerializerProvider`（Jackson 1.x 的类，打包时漏了）。

这是上游项目的已知缺陷。排查时不要误判成"服务宕机"——先确认 cookie 是否还在。脚本已经对这种情况做了自动重登兜底。

## 查询类

| 方法 | 路径 | 参数 | 说明 |
|---|---|---|---|
| GET | `/api/app/list` | 无 | 应用列表，返回 `{id, name}` |
| GET | `/api/env/list` | 无 | 环境列表，返回 `{id, name}` |
| GET | `/api/web/config/versionlist` | `appId`，可选 `envId` | 版本字符串列表，如 `["1_0_0_0"]` |
| GET | `/api/web/config/list` | `appId`、`envId`、`version` **三者必填** | 配置清单；缺任一返回"不能为null" |
| GET | `/api/web/config/{configId}` | 路径参数 | 单条配置，**含完整 value** |
| GET | `/api/web/config/zk/{configId}` | 路径参数 | 单条配置的机器列表 |
| GET | `/api/zoo/zkdeploy` | `appId`、`envId`、`version` | 整体 ZK 部署情况 |
| GET | `/api/web/config/download/{configId}` | 路径参数 | 下载配置文件，`application/octet-stream` |
| GET | `/api/web/config/downloadfilebatch` | `appId`、`envId`、`version` | 批量下载（打包） |

`list` 返回的单条结构：

```json
{
  "configId": 3256,
  "appName": "my-app",
  "appId": "19",
  "version": "1_0_0_0",
  "envId": "1",
  "envName": "rd1",
  "type": "配置文件",          // 或 "配置项"
  "typeId": "0",              // 0=配置文件, 1=配置项
  "key": "db.properties",
  "value": "",                // 列表接口里恒为空，要读值必须走详情接口
  "createTime": "20180730200118",
  "modifyTime": "201907181936",
  "machineSize": "0",
  "machineList": "[]",
  "errorNum": "0"
}
```

**关键细节**：`list` 里的 `value` 永远是空字符串。这是很多人第一次用会觉得"配置是空的"的原因——必须用 `GET /api/web/config/{configId}` 才能拿到真实内容。

## 写入类

| 方法 | 路径 | 参数 | 说明 |
|---|---|---|---|
| PUT | `/api/web/config/item/{configId}` | `value` | 改**配置项**的值 |
| PUT | `/api/web/config/filetext/{configId}` | `fileContent` | 改**配置文件**内容（整段替换） |
| POST | `/api/web/config/item` | `appId`、`envId`、`version`、`key`、`value` | 新建配置项 |
| POST | `/api/web/config/filetext` | `appId`、`envId`、`version`、`fileName`、`fileContent` | 新建配置文件（`fileName` 限 `.properties` / `.xml`） |
| POST | `/api/web/config/file` | multipart | 上传配置文件（前端用 iframe 表单提交） |
| DELETE | `/api/web/config/{configId}` | 路径参数 | 删除配置 |
| POST | `/api/app` | `app`、`desc`、`emails` | 新建应用 |

改配置项和改配置文件是**两个不同接口**，必须按 `type` 分流。调错接口不会报错，但也不会生效——这是排查"我改了为什么不生效"时的首要怀疑点。

## 客户端开放 API（免登录）

Disconf 给非 Java 客户端留的只读接口，**不需要登录**，不走上面的 cookie 鉴权：

| 方法 | 路径 | 参数 | 说明 |
|---|---|---|---|
| GET | `/api/config/item` | `app`、`env`、`version`、`key` | 返回 `{"status":1,"message":"","value":"..."}`，失败时 `status:0` |
| GET | `/api/config/file` | `app`、`env`、`version`、`key` | 直接返回文件内容（附件形式） |

示例：

```
GET {{host}}/api/config/item?app=my-app&env=rd1&version=1_0_0_0&key=someKey
→ {"status":1,"message":"","value":"..."}

GET {{host}}/api/config/item?app=nonexistent
→ {"status":0,"message":"app nonexistent doesn't exist in db.","value":""}
```

### 安全提醒

这两个接口**完全免鉴权**。任何能访问该地址的人都能读走全部配置内容，包括明文数据库密码。如果你的实例暴露在非受信网络，建议：

- 在网络层限制访问来源（安全组 / ACL）
- 或让运维确认是否可关闭这两个接口
- 至少不要把它们暴露到公网

这不是本技能引入的风险，是 Disconf 的原始设计。但既然要用它，就该知道这个事实。

## 完整接口清单

从前端 JS grep 汇总：

```
/api/account/session          GET    会话校验
/api/account/signin           POST   登录
/api/app/list                 GET    应用列表
/api/app                      POST   新建应用
/api/env/list                 GET    环境列表
/api/web/config/list          GET    配置清单
/api/web/config/versionlist   GET    版本列表
/api/web/config/{id}          GET    配置详情
/api/web/config/item/{id}     PUT    改配置项
/api/web/config/filetext/{id} PUT    改配置文件内容
/api/web/config/file/{id}     POST   上传配置文件
/api/web/config/item          POST   新建配置项
/api/web/config/filetext      POST   新建配置文件
/api/web/config/{id}          DELETE 删除配置
/api/web/config/zk/{id}       GET    ZK 机器列表
/api/web/config/download/{id} GET    下载配置
/api/web/config/downloadfilebatch GET 批量下载
/api/zoo/zkdeploy             GET    ZK 部署情况
/api/config/item              GET    开放API-配置项（免登录）
/api/config/file              GET    开放API-配置文件（免登录）
```

## Zookeeper 存储结构

配置最终落在 ZK 上：

```
/disconf/{app}_{version}_{env}/item/{key}    配置项
/disconf/{app}_{version}_{env}/file/{key}    配置文件
```

例如 `/disconf/my-app_1_0_0_0_rd1/file/db.properties`。

客户端订阅这个节点，节点变化即刻推送——**这就是为什么改 Disconf 是实时生效、且没有任何缓冲期的**。也意味着一旦改错，所有在线实例会同时拿到坏配置。动手前务必在测试环境验证。

## 版本兼容性

这些接口在 Disconf 2.6.x 到 6.x 之间基本稳定。不同企业的定制版本可能有差异（比如加了 SSO、改了 URL 前缀）。如果你实例的接口路径不同，先在浏览器开发者工具里看真实请求，再对照上面的表定位差异。
