#!/usr/bin/env python3
"""按 .github/bucket-updater.json 的配置，批量同步 Scoop manifest 的版本信息。

为什么用配置而不是每个包一个 workflow：
    新增包时只需在 .github/bucket-updater.json 的 packages 里加一条，不用再写 YAML。

配置项（.github/bucket-updater.json）::

    {
      "packages": [
        {
          "name":     "weixin",                     // 可选，默认取 file 的文件名
          "file":     "bucket/weixin.json",         // 本地 manifest 路径（相对仓库根目录）
          "upstream": "https://.../weixin.json",    // 上游 manifest 的 raw URL
          "sync": {                                 // 只同步这里列出的字段，其余保持原样
            "version": "version",                   // 本地字段: 上游字段（两侧都支持点号路径，如 autoupdate.url）
            "hash":    "hash",
            "url":     "url",
            "autoupdate.url": "autoupdate.url"
          },
          "verify_url": true,      // 可选，默认 true：更新 url 前先 HEAD 一次，避免写死链
          "allow_downgrade": false // 可选，默认 false：只有上游版本更高才更新
        }
      ]
    }

    sync 的值除了"上游字段路径"字符串外，还支持模板：
        "url": { "template": "https://host/App_$version.exe#/dl.7z" }
    $version 会被替换成本次同步到的上游版本号。

用法::

    python3 scripts/update-packages.py [--message-file PATH]

    --message-file  把 git commit message 写到该文件（供 CI 用 git commit -F 读取）

退出码：0 表示执行成功（可能有变更，也可能没有）；1 表示配置/上游数据有问题。
"""

import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, ".github", "bucket-updater.json")


def version_key(version):
    """把 '4.2.0.12' 变成可比较的元组，忽略其中的非数字噪声。"""
    parts = []
    for chunk in str(version).split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def get_path(data, dotted_path, where):
    """按点号路径取上游字段，例如 'autoupdate.url'。"""
    node = data
    for key in dotted_path.split("."):
        if not isinstance(node, dict) or key not in node:
            raise KeyError(f"{where}: 上游数据里找不到字段 '{dotted_path}'")
        node = node[key]
    return node


def get_path_or_none(data, dotted_path):
    try:
        return get_path(data, dotted_path, "local")
    except KeyError:
        return None


def set_path(data, dotted_path, value):
    """按点号路径写入，缺失的中间层级会自动创建。"""
    keys = dotted_path.split(".")
    node = data
    for key in keys[:-1]:
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    node[keys[-1]] = value


def fetch_json(url, attempts=3):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "scoopps-bucket-updater"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8-sig"))
        except Exception as exc:  # 网络抖动重试
            last = exc
            print(f"  fetch retry {i + 1}/{attempts}: {exc}")
    raise RuntimeError(f"无法获取上游 manifest: {url} ({last})")


def head_status(url):
    """只做连通性检查；网络异常返回 None（不阻塞更新）。"""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "scoopps-bucket-updater"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:
        print(f"  warning: url check skipped: {exc}")
        return None


def read_text(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write_manifest(path, data):
    """保持仓库约定：4 空格缩进、CRLF、结尾换行。"""
    text = json.dumps(data, indent=4, ensure_ascii=False).replace("\n", "\r\n") + "\r\n"
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def sync_package(pkg):
    """返回 (本地路径, 旧版本, 新版本)；无需更新时返回 None。"""
    name = pkg.get("name") or os.path.splitext(os.path.basename(pkg["file"]))[0]
    rel_path = pkg["file"]
    local_path = os.path.join(ROOT, rel_path)
    if not os.path.isfile(local_path):
        raise FileNotFoundError(f"{name}: 本地文件不存在: {rel_path}")

    sync = pkg.get("sync") or {}
    if "version" not in sync:
        raise ValueError(f"{name}: sync 里必须包含 version 字段")

    try:
        local = json.loads(read_text(local_path))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name}: {rel_path} 不是合法 JSON: {exc}")

    upstream = fetch_json(pkg["upstream"])

    version_spec = sync["version"]
    upstream_version = (
        get_path(upstream, version_spec, name)
        if isinstance(version_spec, str)
        else version_spec["template"]
    )
    current_version = str(local.get("version", "0"))
    print(f"{name}: local={current_version} upstream={upstream_version}")

    is_newer = version_key(upstream_version) > version_key(current_version)
    if version_key(upstream_version) == version_key(current_version):
        print(f"{name}: 已是最新，跳过")
        return None
    if not is_newer and not pkg.get("allow_downgrade", False):
        print(f"{name}: 上游版本更低，跳过（如需降级请设置 allow_downgrade）")
        return None

    changes = {}
    for field, spec in sync.items():
        if isinstance(spec, str):
            value = get_path(upstream, spec, name)
        elif isinstance(spec, dict) and "template" in spec:
            value = (
                spec["template"]
                .replace("$version", str(upstream_version))
                .replace("$matchHead", ".".join(str(upstream_version).split(".")[:3]))
            )
        else:
            raise ValueError(f"{name}: sync.{field} 配置不合法（应为字段路径或 template）")

        if get_path_or_none(local, field) != value:
            changes[field] = value

    if not changes:
        print(f"{name}: 版本号变了但字段内容一致，跳过")
        return None

    if "url" in changes and pkg.get("verify_url", True):
        status = head_status(changes["url"].split("#")[0])
        print(f"{name}: url check -> HTTP {status}")
        if status and status >= 400:
            raise RuntimeError(f"{name}: 上游下载地址不可用 (HTTP {status}): {changes['url']}")

    for field, value in changes.items():
        print(f"{name}: {field} = {value}")
        set_path(local, field, value)

    write_manifest(local_path, local)
    return rel_path, current_version, str(upstream_version)


def main():
    message_file = None
    if "--message-file" in sys.argv:
        message_file = sys.argv[sys.argv.index("--message-file") + 1]

    with open(CONFIG, encoding="utf-8") as f:
        config = json.load(f)

    packages = config.get("packages") or []
    print(f"检查 {len(packages)} 个包 ...\n")

    updated, failed = [], []
    for pkg in packages:
        try:
            result = sync_package(pkg)
        except Exception as exc:
            print(f"ERROR: {exc}")
            failed.append(str(exc))
            continue
        if result:
            updated.append(result)
        print()

    if updated:
        print("本次更新:")
        for rel_path, old, new in updated:
            print(f"  - {rel_path}: {old} -> {new}")
    else:
        print("没有需要更新的包。")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Scoop manifest 更新\n\n")
            if updated:
                for rel_path, old, new in updated:
                    f.write(f"- `{rel_path}`: {old} -> **{new}**\n")
            else:
                f.write("没有需要更新的包。\n")
            if failed:
                f.write("\n#### 失败\n\n")
                for msg in failed:
                    f.write(f"- {msg}\n")

    if message_file:
        if len(updated) == 1:
            rel_path, old, new = updated[0]
            name = os.path.splitext(os.path.basename(rel_path))[0]
            lines = [f"Update {name} to {new}", "", f"{rel_path}: {old} -> {new}"]
        else:
            lines = ["Update package manifests", ""]
            lines += [f"{rel_path}: {old} -> {new}" for rel_path, old, new in updated]
        with open(message_file, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines).rstrip() + "\n")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
