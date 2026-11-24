#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Disconf 配置中心命令行客户端（仅依赖 Python 标准库）

封装 Disconf Web 管理 API：登录、查应用、查配置、读配置值、改配置、新建、删除。
会话通过 JSESSIONID cookie 保持。

地址和账号必须显式提供（命令行参数或环境变量），脚本本身不内置任何默认地址或凭据。
用法见 --help 或 SKILL.md。
"""

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

SESSION_CACHE = os.path.join(tempfile.gettempdir(), ".disconf_session.json")


# ---------------- 基础设施 ----------------------------


def die(msg, code=1):
    """统一错误输出，避免异常栈干扰 Agent 阅读"""
    print(json.dumps({"success": False, "error": msg}, ensure_ascii=False), file=sys.stderr)
    sys.exit(code)


def make_opener():
    """带 cookie 的 opener，保证 JSESSIONID 在同一进程多次请求间保持"""
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar


def request(opener, url, method="GET", data=None, timeout=30):
    """
    发一个请求，返回 (status, body_text, headers)。
    不做异常转义，让上层能区分网络错误和业务错误。
    """
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method)
    if body:
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    req.add_header("User-Agent", "disconf-cli/1.0")
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), dict(e.headers)


def parse_json(text):
    """Disconf 老版本偶发返回 HTML 错误页，这里统一兜底"""
    try:
        return json.loads(text)
    except Exception:
        return None


# ---------------- 会话管理 ----------------------------


def login(host, user, password, remember="0", opener=None):
    """登录并返回 (opener, sessionId)。失败时抛出 ValueError。"""
    opener = opener or make_opener()[0]
    status, text, _ = request(
        opener,
        f"{host}/api/account/signin",
        method="POST",
        data={"name": user, "password": password, "remember": remember},
    )
    payload = parse_json(text)
    if payload is None:
        raise ValueError(f"登录返回非 JSON（HTTP {status}），可能是服务端异常")
    if str(payload.get("success")) != "true":
        field = (payload.get("message") or {}).get("field") or {}
        reason = "; ".join(f"{k}: {v}" for k, v in field.items()) or payload.get("message") or "未知原因"
        raise ValueError(f"登录失败：{reason}")
    return opener, payload.get("sessionId")


def save_session(host, user, sid):
    """缓存 sessionId 和登录时间，供后续进程复用（cookie 无法跨进程持久化，所以这里重登）"""
    try:
        with open(SESSION_CACHE, "w", encoding="utf-8") as f:
            json.dump({"host": host, "user": user, "sessionId": sid, "ts": time.time()}, f)
    except Exception:
        pass


def cached_session(host, user):
    try:
        with open(SESSION_CACHE, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("host") == host and d.get("user") == user:
            return d.get("sessionId")
    except Exception:
        return None
    return None


class Client:
    """
    Disconf 客户端。

    由于 Disconf 的鉴权完全依赖 JSESSIONID cookie（不是 Bearer token，也不认
    sessionId 查询参数），每个进程都必须重新登录一次。登录成本很低（一次 POST），
    所以这里不做跨进程复用，只在单进程内保持率。
    """

    def __init__(self, host=None, user=None, password=None):
        self.host = (host or os.environ.get("DISCONF_HOST") or "").rstrip("/")
        self.user = user or os.environ.get("DISCONF_USER") or ""
        self.password = password or os.environ.get("DISCONF_PASSWORD") or ""
        if not self.host:
            raise ValueError(
                "没有配置 Disconf 地址。请用 --host 指定，或设置环境变量 DISCONF_HOST。"
                "例如：export DISCONF_HOST=http://disconf.example.com"
            )
        if not self.user or not self.password:
            raise ValueError(
                "没有配置登录凭据。请用 --user/--password 指定，或设置环境变量 "
                "DISCONF_USER / DISCONF_PASSWORD。"
            )
        self.opener, _ = make_opener()
        self.session_id = None

    def ensure_login(self):
        if self.session_id:
            return
        self.opener, sid = login(self.host, self.user, self.password, opener=self.opener)
        self.session_id = sid
        save_session(self.host, self.user, sid)

    def get(self, path, params=None):
        self.ensure_login()
        url = self.host + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        status, text, headers = request(self.opener, url, timeout=30)
        payload = parse_json(text)
        if payload is None:
            # 会话可能在服务端过期，重登一次再试，避免直接报错
            if status == 500:
                self.session_id = None
                self.ensure_login()
                status, text, headers = request(self.opener, url, timeout=30)
                payload = parse_json(text)
                if payload is None:
                    raise ValueError(f"接口返回非 JSON（HTTP {status}）：{text[:200]}")
            else:
                raise ValueError(f"接口返回非 JSON（HTTP {status}）：{text[:200]}")
        return payload, headers

    def write(self, path, method, data):
        self.ensure_login()
        url = self.host + path
        status, text, _ = request(self.opener, url, method=method, data=data, timeout=30)
        payload = parse_json(text)
        if payload is None:
            raise ValueError(f"接口返回非 JSON（HTTP {status}）：{text[:200]}")
        return payload

    # ---- 业务封装 ----

    def list_apps(self):
        payload, _ = self.get("/api/app/list")
        self._raise_if_failed(payload)
        return ((payload.get("page") or {}).get("result")) or []

    def list_envs(self):
        payload, _ = self.get("/api/env/list")
        self._raise_if_failed(payload)
        return ((payload.get("page") or {}).get("result")) or []

    def list_versions(self, app_id, env_id=None):
        params = {"appId": app_id}
        if env_id is not None:
            params["envId"] = env_id
        payload, _ = self.get("/api/web/config/versionlist", params)
        self._raise_if_failed(payload)
        return ((payload.get("page") or {}).get("result")) or []

    def list_configs(self, app_id, env_id, version):
        """按 app+env+version 三要素精确查配置列表（三个参数都是必填）"""
        payload, _ = self.get(
            "/api/web/config/list",
            {"appId": app_id, "envId": env_id, "version": version},
        )
        self._raise_if_failed(payload)
        return ((payload.get("page") or {}).get("result")) or []

    def get_config(self, config_id):
        """按 configId 取单条配置，返回含完整 value 的字典"""
        payload, _ = self.get(f"/api/web/config/{config_id}")
        self._raise_if_failed(payload)
        return payload.get("result") or {}

    def zk_deploy(self, app_id, env_id, version):
        payload, _ = self.get(
            "/api/zoo/zkdeploy", {"appId": app_id, "envId": env_id, "version": version}
        )
        self._raise_if_failed(payload)
        return payload.get("result") or {}

    def update_item(self, config_id, value):
        """改配置项的值"""
        payload = self.write(f"/api/web/config/item/{config_id}", "PUT", {"value": value})
        self._raise_if_failed(payload)
        return payload

    def update_file(self, config_id, file_content):
        """改配置文件的内容"""
        payload = self.write(
            f"/api/web/config/filetext/{config_id}", "PUT", {"fileContent": file_content}
        )
        self._raise_if_failed(payload)
        return payload

    def create_item(self, app_id, env_id, version, key, value):
        payload = self.write(
            "/api/web/config/item",
            "POST",
            {"appId": app_id, "envId": env_id, "version": version, "key": key, "value": value},
        )
        self._raise_if_failed(payload)
        return payload

    def create_file(self, app_id, env_id, version, file_name, file_content):
        payload = self.write(
            "/api/web/config/filetext",
            "POST",
            {
                "appId": app_id,
                "envId": env_id,
                "version": version,
                "fileName": file_name,
                "fileContent": file_content,
            },
        )
        self._raise_if_failed(payload)
        return payload

    def delete_config(self, config_id, confirm=None):
        """
        删除配置。必需显式传入 confirm == config_id，
        防止 Agent 误触发（Disconf 没有回收站，删了直接推送 ZK）。
        """
        if str(confirm) != str(config_id):
            raise ValueError(
                "删除必须二次确认：请传入 --confirm 且值等于 configId，否则可能误删线上配置"
            )
        payload = self.write(f"/api/web/config/{config_id}", "DELETE", None)
        self._raise_if_failed(payload)
        return payload

    @staticmethod
    def _raise_if_failed(payload):
        if str(payload.get("success")) != "true":
            field = (payload.get("message") or {}).get("field") or {}
            detail = "; ".join(f"{k}: {v}" for k, v in field.items())
            if not detail:
                detail = str(payload.get("message") or "未知错误")
            raise ValueError(f"操作失败：{detail}")


# ---------------- 输出 ----------------------------


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def mask_secret(value, preview_limit=None):
    """
    配置值里常含密码。默认不打印明文，用 --show-value 才展开，
    避免密码出现在会话记录里。

    preview_limit：dry-run 场景下配置动辄几百行，只回前 N 行，
    避免 diff 输出淹没对话。真正写入时不受影响，写的是完整内容。
    """
    if not value:
        return value
    lines = value.splitlines()
    out = []
    for line in lines:
        stripped = line.lstrip()
        # 注释掉的行也按同样规则处理，否则密码会从注释里漏出来
        is_comment = stripped.startswith("#") or stripped.startswith("!")
        body = stripped[1:] if is_comment else line
        if "=" in body:
            k, _, v = body.partition("=")
            kl = k.strip().lower()
            # 只匹配真正的敏感字段名。注意不能用宽泛的 "key"：
            # jdbc-key / redis.key 这类是分片标识或普通键名，不是密码
            secret_words = ("password", "passwd", "pwd", "secret", "token", "credential")
            if any(w in kl for w in secret_words):
                prefix = "#" if is_comment else ""
                out.append(f"{prefix}{k}=(*已隐藏*)")
                continue
        out.append(line)
    if preview_limit and len(out) > preview_limit:
        head = "\n".join(out[:preview_limit])
        return f"{head}\n... (共 {len(out)} 行，此处仅显示前 {preview_limit} 行)"
    return "\n".join(out)


# ---------------- 命令 ----------------------------


def cmd_apps(c, a):
    apps = c.list_apps()
    emit({"success": True, "count": len(apps), "apps": apps})


def cmd_envs(c, a):
    envs = c.list_envs()
    emit({"success": True, "count": len(envs), "envs": envs})


def cmd_versions(c, a):
    versions = c.list_versions(a.app_id, a.env_id)
    emit({"success": True, "appId": a.app_id, "versions": versions})


def cmd_list(c, a):
    items = c.list_configs(a.app_id, a.env_id, a.version)
    slim = [
        {
            "configId": it.get("configId"),
            "appName": it.get("appName"),
            "envName": it.get("envName"),
            "version": it.get("version"),
            "type": it.get("type"),
            "key": it.get("key"),
            "modifyTime": it.get("modifyTime"),
        }
        for it in items
    ]
    emit({"success": True, "count": len(slim), "configs": slim})


def cmd_get(c, a):
    cfg = c.get_config(a.config_id)
    value = cfg.get("value", "")
    if not a.show_value:
        value = mask_secret(value)
    emit(
        {
            "success": True,
            "configId": cfg.get("configId"),
            "appName": cfg.get("appName"),
            "envName": cfg.get("envName"),
            "version": cfg.get("version"),
            "type": cfg.get("type"),
            "key": cfg.get("key"),
            "modifyTime": cfg.get("modifyTime"),
            "value": value,
            "valueMasked": not a.show_value,
            "valueLength": len(cfg.get("value", "")),
        }
    )


def cmd_zk(c, a):
    info = c.zk_deploy(a.app_id, a.env_id, a.version)
    emit({"success": True, "result": info})


def cmd_update(c, a):
    # 先把旧值读出来，做 diff，让用户看到到底改了什么
    before = c.get_config(a.config_id)
    old_value = before.get("value", "")
    if a.value_file:
        with open(a.value_file, encoding="utf-8") as f:
            new_value = f.read()
    else:
        new_value = a.value or ""

    if a.dry_run:
        emit(
            {
                "success": True,
                "dryRun": True,
                "configId": a.config_id,
                "key": before.get("key"),
                "type": before.get("type"),
                "envName": before.get("envName"),
                "version": before.get("version"),
                "beforePreview": mask_secret(old_value, preview_limit=a.preview_lines),
                "afterPreview": mask_secret(new_value, preview_limit=a.preview_lines),
                "beforeLength": len(old_value),
                "afterLength": len(new_value),
                "note": (
                    "未实际写入。去掉 --dry-run 才会生效。"
                    "Disconf 的修改会推送 ZK 并对所有订阅客户端实时生效，没有灰度也没有回滚。"
                    "改配置文件时传入的内容会整段替换原文件，不是增量合并，务必确认内容完整。"
                ),
            }
        )
        return

    if before.get("type") == "配置文件":
        c.update_file(a.config_id, new_value)
    else:
        c.update_item(a.config_id, new_value)
    emit(
        {
            "success": True,
            "configId": a.config_id,
            "key": before.get("key"),
            "appName": before.get("appName"),
            "envName": before.get("envName"),
            "version": before.get("version"),
            "before": mask_secret(old_value),
            "after": mask_secret(new_value),
            "note": "已写入。Disconf 会推送到 ZK，所有订阅该应用的客户端将实时拉取新配置。",
        }
    )


def cmd_create(c, a):
    if a.kind == "file":
        if not a.file_name:
            die("新建配置文件必须提供 --file-name")
        content = a.value or ""
        if a.value_file:
            with open(a.value_file, encoding="utf-8") as f:
                content = f.read()
        if a.dry_run:
            emit({"success": True, "dryRun": True, "would": "create_file", "fileName": a.file_name})
            return
        c.create_file(a.app_id, a.env_id, a.version, a.file_name, content)
        emit({"success": True, "created": a.file_name, "kind": "file"})
    else:
        if a.dry_run:
            emit({"success": True, "dryRun": True, "would": "create_item", "key": a.key})
            return
        c.create_item(a.app_id, a.env_id, a.version, a.key, a.value or "")
        emit({"success": True, "created": a.key, "kind": "item"})


def cmd_delete(c, a):
    before = c.get_config(a.config_id)
    if a.dry_run:
        emit({"success": True, "dryRun": True, "wouldDelete": {
            "configId": before.get("configId"), "key": before.get("key"),
            "appName": before.get("appName"), "envName": before.get("envName"),
        }, "note": "未删除。"})
        return
    c.delete_config(a.config_id, confirm=a.confirm)
    emit({"success": True, "deleted": a.config_id, "key": before.get("key")})


def cmd_find(c, a):
    """
    跨应用按 key 关键字搜配置。

    Disconf 没有全局搜索接口，只能逐个 app+env+version 调 list，
    466 个应用 × 2 环境 × N 版本会非常慢。所以默认限制扫描应用数，
    并且优先建议用户用 --app 缩小范围。
    """
    apps = c.list_apps()
    envs = c.list_envs()
    keyword = (a.keyword or "").lower()
    hits = []
    scanned_items = 0
    scanned_apps = 0

    targets = apps
    if a.app:
        targets = [x for x in apps if a.app.lower() in str(x.get("name", "")).lower()]
        if not targets:
            raise ValueError(f"没有名字匹配 '{a.app}' 的应用，先用 apps 命令看真实名称")

    for app in targets:
        if a.max_apps and scanned_apps >= a.max_apps:
            break
        scanned_apps += 1
        for env in envs:
            if a.env and a.env.lower() not in str(env.get("name", "")).lower():
                continue
            try:
                versions = c.list_versions(app["id"], env["id"])
            except ValueError:
                continue
            for ver in versions:
                try:
                    items = c.list_configs(app["id"], env["id"], ver)
                except ValueError:
                    continue
                scanned_items += len(items) or 0
                for it in items:
                    if keyword in str(it.get("key", "")).lower():
                        hits.append({
                            "configId": it.get("configId"),
                            "appName": it.get("appName"),
                            "envName": it.get("envName"),
                            "version": it.get("version"),
                            "type": it.get("type"),
                            "key": it.get("key"),
                            "modifyTime": it.get("modifyTime"),
                        })
    truncated = bool(a.max_apps and scanned_apps >= a.max_apps and len(targets) > scanned_apps)
    emit({
        "success": True,
        "keyword": a.keyword,
        "scannedApps": scanned_apps,
        "scannedItems": scanned_items,
        "count": len(hits),
        "truncated": truncated,
        "hint": "扫描被截断，用 --app / --env 缩小范围，或调大 --max-apps" if truncated else None,
        "hits": hits,
    })


def cmd_resolve(c, a):
    """把 app 名 + env 名 + version 解析成 id，方便后续调用"""
    apps = c.list_apps()
    envs = c.list_envs()
    app = next((x for x in apps if str(x.get("name")) == a.app), None)
    if not app and a.app:
        cands = [x for x in apps if a.app.lower() in str(x.get("name", "")).lower()]
        if len(cands) == 1:
            app = cands[0]
    if not app:
        raise ValueError(f"找不到应用：{a.app}")
    env = None
    if a.env:
        env = next((x for x in envs if str(x.get("name")) == a.env), None)
        if not env:
            cands = [x for x in envs if a.env.lower() in str(x.get("name", "")).lower()]
            if len(cands) == 1:
                env = cands[0]
    versions = c.list_versions(app["id"], env["id"] if env else None)
    emit({
        "success": True,
        "appId": app["id"], "appName": app["name"],
        "envId": env["id"] if env else None, "envName": env["name"] if env else None,
        "versions": versions,
    })


# ---------------- 入口 ----------------------------


def build_parser():
    p = argparse.ArgumentParser(
        prog="disconf",
        description="Disconf 配置中心命令行客户端（查/改配置）",
        epilog="所有命令输出 JSON，便于 Agent 解析。修改类命令建议先加 --dry-run 看 diff。",
    )
    p.add_argument("--host", default=None, help="Disconf 地址，如 http://disconf.example.com（也可用 $DISCONF_HOST）")
    p.add_argument("--user", default=None, help="登录账号（也可用 $DISCONF_USER）")
    p.add_argument("--password", default=None, help="登录密码（也可用 $DISCONF_PASSWORD）")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("apps", help="列出所有应用").set_defaults(func=cmd_apps)
    sub.add_parser("envs", help="列出所有环境").set_defaults(func=cmd_envs)

    sp = sub.add_parser("versions", help="列出某应用的版本")
    sp.add_argument("--app-id", type=int, required=True)
    sp.add_argument("--env-id", type=int, default=None)
    sp.set_defaults(func=cmd_versions)

    sp = sub.add_parser("list", help="列出配置项（需 app+env+version 三者）")
    sp.add_argument("--app-id", type=int, required=True)
    sp.add_argument("--env-id", type=int, required=True)
    sp.add_argument("--version", required=True)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("get", help="读取单条配置（含完整值）")
    sp.add_argument("--config-id", type=int, required=True)
    sp.add_argument("--show-value", action="store_true", help="显示明文（默认隐藏密码类字段）")
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("zk", help="查看 ZK 部署情况")
    sp.add_argument("--app-id", type=int, required=True)
    sp.add_argument("--env-id", type=int, required=True)
    sp.add_argument("--version", required=True)
    sp.set_defaults(func=cmd_zk)

    sp = sub.add_parser("update", help="修改配置（默认支持 --dry-run 预览）")
    sp.add_argument("--config-id", type=int, required=True)
    sp.add_argument("--value", default=None)
    sp.add_argument("--value-file", default=None, help="从文件读取新内容，适合多行配置文件")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--preview-lines", type=int, default=15, help="dry-run 时每个片段预览行数，默认 15")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("create", help="新建配置项或配置文件")
    sp.add_argument("--app-id", type=int, required=True)
    sp.add_argument("--env-id", type=int, required=True)
    sp.add_argument("--version", required=True)
    sp.add_argument("--kind", choices=["item", "file"], default="item")
    sp.add_argument("--key", default=None, help="配置项 key（kind=item 时必填）")
    sp.add_argument("--file-name", default=None, help="配置文件名称（kind=file 时必填，须 .properties/.xml）")
    sp.add_argument("--value", default=None)
    sp.add_argument("--value-file", default=None)
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_create)

    sp = sub.add_parser("delete", help="删除配置（必须 --confirm 等于 configId）")
    sp.add_argument("--config-id", type=int, required=True)
    sp.add_argument("--confirm", default=None, help="二次确认，值必须等于 configId")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_delete)

    sp = sub.add_parser("find", help="按 key 关键字跨应用搜索配置")
    sp.add_argument("--keyword", required=True)
    sp.add_argument("--app", default=None, help="限定应用名（模糊匹配），强烈建议提供以提速")
    sp.add_argument("--env", default=None, help="限定环境名（模糊匹配）")
    sp.add_argument("--max-apps", type=int, default=30, help="最多扫描多少个应用，默认 30，防全量扫描过慢")
    sp.set_defaults(func=cmd_find)

    sp = sub.add_parser("resolve", help="把应用名/环境名解析成 id")
    sp.add_argument("--app", required=True)
    sp.add_argument("--env", default=None)
    sp.set_defaults(func=cmd_resolve)

    return p


def main():
    args = build_parser().parse_args()
    try:
        client = Client(args.host, args.user, args.password)
        args.func(client, args)
    except ValueError as e:
        die(str(e))
    except urllib.error.URLError as e:
        target = args.host or os.environ.get("DISCONF_HOST") or "(未配置)"
        die(f"网络不可达：{e}。请确认地址 {target} 可访问（是否需要内网/VPN）")
    except KeyboardInterrupt:
        die("已中断", 130)


if __name__ == "__main__":
    main()
