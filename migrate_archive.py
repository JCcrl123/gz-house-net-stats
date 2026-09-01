#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""一次性迁移：把旧的单体 archive.json 拆分为 archive/<YYYY-MM-DD>.json.gz。

设计要点
--------
1. 幂等：没有旧 archive.json 时直接跳过，可安全重复执行。
2. 安全：先把所有分片写完并逐个校验（解压 + json.loads）通过，才删除旧文件；
   任何一步失败都保留 archive.json 原样，绝不丢数据。
3. 低内存：逐日写出并立即释放，避免同时持有两份全量数据。

用法：python migrate_archive.py
"""
import json
import gzip
import os
import sys

ARCHIVE_DIR = "archive"
META_NAME   = "meta.json"
LEGACY      = "archive.json"

SOURCE = "https://zfcj.gz.gov.cn/zfcj/fyxx/fdcxmxx/"


def _write_day(date, rec):
    """写出单日分片并回读校验，返回文件大小（字节）。"""
    path = os.path.join(ARCHIVE_DIR, f"{date}.json.gz")
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
    # 回读校验，确保落盘内容可正常解析
    with gzip.open(path, "rt", encoding="utf-8") as f:
        json.load(f)
    return os.path.getsize(path)


def main():
    if not os.path.exists(LEGACY):
        print(f"[migrate] 未发现 {LEGACY}，跳过（已是分片结构）")
        return 0

    print(f"[migrate] 读取旧归档 {LEGACY} ...")
    with open(LEGACY, "r", encoding="utf-8") as f:
        archive = json.load(f)

    records = archive.get("records", {}) or {}
    meta    = archive.get("meta", {}) or {}
    if not records:
        print(f"[migrate] {LEGACY} 中无 records，跳过")
        return 0

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    total = len(records)
    print(f"[migrate] 共 {total} 个日期，开始拆分 ...")

    ok, written_bytes = 0, 0
    for i, (date, rec) in enumerate(sorted(records.items()), 1):
        try:
            size = _write_day(date, rec)
        except Exception as e:
            print(f"[migrate] ✗ 写出失败 {date}: {e}", file=sys.stderr)
            print(f"[migrate] 中止迁移，保留 {LEGACY} 以防数据丢失", file=sys.stderr)
            return 1
        written_bytes += size
        ok += 1
        if i % 10 == 0 or i == total:
            print(f"[migrate]   {i}/{total}  ({written_bytes/1048576:.1f} MB 已写出)")

    if ok != total:
        print(f"[migrate] 校验失败：{ok}/{total}，保留 {LEGACY}", file=sys.stderr)
        return 1

    # 写 meta
    meta.setdefault("source", SOURCE)
    with open(os.path.join(ARCHIVE_DIR, META_NAME), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 全部校验通过后才删除旧文件（git 历史仍保留，可回溯）
    os.remove(LEGACY)
    print(f"[migrate] ✓ 拆分完成：{total} 天 -> {ARCHIVE_DIR}/，"
          f"共 {written_bytes/1048576:.1f} MB（gzip），已删除 {LEGACY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
