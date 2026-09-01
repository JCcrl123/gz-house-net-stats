#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""Daily scraper for Guangzhou new house online-signing data from official API.

数据来源：广州市住房和城乡建设局 · 阳光家缘 · 房地产项目信息
官方接口：
  - 楼盘列表：  /ysqgk/Api/WebApi/fdcxmxxlb.ashx
  - 楼盘详情：  /ysqgk/Api/WebApi/fdcxmjbxx.ashx
  - 楼栋列表：  /ysqgk/Api/WebApi/xmldxx.ashx
  - 销控明细：  /ysqgk/Api/WebApi/xmxkbxx.ashx
官网： https://zfcj.gz.gov.cn/zfcj/fyxx/fdcxmxx/

所有数据均来自上述官方公开接口，不引用任何第三方。
"""
import json
import os
import sys
import re
import gzip
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode
import requests

# ===== 官方接口 =====
BASE_URL     = "https://zfcj.gz.gov.cn/ysqgk/Api/WebApi/fdcxmxxlb.ashx"  # 楼盘列表
DETAIL_URL   = "https://zfcj.gz.gov.cn/ysqgk/Api/WebApi/fdcxmjbxx.ashx"  # 楼盘基本信息
BUILDING_URL = "https://zfcj.gz.gov.cn/ysqgk/Api/WebApi/xmldxx.ashx"     # 楼栋列表（拿 buildingId）
SALES_URL    = "https://zfcj.gz.gov.cn/ysqgk/Api/WebApi/xmxkbxx.ashx"    # 销控表（楼层×房号）

# 分片归档：archive/<YYYY-MM-DD>.json.gz  +  archive/meta.json
# 背景：历史单体 archive.json 已 >100MB，GitHub 会拒绝推送(GH001)，故改为按日分片并 gzip 压缩。
# 好处：单文件恒定在数百 KB 量级，永不再触碰 GitHub 100MB 单文件上限。
ARCHIVE_DIR    = "archive"
META_NAME      = "meta.json"
LEGACY_ARCHIVE = "archive.json"   # 旧单体归档，迁移后删除

# ===== 监控的楼盘（展示名 → 官方备案名）=====
PROJECTS = {
    "珑曜上城": {"keywords": ["珑曜花园"]},
    "星汇锦城": {"keywords": ["盛颂花园"]},
    "繁花里":   {"keywords": ["繁花院"]},
    "檐屿城":   {"keywords": ["檐屿花园"]},
    "亚运城环宇熙和": {
        "keywords": ["亚运城"],
        "filter":   lambda r: r.get("presell") == "20260088"
                                 and "B-6~B-9" in r.get("projectName", "")
    }
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer":    "https://zfcj.gz.gov.cn/zfcj/fyxx/fdcxmxx/",
    "Accept":     "application/json, text/javascript, */*",
}

HEADERS_DETAIL = {
    "User-Agent": HEADERS["User-Agent"],
    "Referer":    "https://zfcj.gz.gov.cn/zfcj/fyxx/projectdetail/index.html",
    "Accept":     "application/json, text/javascript, */*",
}


# ===== 通用抓取（含 3 次重试）=====
def _get(url, headers=None, retries=3):
    headers = headers or HEADERS
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt == retries - 1:
                raise
            print(f"[scraper] retry {attempt+1}/{retries} for {url[:120]}: {e}")
            time.sleep(2 * (attempt + 1))
    raise last_err  # pragma: no cover


# ===== 楼盘列表 =====
def fetch_page(project_name, page=1, page_size=50, retries=3):
    params = {
        "sProjectName":    project_name,
        "sProjectAddress": "",
        "sDeveloper":      "",
        "sPresellNo":      "",
        "page":            page,
        "pageSize":        page_size,
    }
    url = f"{BASE_URL}?{urlencode(params)}"
    return _get(url, HEADERS, retries)


def fetch_all(keyword):
    """分页拉取 keyword 命中的全部官方楼盘记录。"""
    records = []
    page = 1
    total_page = 1
    while page <= total_page:
        data = fetch_page(keyword, page=page, page_size=50)
        total_page = data.get("totalPage", 0) or 1
        records.extend(data.get("data", []))
        page += 1
        time.sleep(0.3)
    return records


# ===== 销控相关（官方接口）=====
def fetch_building_list(project_id, presell_no):
    """根据 projectId + 预售证号，获取该预售证下的楼栋列表（含 buildingId / buildName）。"""
    params = {"sProjectId": project_id, "sPreSellNo": presell_no}
    data = _get(f"{BUILDING_URL}?{urlencode(params)}", HEADERS_DETAIL)
    return data.get("data", [])


def fetch_sales_control(building_id):
    """根据 buildingId 获取该楼栋全部楼层×房号的销控数据。"""
    params = {"buildingId": building_id}
    data = _get(f"{SALES_URL}?{urlencode(params)}", HEADERS_DETAIL)
    return data.get("data", [])


def fetch_project_detail(project_id):
    """获取楼盘基本信息和预售面积统计（备用，本项目核心是销控）。"""
    params = {"sProjectId": project_id}
    data = _get(f"{DETAIL_URL}?{urlencode(params)}", HEADERS_DETAIL)
    return data.get("data", {})


def clean_building_name(name):
    return re.sub(r"\s+", " ", name).strip()


def _extract_floor(build_name):
    """从官方 buildName 中提取简洁栋号，例如：
       '2栋（自编2#楼）' → '2栋'
       '自编号5-1'      → '自编号5-1'
       'B-6住宅'        → 'B-6住宅'  (兜底)
    """
    m = re.search(r"(\d+)\s*栋", build_name)
    if m:
        return f"{m.group(1)}栋"
    m = re.search(r"(自编[号]?)([\dA-Za-z\-]+)", build_name)
    if m:
        return f"自编号{m.group(2)}"
    return build_name


def _fetch_one_building_detail(project_id, presell_no):
    """抓取某预售证下所有楼栋的销控表数据。
    返回: {"buildings": [...], "units": {buildingId: {name, fullName, floors}}, "error": str|None}
    失败容错：单个楼栋失败不影响其它楼栋，最终 error 字段记录所有错误信息。"""
    detail = {"buildings": [], "units": {}, "error": None}
    if not (project_id and presell_no):
        detail["error"] = "missing projectId/presell"
        return detail
    try:
        detail["buildings"] = fetch_building_list(project_id, presell_no)
    except Exception as e:
        detail["error"] = f"fetch_building_list failed: {e}"
        return detail
    errors = []
    for sub in detail["buildings"]:
        bid = sub.get("buildingId")
        if not bid:
            continue
        try:
            floors = fetch_sales_control(bid)
            detail["units"][bid] = {
                "name":     _extract_floor(sub.get("buildName", "")),
                "fullName": sub.get("buildName", ""),
                "floors":   floors,
            }
            time.sleep(0.3)
        except Exception as e:
            errors.append(f"{bid}:{e}")
    if errors:
        detail["error"] = "; ".join(errors)
    return detail


# ===== 构建单个楼盘快照 =====
def build_project_snapshot(alias, cfg):
    records = []
    for kw in cfg["keywords"]:
        records.extend(fetch_all(kw))
    f = cfg.get("filter")
    if f:
        records = [r for r in records if f(r)]

    # 按 projectId 去重 + 按预售证排序
    seen = set()
    uniq = []
    for r in records:
        pid = r.get("projectId")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        uniq.append(r)
    uniq.sort(key=lambda x: x.get("presell", "") or "")

    buildings = []
    for r in uniq:
        project_id = r.get("projectId", "")
        presell    = r.get("presell", "")
        sold       = int(r.get("houseSoldNum",   0) or 0)
        unsale     = int(r.get("houseUnsaleNum", 0) or 0)
        total      = sold + unsale

        bld = {
            "name":      clean_building_name(r.get("projectName", "")),
            "presell":   presell,
            "developer": r.get("developer", ""),
            "address":   r.get("projectAddress", ""),
            "total":     total,
            "signed":    sold,
            "remaining": unsale,
            "rate":      round(sold / total, 6) if total > 0 else 0,
        }

        # 抓取销控表：保留 44f754b 历史实现（含失败容错）
        detail = _fetch_one_building_detail(project_id, presell)
        bld["detail"] = detail
        buildings.append(bld)

    total_all      = sum(b["total"]     for b in buildings)
    signed_all     = sum(b["signed"]    for b in buildings)
    remaining_all  = sum(b["remaining"] for b in buildings)
    summary = {
        "total":     total_all,
        "signed":    signed_all,
        "remaining": remaining_all,
        "rate":      round(signed_all / total_all, 6) if total_all > 0 else 0,
        "count":     len(buildings),
    }
    return {"buildings": buildings, "summary": summary}


def _migrate_legacy_archive():
    """把旧的单体 archive.json 拆分为按日分片（幂等，迁移后自动跳过）。

    之所以放在 scraper 内调用：.github/workflows/ 下的文件需要 workflow 权限才能修改，
    在无法更新工作流的情况下，让代码侧自行完成迁移即可。
    """
    if not os.path.exists(LEGACY_ARCHIVE):
        return
    try:
        import migrate_archive
        migrate_archive.main()
    except Exception as e:
        print(f"[scraper] 旧归档迁移失败（将导致推送超限）: {e}")


# ===== 入口 =====
def run(target_date=None):
    _migrate_legacy_archive()

    if target_date is None:
        # 北京时间（UTC+8）日期，对齐 cron 09:00 CST
        target_date = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")

    out = {}
    for alias, cfg in PROJECTS.items():
        print(f"[scraper] fetching {alias} ...")
        try:
            out[alias] = build_project_snapshot(alias, cfg)
        except Exception as e:
            print(f"[scraper] ERROR {alias}: {e}")
            out[alias] = {
                "buildings": [],
                "summary":   {"total": 0, "signed": 0, "remaining": 0, "rate": 0, "count": 0},
                "error":     str(e),
            }

    # 分片写入：每天一个 gzip 文件，不再读取/重写整个历史归档（旧实现每天要重写 >100MB）
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    day_path = os.path.join(ARCHIVE_DIR, f"{target_date}.json.gz")
    with gzip.open(day_path, "wt", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    meta = {
        "source":       "https://zfcj.gz.gov.cn/zfcj/fyxx/fdcxmxx/",
        "updated":      datetime.now().isoformat(),
        "fetched_date": target_date,
    }
    with open(os.path.join(ARCHIVE_DIR, META_NAME), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    kb = os.path.getsize(day_path) / 1024
    print(f"[scraper] archived {target_date} -> {day_path} ({kb:.0f} KB)")
    return {"meta": meta, "records": {target_date: out}}


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else None
    run(date)