#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""读取 archive.json，计算日/周/月环比，生成可日期查询的单文件 HTML 网站。

数据来源：广州市住房和城乡建设局 · 阳光家缘 · 房地产项目信息
          https://zfcj.gz.gov.cn/zfcj/fyxx/fdcxmxx/
所有数据均来自阳光家缘官方公开接口，不做任何人工估算。
"""
import json
from datetime import datetime, timedelta

ARCHIVE = "archive.json"
OUT     = "广州新房网签数据.html"


# =====================================================================
# 数据加载 + 日/周/月环比计算（沿用既有逻辑，保持原网站日/周/月新增的语义）
# =====================================================================
def load_archive():
    with open(ARCHIVE, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_comparisons(archive):
    dates    = sorted(archive.get("records", {}).keys())
    records  = archive["records"]
    projects = list(next(iter(records.values())).keys()) if records else []
    out = {"dates": dates, "meta": archive.get("meta", {}), "projects": projects, "records": {}}
    for date in dates:
        out["records"][date] = {}
        for proj in projects:
            snap = records[date].get(proj, {"buildings": [], "summary": {}})
            prev   = _prev_date(date, dates)
            wstart = _week_monday(date, dates)
            mstart = _month_first(date, dates)
            lwstart = _last_week_monday(date, dates)
            lmstart = _last_month_first(date, dates)

            bld_out = []
            for b in snap.get("buildings", []):
                bld_out.append(_attach_compare(b, date, prev, wstart, mstart,
                                               lwstart, lmstart, records, proj))

            summary = snap.get("summary", {}).copy()
            summary = _attach_compare(summary, date, prev, wstart, mstart,
                                      lwstart, lmstart, records, proj, is_summary=True)
            summary["count"] = len(bld_out)

            # summary 不带 detail（前端不会用到，节省体积）
            out["records"][date][proj] = {"buildings": bld_out, "summary": summary}
    return out


def _prev_date(date, dates):
    idx = dates.index(date)
    return dates[idx - 1] if idx > 0 else None


def _week_monday(date, dates):
    """本周一（自然周起点：周一）。若无数据则回退到本周第一个有数据的日期。"""
    d       = datetime.strptime(date, "%Y-%m-%d")
    mon     = d - timedelta(days=d.weekday())
    mon_str = mon.strftime("%Y-%m-%d")
    cands   = [dd for dd in dates if mon_str <= dd <= date]
    return cands[0] if cands else None


def _month_first(date, dates):
    """本月 1 日。若无数据则回退到本月第一个有数据的日期。"""
    d         = datetime.strptime(date, "%Y-%m-%d")
    first     = d.replace(day=1)
    first_str = first.strftime("%Y-%m-%d")
    cands     = [dd for dd in dates if first_str <= dd <= date]
    return cands[0] if cands else None


def _last_week_monday(date, dates):
    """上一自然周周一，返回该周内第一个有数据的快照日期（用于"上周"参考）。

    数据口径：每个快照 dated D 实际包含 D-1（昨天）全天数据。
    因此上一自然周（周一~周日）的净新增 = 本周一快照 - 上周一快照。
    """
    d        = datetime.strptime(date, "%Y-%m-%d")
    this_mon = d - timedelta(days=d.weekday())
    last_mon = this_mon - timedelta(days=7)
    last_sun = last_mon + timedelta(days=6)
    lm_str   = last_mon.strftime("%Y-%m-%d")
    ls_str   = last_sun.strftime("%Y-%m-%d")
    cands    = [dd for dd in dates if lm_str <= dd <= ls_str]
    return cands[0] if cands else None


def _last_month_first(date, dates):
    """上一自然月 1 日，返回该月内第一个有数据的快照日期（用于"上月"参考）。

    数据口径：每个快照 dated D 实际包含 D-1（昨天）全天数据。
    因此上一自然月（1 日~月末）的净新增 = 本月 1 日快照 - 上月 1 日快照。
    """
    d              = datetime.strptime(date, "%Y-%m-%d")
    this_first     = d.replace(day=1)
    last_month_end = this_first - timedelta(days=1)
    last_month_fir = last_month_end.replace(day=1)
    lmf_str        = last_month_fir.strftime("%Y-%m-%d")
    lme_str        = last_month_end.strftime("%Y-%m-%d")
    cands          = [dd for dd in dates if lmf_str <= dd <= lme_str]
    return cands[0] if cands else None


def _attach_compare(item, date, prev, wstart, mstart, lwstart, lmstart,
                   records, proj, is_summary=False):
    out  = dict(item)
    curr = item.get("signed", 0) or 0
    d    = datetime.strptime(date, "%Y-%m-%d")
    is_monday       = (d.weekday() == 0)   # 自然周第一天
    is_month_first  = (d.day == 1)         # 自然月第一天

    # 日新增：当天 vs 前一天
    if prev and prev != date and prev in records and proj in records[prev]:
        ref_val = _get_ref_signed(prev, records, proj, item, is_summary)
        if ref_val is not None:
            out["day_delta"] = curr - ref_val
            out["day_pct"]   = round((curr - ref_val) / ref_val, 6) if ref_val > 0 \
                                else (0.0 if curr == ref_val else None)
        else:
            out["day_delta"], out["day_pct"] = None, None
    else:
        out["day_delta"], out["day_pct"] = None, None

    # 周累计新增：数据口径为"截止昨天（D-1）全天"。
    # - 自然周第一天（周一）：显示"上周（周一~周日）完整 7 天"数据
    #   → 参考点取上一自然周周一快照
    # - 自然周第二天起（周二~周日）：显示"本周累计"
    #   → 参考点取本周一快照
    week_ref = lwstart if is_monday else wstart
    if week_ref and week_ref in records and proj in records[week_ref]:
        ref_val = _get_ref_signed(week_ref, records, proj, item, is_summary)
        if ref_val is not None:
            out["week_delta"] = curr - ref_val
            out["week_pct"]   = round((curr - ref_val) / ref_val, 6) if ref_val > 0 \
                                else (0.0 if curr == ref_val else None)
        else:
            out["week_delta"], out["week_pct"] = None, None
    else:
        out["week_delta"], out["week_pct"] = None, None

    # 月累计新增：同上逻辑
    # - 自然月第一天（1 号）：显示"上月（1 日~月末）完整"数据
    #   → 参考点取上一自然月 1 日快照
    # - 自然月第二天起（2 号~月末）：显示"本月累计"
    #   → 参考点取本月 1 日快照
    month_ref = lmstart if is_month_first else mstart
    if month_ref and month_ref in records and proj in records[month_ref]:
        ref_val = _get_ref_signed(month_ref, records, proj, item, is_summary)
        if ref_val is not None:
            out["month_delta"] = curr - ref_val
            out["month_pct"]   = round((curr - ref_val) / ref_val, 6) if ref_val > 0 \
                                 else (0.0 if curr == ref_val else None)
        else:
            out["month_delta"], out["month_pct"] = None, None
    else:
        out["month_delta"], out["month_pct"] = None, None

    # 上周新增网签：上一自然周（周一~周日）净新增
    #   = 本周一快照 - 上周一快照
    if wstart and lwstart and wstart in records and lwstart in records \
       and proj in records[wstart] and proj in records[lwstart]:
        end_val   = _get_ref_signed(wstart, records, proj, item, is_summary)
        start_val = _get_ref_signed(lwstart, records, proj, item, is_summary)
        if end_val is not None and start_val is not None:
            out["last_week_delta"] = end_val - start_val
        else:
            out["last_week_delta"] = None
    else:
        out["last_week_delta"] = None

    # 上月新增网签：上一自然月（1 日~月末）净新增
    #   = 本月 1 日快照 - 上月 1 日快照
    if mstart and lmstart and mstart in records and lmstart in records \
       and proj in records[mstart] and proj in records[lmstart]:
        end_val   = _get_ref_signed(mstart, records, proj, item, is_summary)
        start_val = _get_ref_signed(lmstart, records, proj, item, is_summary)
        if end_val is not None and start_val is not None:
            out["last_month_delta"] = end_val - start_val
        else:
            out["last_month_delta"] = None
    else:
        out["last_month_delta"] = None

    return out


def _get_ref_signed(ref_date, records, proj, item, is_summary):
    ref_rec = records[ref_date][proj]
    if is_summary:
        ref = ref_rec.get("summary", {})
    else:
        ref = next((x for x in ref_rec.get("buildings", [])
                    if x.get("name") == item.get("name")), None)
    if ref is None:
        return None
    return ref.get("signed", 0) or 0


# =====================================================================
# HTML 生成（含 Modal 弹窗 + 销控表 CSS Grid 渲染）
# =====================================================================
def build_html(data):
    dates        = data["dates"]
    latest       = dates[-1] if dates else ""
    data_json    = json.dumps(data, ensure_ascii=False, indent=2)
    data_json    = data_json.replace("</", "<\\/")  # 防 </script> 注入

    mapping_notes = {
        "珑曜上城":         "官方备案名：珑曜花园",
        "星汇锦城":         "官方备案名：盛颂花园（越秀·大学·星汇锦城）",
        "繁花里":           "官方备案名：繁花院",
        "檐屿城":           "官方备案名：檐屿花园",
        "亚运城环宇熙和":   "阳光家缘未以“熙和/环宇熙和”备案；本表以最新在售官方组团“亚运城B地块B-6~B-9幢住宅（预售证20260088）”代理",
    }

    project_cards = []
    for proj in data["projects"]:
        s = data["records"][latest][proj]["summary"] if latest else {}
        project_cards.append(f'''
        <div class="card" data-proj="{proj}">
          <div class="card-title">{proj}</div>
          <div class="card-grid">
            <div><div class="lbl">预售总数</div><div class="val">{s.get('total', 0):,}</div></div>
            <div><div class="lbl">已网签</div><div class="val">{s.get('signed', 0):,}</div></div>
            <div><div class="lbl">剩余</div><div class="val">{s.get('remaining', 0):,}</div></div>
            <div><div class="lbl">去化率</div><div class="val">{s.get('rate', 0) * 100:.2f}%</div></div>
          </div>
        </div>
        ''')
    cards_html = "\n".join(project_cards)

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>广州新房网签数据</title>
<style>
:root {{
  --bg: #f5f7fa; --card: #fff; --primary: #1f4e78; --accent: #2e75b6;
  --text: #333; --muted: #666; --border: #e0e4e8;
  --up: #d32f2f; --down: #388e3c; --zero: #999;
  --warn: #fff3cd; --warn-t: #856404;
  --shadow: 0 2px 8px rgba(0, 0, 0, .06);
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial,
               "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--bg); color: var(--text); margin: 0; padding: 20px; line-height: 1.5;
}}
header {{
  max-width: 1300px; margin: 0 auto 20px; background: var(--card);
  padding: 22px 28px; border-radius: 10px; box-shadow: var(--shadow);
}}
header h1 {{ margin: 0 0 8px; font-size: 24px; color: var(--primary); }}
header p  {{ margin: 6px 0; color: var(--muted); font-size: 14px; }}
header a  {{ color: var(--accent); text-decoration: none; }}
.controls {{
  max-width: 1300px; margin: 0 auto 20px; display: flex; gap: 16px;
  align-items: center; flex-wrap: wrap;
}}
.controls label      {{ font-weight: 600; color: var(--muted); }}
.controls select     {{ font-size: 16px; padding: 8px 12px; border-radius: 6px;
                        border: 1px solid var(--border); background: #fff; }}
.cards {{
  max-width: 1300px; margin: 0 auto 20px;
  display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px;
}}
.card {{
  background: var(--card); padding: 16px 18px; border-radius: 10px;
  box-shadow: var(--shadow); cursor: pointer;
  transition: transform .15s, border-color .15s; border: 2px solid transparent;
}}
.card:hover  {{ transform: translateY(-2px); border-color: var(--accent); }}
.card.active {{ border-color: var(--primary); }}
.card-title  {{ font-weight: 700; font-size: 16px; color: var(--primary); margin-bottom: 10px; }}
.card-grid   {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
.card-grid .lbl {{ font-size: 12px; color: var(--muted); }}
.card-grid .val {{ font-size: 18px; font-weight: 700; color: var(--text); }}
.section {{
  max-width: 1300px; margin: 0 auto 28px; background: var(--card);
  border-radius: 10px; box-shadow: var(--shadow); overflow: hidden;
}}
.section-header {{
  padding: 16px 20px; color: #fff;
  background: linear-gradient(90deg, var(--primary), var(--accent));
  display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
}}
.section-header h2       {{ margin: 0; font-size: 18px; }}
.section-header .note    {{ font-size: 12px; opacity: .9; }}
.section-header .totals  {{ display: flex; gap: 18px; font-size: 14px; }}
.section-header .totals b{{ font-size: 16px; margin-left: 4px; }}
.table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
.table-wrap table {{ width: auto; min-width: 100%; border-collapse: collapse; font-size: 14px; }}
th, td {{ padding: 10px 12px; border: 1px solid var(--border); text-align: center; }}
th      {{ background: #f0f4f8; font-weight: 600; color: var(--primary); white-space: nowrap; }}
td.name {{ text-align: left; min-width: 120px; max-width: 220px; word-break: break-word; }}
td.num  {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr.total td {{ background: #fff3e0; font-weight: 700; }}
span.na   {{ color: var(--zero);  font-size: 12px; }}
span.up   {{ color: var(--up);    font-weight: 600; }}
span.down {{ color: var(--down);  font-weight: 600; }}
span.zero {{ color: var(--zero); }}
span.rate {{ color: var(--primary); font-weight: 600; }}
.warn {{
  background: var(--warn); color: var(--warn-t);
  padding: 12px 16px; border-radius: 8px; margin: 0 auto 20px;
  max-width: 1300px; font-size: 14px;
}}
footer {{ max-width: 1300px; margin: 30px auto; color: var(--muted); font-size: 13px; }}
footer p {{ margin: 6px 0; }}
.bld-link {{ color: var(--accent); cursor: pointer; text-decoration: underline; }}
.bld-link:hover {{ color: var(--primary); }}

/* ============== Modal 销控表 ============== */
.modal-overlay {{
  position: fixed; inset: 0; background: rgba(0, 0, 0, .55);
  z-index: 1000; display: none; align-items: flex-start; justify-content: center;
  padding: 24px; overflow: auto;
}}
.modal-overlay.open {{ display: flex; }}
.modal {{
  background: var(--card); border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, .25);
  width: min(1100px, 100%); display: flex; flex-direction: column; overflow: hidden;
}}
.modal-header {{
  padding: 14px 20px; background: var(--primary); color: #fff;
  display: flex; justify-content: space-between; align-items: center;
}}
.modal-header h3    {{ margin: 0; font-size: 18px; }}
.modal-header .close{{ cursor: pointer; font-size: 24px; line-height: 1; padding: 0 4px; }}
.modal-subtabs {{
  display: flex; gap: 8px; padding: 10px 20px 0;
  border-bottom: 1px solid var(--border); flex-wrap: wrap;
}}
.modal-subtabs .subtab {{
  padding: 6px 14px; border-radius: 6px 6px 0 0; cursor: pointer;
  border: 1px solid transparent; border-bottom: none;
  background: #f0f4f8; color: var(--muted);
}}
.modal-subtabs .subtab.active {{
  background: var(--card); color: var(--primary);
  border-color: var(--border); font-weight: 600;
}}
.modal-body {{ padding: 14px 20px 20px; overflow-x: auto; }}

/* 图例区：两行（与用户上传图片一致）*/
.legend-block {{
  background: #fafbfc; border: 1px solid var(--border);
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px;
}}
.legend-row {{
  display: flex; flex-wrap: wrap; gap: 14px; align-items: center; font-size: 13px;
}}
.legend-row + .legend-row {{ margin-top: 6px; }}
.legend-item {{ display: flex; align-items: center; gap: 6px; color: #333; }}
.legend-color {{
  width: 18px; height: 18px; border-radius: 4px; border: 1px solid rgba(0, 0, 0, .12);
  display: inline-block;
}}
.legend-mark {{
  width: 18px; height: 18px; display: inline-flex; align-items: center; justify-content: center;
  font-size: 15px; line-height: 1; color: #333;
}}

/* 销控表网格：左侧楼层列 + 右侧房号列（列数 = 该楼栋披露的「户数」，由 JS 动态生成） */
.sales-wrap {{
  display: grid;
  grid-template-columns: 70px repeat(4, minmax(72px, 1fr));
  gap: 8px;
  background: #fff;
  min-width: max-content;
}}
.sales-wrap .floor-cell {{
  background: #ECEFF1; font-size: 24px; font-weight: 700; color: #37474F;
  display: flex; align-items: center; justify-content: center;
  border-radius: 6px; min-height: 70px;
  position: sticky; left: 0; z-index: 2;
}}
.sales-wrap .room-cell {{
  min-height: 76px; border-radius: 6px; padding: 6px 4px;
  display: flex; flex-direction: column; justify-content: center; align-items: center;
  cursor: default; color: #fff; font-size: 13px; gap: 2px;
  transition: transform .12s ease, box-shadow .12s ease;
}}
/* 该楼层没有的房号位置：显示为浅灰虚线格，避免看起来像缺数据 */
.sales-wrap .room-cell:empty {{
  background: #f5f5f5;
  border: 1px dashed #e0e0e0;
}}
.sales-wrap .room-cell:hover {{
  transform: translateY(-2px);
  box-shadow: 0 4px 10px rgba(0, 0, 0, .15);
  outline: 2px solid rgba(255, 255, 255, .7);
}}
.sales-wrap .room-cell .room-num  {{ font-weight: 700; font-size: 14px; line-height: 1.1; }}
.sales-wrap .room-cell .room-area {{ font-size: 11px; opacity: .9; line-height: 1.1; }}
.sales-wrap .room-cell .room-mark {{
  font-size: 15px; line-height: 1; letter-spacing: 1px;
  color: rgba(255, 255, 255, .98); margin-top: 2px;
}}

/* ====== 15 种状态颜色（严格匹配用户上传图片的图例）====== */
.s-not-included   {{ background: #9E9E9E; color: #fff; }} /* 灰   未纳入 */
.s-frozen         {{ background: #1976D2; color: #fff; }} /* 蓝   强制冻结 */
.s-restricted     {{ background: #FB8C00; color: #fff; }} /* 橙   限制销售 */
.s-pledged        {{ background: #FFB300; color: #fff; }} /* 黄   抵押 */
.s-presell-off    {{ background: #E53935; color: #fff; }} /* 红   不可销售 */
.s-confirm-off    {{ background: #C62828; color: #fff; }} /* 红   确权不可售 */
.s-presell-on     {{ background: #7CB342; color: #fff; }} /* 亮绿 预售可售 */
.s-confirm-on     {{ background: #2E7D32; color: #fff; }} /* 深绿 确权可售 */
.s-sold           {{ background: #7CB342; color: #fff; }} /* 亮绿 已签约 */
.s-transferred    {{ background: #7CB342; color: #fff; }} /* 亮绿 已过户 */
.s-relocated      {{ background: #7CB342; color: #fff; }} /* 亮绿 回迁 */
.s-self-use       {{ background: #7CB342; color: #fff; }} /* 亮绿 自用 */
.s-public         {{ background: #7CB342; color: #fff; }} /* 亮绿 公建配套 */
.s-direct-mgmt    {{ background: #2E7D32; color: #fff; }} /* 深绿 直管 */
.s-divided        {{ background: #2E7D32; color: #fff; }} /* 深绿 分成 */
.s-sealed         {{ background: #2E7D32; color: #fff; }} /* 深绿 查封 */
.s-filed          {{ background: #7CB342; color: #fff; }} /* 亮绿 已备案 */
.s-unknown        {{ background: #E0E0E0; color: #666; }} /* 浅灰 未知 */

.room-tip {{
  position: fixed; background: rgba(0, 0, 0, .88); color: #fff;
  padding: 8px 10px; border-radius: 6px; font-size: 12px;
  pointer-events: none; z-index: 2000; display: none; max-width: 240px; line-height: 1.55;
}}
.no-detail {{ color: var(--muted); padding: 30px; text-align: center; }}

@media (max-width: 900px) {{
  body {{ padding: 10px; }}
  .cards {{ grid-template-columns: 1fr 1fr; }}
  .section {{ overflow-x: auto; }}
  table {{ min-width: 760px; }}
  .sales-wrap {{ grid-template-columns: 56px repeat(4, minmax(60px, 1fr)); gap: 6px; }}
  .sales-wrap .floor-cell {{ font-size: 18px; min-height: 60px; }}
  .sales-wrap .room-cell  {{ min-height: 60px; font-size: 12px; }}
}}
@media (max-width: 600px) {{
  .cards {{ grid-template-columns: 1fr; }}
  .modal-subtabs {{ gap: 4px; }}
}}
</style>
</head>
<body>
<header>
  <h1>广州新房网签数据</h1>
  <p>数据来源：<a href="https://zfcj.gz.gov.cn/zfcj/fyxx/fdcxmxx/" target="_blank">广州市住房和城乡建设局 · 阳光家缘 · 房地产项目信息</a>（每日自动抓取，仅引用官方数据）</p>
  <p>最后更新：<span id="lastUpdate"></span>｜当前选择日期：<span id="curDate" style="font-weight:700;color:var(--primary)"></span></p>
</header>

<div class="controls">
  <label for="dateSel">选择日期：</label>
  <select id="dateSel"></select>
  <span style="color:var(--muted);font-size:13px">默认显示最新日期；日/周/月环比需至少 2 天数据后自动出现；点击楼栋名查看销控表</span>
</div>

<div class="warn">
  <b>数据说明：</b>"已网签数"对应阳光家缘"住宅已售套数"；"剩余未网签"对应"住宅未售套数"；"预售总数"=已售+未售。<b>点击楼栋名称可弹出官方销控表（楼层×房号）</b>。由于官方 API 不返回"栋号"明确拆分，楼栋名即官方备案记录中的项目名称。
</div>

<div class="cards" id="cards">
{cards_html}
</div>

<div id="tables"></div>

<!-- Modal 销控表 -->
<div class="modal-overlay" id="modalOverlay">
  <div class="modal">
    <div class="modal-header">
      <h3 id="modalTitle">楼栋销控表</h3>
      <span class="close" onclick="closeModal()">&times;</span>
    </div>
    <div class="modal-subtabs" id="modalSubtabs"></div>
    <div class="modal-body" id="modalBody">
      <div id="salesLegend"></div>
      <div id="salesTableWrap"></div>
    </div>
  </div>
</div>
<div class="room-tip" id="roomTip"></div>

<footer>
  <p><b>楼盘名称映射：</b>楼栋名严格采用阳光家缘官方备案名称。珑曜上城→珑曜花园；星汇锦城→盛颂花园；繁花里→繁花院；檐屿城→檐屿花园；亚运城环宇熙和→官方暂无"熙和/环宇熙和"备案记录，暂以最新在售官方组团"亚运城B地块B-6~B-9幢住宅"代理。</p>
  <p>本系统每日自动从广州市住建局阳光家缘抓取，所有数据均来自官方公开接口，不做任何人工估算。点击楼栋名可弹出官方销控表（楼层×房号），状态色严格对照阳光家缘官方口径。</p>
</footer>

<script>
const ARCHIVE = {data_json};

const dateSel       = document.getElementById('dateSel');
const curDateSpan   = document.getElementById('curDate');
const lastUpdate    = document.getElementById('lastUpdate');
const tables        = document.getElementById('tables');
const cards         = document.getElementById('cards');
const modalOverlay  = document.getElementById('modalOverlay');
const modalTitle    = document.getElementById('modalTitle');
const modalSubtabs  = document.getElementById('modalSubtabs');
const salesLegend   = document.getElementById('salesLegend');
const salesTableWrap= document.getElementById('salesTableWrap');
const roomTip       = document.getElementById('roomTip');

// ===================================================================
// 6 种主色（与阳光家缘官方销控表一致）+ 符号叠加
// 次要状态（抵押/查封/公建/回迁/自用/未纳入/直管/分成/已备案等）改用符号
// ===================================================================
const COLOR_MAP = {{
  's-presell-off':  {{ color: '#E53935', label: '已签约/已售' }},
  's-confirm-off':  {{ color: '#C62828', label: '确权不可售'  }},
  's-presell-on':   {{ color: '#7CB342', label: '未签约/可售' }},
  's-confirm-on':   {{ color: '#2E7D32', label: '确权可售'    }},
  's-transferred':  {{ color: '#26A69A', label: '已过户'      }},
  's-frozen':       {{ color: '#1976D2', label: '强制冻结'    }},
}};
// 符号定义（与阳光家缘官方图例一致）：sym=显示字符，order=优先级（数字越小越靠前）
const MARK_DEFS = [
  {{ sym: '⊙',  order: 1,  label: '已签约',   test: r => r.pactStatus === 5 || r.pactStatus === 4 || r.pactStatus === 3 || r.status === 4 }},
  {{ sym: '■',  order: 2,  label: '已备案',   test: r => r.status === 17 || r.filed === 1 }},
  {{ sym: '◆',  order: 3,  label: '抵押',     test: r => r.pledgeStatus === 2 || r.status === 10 }},
  {{ sym: '●',  order: 4,  label: '查封',     test: r => r.sealed === 1 || r.status === 11 }},
  {{ sym: '★',  order: 5,  label: '未纳入预售', test: r => r.status === 18 }},
  {{ sym: '△',  order: 6,  label: '回迁房',   test: r => r.backMove === 1 || r.status === 12 }},
  {{ sym: '□',  order: 7,  label: '自用房',   test: r => r.useself === 1 || r.status === 13 }},
  {{ sym: '☆',  order: 8,  label: '公建配套', test: r => r.commonMatch === 1 || r.status === 14 }},
  {{ sym: '▲',  order: 9,  label: '直管房',   test: r => r.directly === 1 || r.status === 15 }},
  {{ sym: '■',  order: 10, label: '分成',     test: r => r.divide === 1 || r.status === 16 }},
];

// ===================================================================
// 工具
// ===================================================================
lastUpdate.textContent = (ARCHIVE.meta.updated || '').replace('T', ' ').substring(0, 19);
ARCHIVE.dates.slice().reverse().forEach(d => {{
  const opt = document.createElement('option');
  opt.value = d; opt.textContent = d;
  dateSel.appendChild(opt);
}});

function fmtNum(n)        {{ if (n === null || n === undefined || n === '') return '<span class="na">—</span>'; return n.toLocaleString(); }}
function fmtDelta(n)      {{ if (n === null || n === undefined || n === '') return '<span class="na">—</span>'; const sign = n > 0 ? '+' : ''; return `<span class="num">${{sign}}${{n.toLocaleString()}}</span>`; }}
function fmtPct(v)        {{ if (v === null || v === undefined || v === '') return '<span class="na">—</span>'; const cls = v > 0 ? 'up' : (v < 0 ? 'down' : 'zero'); return `<span class="${{cls}}">${{(v * 100).toFixed(2)}}%</span>`; }}
function fmtRate(v)       {{ if (v === null || v === undefined || v === '') return '<span class="na">—</span>'; return `<span class="rate">${{(v * 100).toFixed(2)}}%</span>`; }}
function fmtDeltaPct(v)   {{ if (v === null || v === undefined || v === '') return '<span class="na">—</span>'; const cls = v > 0 ? 'up' : (v < 0 ? 'down' : 'zero'); const sign = v > 0 ? '+' : ''; return `<span class="${{cls}}">${{sign}}${{(v * 100).toFixed(2)}}%</span>`; }}

function escHtml(s) {{
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}}

function abbrevBldName(proj, fullName) {{
  // 优先匹配「自编号7、8栋 / 自编号A1# / 自编号14栋」等备案号（兼容 N、M 枚举）
  let m = fullName.match(/自编号\s*([A-Z0-9]+(?:[、,][A-Z0-9]+)*[栋号楼#]?)/);
  if (m) return `${{proj}}-${{m[1].replace(/#$/,'').replace(/、$/,'')}}`;
  // 再匹配普通「2栋 / 3号楼」
  m = fullName.match(/(\d+[栋号楼])/);
  if (m) return `${{proj}}-${{m[1]}}`;
  // 兜底：保持原名
  return fullName;
}}

// ===================================================================
// 主体表格渲染
// ===================================================================
function render() {{
  const date = dateSel.value;
  curDateSpan.textContent = date;
  const rec = ARCHIVE.records[date] || {{}};
  tables.innerHTML = '';
  Array.from(cards.children).forEach(c => c.classList.remove('active'));
  ARCHIVE.projects.forEach(proj => {{
    const p = rec[proj] || {{ buildings: [], summary: {{ total: 0, signed: 0, remaining: 0, rate: 0, count: 0 }} }};
    const s = p.summary;
    const note = {json.dumps(mapping_notes, ensure_ascii=False)};
    let rows = p.buildings.map(b => `
      <tr>
        <td class="name"><span class="bld-link" onclick="openSalesControl('${{escHtml(proj)}}', '${{escHtml(b.name).replace(/'/g, "\\'")}}')" title="${{escHtml(b.name)}}">${{escHtml(abbrevBldName(proj, b.name))}}</span></td>
        <td>${{escHtml(b.presell)}}</td>
        <td class="num">${{fmtNum(b.total)}}</td>
        <td class="num">${{fmtNum(b.signed)}}</td>
        <td class="num">${{fmtNum(b.remaining)}}</td>
        <td>${{fmtRate(b.rate)}}</td>
        <td class="num">${{fmtDelta(b.day_delta)}}</td>
        <td>${{fmtDeltaPct(b.day_pct)}}</td>
        <td class="num">${{fmtDelta(b.week_delta)}}</td>
        <td>${{fmtDeltaPct(b.week_pct)}}</td>
        <td class="num">${{fmtDelta(b.month_delta)}}</td>
        <td>${{fmtDeltaPct(b.month_pct)}}</td>
        <td class="num">${{fmtDelta(b.last_week_delta)}}</td>
        <td class="num">${{fmtDelta(b.last_month_delta)}}</td>
      </tr>
    `).join('');
    rows += `
      <tr class="total">
        <td class="name">合计（${{s.count}} 条官方记录）</td>
        <td>—</td>
        <td class="num">${{fmtNum(s.total)}}</td>
        <td class="num">${{fmtNum(s.signed)}}</td>
        <td class="num">${{fmtNum(s.remaining)}}</td>
        <td>${{fmtRate(s.rate)}}</td>
        <td class="num">${{fmtDelta(s.day_delta)}}</td>
        <td>${{fmtDeltaPct(s.day_pct)}}</td>
        <td class="num">${{fmtDelta(s.week_delta)}}</td>
        <td>${{fmtDeltaPct(s.week_pct)}}</td>
        <td class="num">${{fmtDelta(s.month_delta)}}</td>
        <td>${{fmtDeltaPct(s.month_pct)}}</td>
        <td class="num">${{fmtDelta(s.last_week_delta)}}</td>
        <td class="num">${{fmtDelta(s.last_month_delta)}}</td>
      </tr>
    `;
    const sec = document.createElement('div');
    sec.className = 'section';
    sec.innerHTML = `
      <div class="section-header">
        <h2>${{escHtml(proj)}}</h2>
        <div class="note">${{escHtml(note[proj] || '')}}</div>
        <div class="totals">
          <span>预售总数<b>${{fmtNum(s.total)}}</b></span>
          <span>已网签<b>${{fmtNum(s.signed)}}</b></span>
          <span>剩余<b>${{fmtNum(s.remaining)}}</b></span>
          <span>去化率<b>${{fmtRate(s.rate)}}</b></span>
        </div>
      </div>
      <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>楼栋</th><th>预售证号</th>
            <th>预售总数</th><th>已网签数</th><th>剩余未网签</th><th>去化率</th>
            <th>日新增</th><th>日环比</th>
            <th>本周累计新增</th><th>周环比</th>
            <th>本月累计新增</th><th>月环比</th>
            <th>上周新增网签</th><th>上月新增网签</th>
          </tr>
        </thead>
        <tbody>${{rows}}</tbody>
      </table>
      </div>
    `;
    tables.appendChild(sec);
  }});
}}

// ===================================================================
// 销控表 Modal
// ===================================================================
let currentSubUnits = [];
let currentSubIndex = 0;

// 静态图例：6 种主色（行 1）+ 符号说明（行 2），与阳光家缘官方一致
const LEGEND_ROWS = [
  // 第 1 行：6 种颜色
  [
    {{ cls: 's-presell-off',  label: '已签约/已售' }},
    {{ cls: 's-presell-on',   label: '未签约/可售' }},
    {{ cls: 's-confirm-off',  label: '确权不可售'  }},
    {{ cls: 's-confirm-on',   label: '确权可售'    }},
    {{ cls: 's-transferred',  label: '已过户'      }},
    {{ cls: 's-frozen',       label: '强制冻结'    }},
  ],
  // 第 2 行：符号（次要状态，与阳光家缘官方图例一致）
  [
    {{ sym: '★',  label: '未纳入预售' }},
    {{ sym: '△',  label: '回迁房'      }},
    {{ sym: '□',  label: '自用房'      }},
    {{ sym: '☆',  label: '公建配套'    }},
    {{ sym: '▲',  label: '直管房'      }},
    {{ sym: '■',  label: '分成'        }},
    {{ sym: '◆',  label: '抵押'        }},
    {{ sym: '●',  label: '查封'        }},
    {{ sym: '⊙',  label: '已签约'      }},
    {{ sym: '■',  label: '已备案'      }},
  ],
];

function renderLegend() {{
  const html = LEGEND_ROWS.map(row => `
    <div class="legend-row">${{row.map(it => {{
      const sw = it.cls
        ? `<span class="legend-color ${{it.cls}}"></span>`
        : `<span class="legend-mark">${{it.sym}}</span>`;
      return `<div class="legend-item">${{sw}}<span>${{it.label}}</span></div>`;
    }}).join('')}}</div>
  `).join('');
  salesLegend.innerHTML = `<div class="legend-block">${{html}}</div>`;
}}

function openSalesControl(proj, bldName) {{
  const date = dateSel.value;
  const p    = (ARCHIVE.records[date] || {{}})[proj];
  if (!p) return;
  const b = p.buildings.find(x => x.name === bldName);
  if (!b) return;
  const detail = b.detail || {{}};
  const units  = detail.units || {{}};
  const bids   = Object.keys(units);
  renderLegend();
  if (bids.length === 0) {{
    modalTitle.textContent     = `${{proj}} · ${{bldName}}`;
    modalSubtabs.innerHTML     = '';
    salesTableWrap.innerHTML   = '<div class="no-detail">暂无销控表楼层数据（可能官方接口暂未返回）</div>';
    modalOverlay.classList.add('open');
    return;
  }}
  currentSubUnits = bids.map(bid => ({{ bid, ...units[bid] }}));
  currentSubIndex = 0;
  modalTitle.textContent = `${{proj}} · ${{bldName}}（预售证 ${{b.presell || ''}}）`;
  renderSubtabs();
  renderSalesTable(currentSubUnits[0]);
  modalOverlay.classList.add('open');
}}

function renderSubtabs() {{
  if (currentSubUnits.length <= 1) {{
    modalSubtabs.innerHTML = '';
    return;
  }}
  modalSubtabs.innerHTML = currentSubUnits.map((u, i) => `
    <div class="subtab ${{i === currentSubIndex ? 'active' : ''}}" onclick="switchSubtab(${{i}})">${{escHtml(u.name || u.bid)}}</div>
  `).join('');
}}

window.switchSubtab = function(i) {{
  currentSubIndex = i;
  renderSubtabs();
  renderSalesTable(currentSubUnits[i]);
}};

// 状态判定：颜色 = 是否已网签/已售（红=已签约/已备案，绿=未签约/可售）
//         符号 = 该户的具体附加情况（已签约/已备案/抵押/查封/回迁/自用/公建/直管/分成/未纳入）
// 关键规则：只有真正完成网签/签约/备案/过户的单元才标红；
//          抵押/查封/限制销售/公建配套/回迁/自用等「未签约」状态统一亮绿，符号区分原因。
function decideStatus(r) {{
  let cls = 's-presell-on';
  let label = '未签约/可售';
  // 1. 强制冻结（最高优先级，蓝）
  if (r.closed === 1 && r.preSellStatus === 1 && (r.status === 9 || r.pactStatus === 9)) {{
    cls = 's-frozen'; label = '强制冻结';
  }}
  // 2. 已过户（青绿）
  else if (r.status === 8) {{ cls = 's-transferred'; label = '已过户'; }}
  // 3. 确权不可售（深红）
  else if (r.status === 7) {{ cls = 's-confirm-off'; label = '确权不可售'; }}
  // 4. 确权可售（深绿）
  else if (r.status === 6) {{ cls = 's-confirm-on'; label = '确权可售'; }}
  // 5. 已签约/已网签/已备案 → 红（已售/不可再售）
  //    pactStatus: 5=已签约(网签) | 3=已签约(认购/草签) | 4=已签约
  else if (r.pactStatus === 5 || r.pactStatus === 4 || r.pactStatus === 3 || r.status === 4) {{
    cls = 's-presell-off'; label = '已签约（不可销售）';
  }}
  else if (r.status === 17 || r.filed === 1) {{ cls = 's-presell-off'; label = '已备案（不可销售）'; }}
  // 6. 未签约的其他限制状态 → 亮绿（符号说明具体原因，tooltip 显示详情）
  else if (r.sealed === 1 || r.status === 11) {{ label = '查封（未签约）'; }}
  else if (r.pledgeStatus === 2 || r.status === 10) {{ label = '抵押（未签约）'; }}
  else if (r.backMove === 1 || r.status === 12) {{ label = '回迁房（未签约）'; }}
  else if (r.useself === 1 || r.status === 13) {{ label = '自用房（未签约）'; }}
  else if (r.commonMatch === 1 || r.status === 14) {{ label = '公建配套（未签约）'; }}
  else if (r.directly === 1 || r.status === 15) {{ label = '直管房（未签约）'; }}
  else if (r.divide === 1 || r.status === 16) {{ label = '分成（未签约）'; }}
  else if (r.status === 18) {{ label = '未纳入预售'; }}
  else if (r.status === 5 || r.restricted === 1) {{ label = '限制销售（未签约）'; }}
  else if (r.closed === 1) {{ label = '不可销售（未签约）'; }}
  else {{ label = '预售可售'; }}
  // 符号收集（按优先级）
  const marks = MARK_DEFS.filter(m => {{ try {{ return m.test(r); }} catch(e) {{ return false; }} }})
                          .sort((a, b) => a.order - b.order)
                          .map(m => ({{ sym: m.sym, label: m.label }}));
  return {{ cls, label, marks }};
}}

function renderSalesTable(unit) {{
  const floors = unit.floors || [];
  if (floors.length === 0) {{
    salesTableWrap.innerHTML = '<div class="no-detail">该楼栋暂无销控表数据</div>';
    return;
  }}

  // 按 group 数字倒序（顶层在前）
  const sortedFloors = floors.slice().sort((a, b) => Number(b.group) - Number(a.group));

  // 列数 = 该楼栋「每层户数」（按官方披露的房间位置）。
  // 取「标准层」= 房间数最多的那一层，用它的房号位置（去掉楼层号后的房号部分）作为列。
  // 原因：房号是「楼层号+房号」（如 3901=39层01房、3001=30层01房），不同楼层同一位置编号不同，
  // 如果把所有房号取并集会产生 100+ 列的废海；标准层取法让列数 = 该层户数（几户就有几列）。
  const stripFloor = (r) => {{
    const u = String(r.unitNum), f = String(r.floorNum || '');
    return (f && u.startsWith(f)) ? u.slice(f.length) : u.slice(-2);
  }};
  const stdFloor = sortedFloors.reduce(
    (a, b) => ((b.groupData || []).length > (a.groupData || []).length) ? b : a,
    sortedFloors[0]
  );
  const cols = (stdFloor.groupData || []).map(stripFloor).sort((a, b) => Number(a) - Number(b));
  const colCount = Math.max(cols.length, 1);
  // 渲染：第 1 列为楼层号，其后每列对应一个房号位置（按房间数最多的标准层确定列数）
  let html = `<div class="sales-wrap" style="grid-template-columns: 70px repeat(${{colCount}}, minmax(72px, 1fr));">`;
  sortedFloors.forEach(f => {{
    html += `<div class="floor-cell">${{escHtml(f.group)}}</div>`;
    const map = {{}};
    (f.groupData || []).forEach(r => {{ map[stripFloor(r)] = r; }});
    for (let i = 0; i < cols.length; i++) {{
      const c   = cols[i];
      const r   = map[c];
      if (!r) {{
        html += `<div class="room-cell"></div>`;
        continue;
      }}
      const st = decideStatus(r);
      const area = r.totalArea != null ? `<span class="room-area">${{escHtml(r.totalArea)}}㎡</span>` : '';
      const marks = (st.marks && st.marks.length)
        ? `<span class="room-mark">${{st.marks.map(m => m.sym).join('')}}</span>` : '';
      html += `
        <div class="room-cell ${{st.cls}}" data-info='${{escHtml(JSON.stringify(r))}}'>
          <span class="room-num">${{escHtml(r.unitNum)}}房</span>
          ${{area}}
          ${{marks}}
        </div>
      `;
    }}
  }});
  html += '</div>';
  salesTableWrap.innerHTML = html;

  // Tooltip 绑定
  salesTableWrap.querySelectorAll('.room-cell[data-info]').forEach(cell => {{
    cell.addEventListener('mouseenter', () => {{
      const r = JSON.parse(cell.getAttribute('data-info'));
      const st = decideStatus(r);
      const marksDesc = (st.marks && st.marks.length)
        ? st.marks.map(m => m.sym + ' ' + m.label).join('，') : '—';
      roomTip.innerHTML = `
        <b>${{escHtml(r.unitNum)}}</b>（${{escHtml(r.floorNum || '')}}层）<br/>
        类型：${{escHtml(r.houseFunction || '—')}} ${{escHtml(r.unitType || '')}}<br/>
        建筑面积：${{escHtml(r.totalArea || '—')}}㎡<br/>
        套内面积：${{escHtml(r.inArea || '—')}}㎡<br/>
        状态：${{st.label}}<br/>
        符号：${{marksDesc}}
      `;
      roomTip.style.display = 'block';
    }});
    cell.addEventListener('mousemove', e => {{
      roomTip.style.left = (e.clientX + 12) + 'px';
      roomTip.style.top  = (e.clientY + 12) + 'px';
    }});
    cell.addEventListener('mouseleave', () => {{ roomTip.style.display = 'none'; }});
  }});
}}

window.closeModal = function() {{
  modalOverlay.classList.remove('open');
}};
modalOverlay.addEventListener('click', e => {{ if (e.target === modalOverlay) closeModal(); }});
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeModal(); }});

dateSel.addEventListener('change', render);
render();
</script>
</body>
</html>'''

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[build_site] generated {OUT} ({len(html)} bytes)")


if __name__ == "__main__":
    archive = load_archive()
    data    = compute_comparisons(archive)
    build_html(data)