#!/usr/bin/env python3
"""Tautulli 幽灵会话探针 —— 只读，不删除也不修改任何数据。

在动手清理之前用它确认三件事：

  1. 当前 Tautulli 版本的 get_history / get_metadata 究竟返回哪些字段、单位是否符合预期
  2. 库里到底有多少条幽灵记录、分布如何
  3. 判定规则与补偿公式跑出来的结果是否合理

用法：
    PYTHONPATH=src python3 scripts/probe_tautulli_ghost_sessions.py [天数] [粗筛阈值(小时)]

默认扫描最近 30 天，粗筛阈值取模块默认值。
"""

import sys
from collections import defaultdict
from datetime import datetime, timedelta

from app.modules.tautulli import Tautulli
from app.utils.tautulli_history import (
    COARSE_FILTER_SECONDS,
    GHOST_DURATION_RATIO,
    GHOST_DURATION_SLACK,
    STATUS_GHOST,
    STATUS_UNDETERMINED,
    MediaDurationResolver,
    clamp_percent,
    get_row_play_seconds,
    is_active_session,
    judge_row,
)

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
COARSE_SECONDS = (
    int(float(sys.argv[2]) * 3600) if len(sys.argv) > 2 else COARSE_FILTER_SECONDS
)

# 单位自检的取样条数，以及取样记录需满足的最小播放时长
CALIBRATION_SAMPLE = 5
CALIBRATION_MIN_SECONDS = 600

# 播放时长分布的分桶边界（秒），用于评估粗筛阈值定在哪里合适
HISTOGRAM_BUCKETS = [
    (0, 1800),
    (1800, 3600),
    (3600, 5400),
    (5400, 7200),
    (7200, 10800),
    (10800, 14400),
    (14400, 21600),
    (21600, 43200),
    (43200, None),
]

SEP = "=" * 78


def fmt_hours(seconds) -> str:
    return f"{(seconds or 0) / 3600:.2f}h"


def fmt_ts(ts) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")


def main() -> None:
    tautulli = Tautulli()
    after = (datetime.now() - timedelta(days=DAYS)).strftime("%Y-%m-%d")

    print(SEP)
    print("Tautulli 幽灵会话探针（只读）")
    print(SEP)
    print(f"扫描区间   : {after} 起最近 {DAYS} 天")
    print(f"粗筛阈值   : {fmt_hours(COARSE_SECONDS)}（超过才去查媒体元数据）")
    print(
        f"判定规则   : 播放时长 > 媒体时长 * {GHOST_DURATION_RATIO} + {GHOST_DURATION_SLACK}s"
    )
    print("补偿公式   : 媒体时长 * percent_complete / 100")
    print()

    resolver = MediaDurationResolver(tautulli)
    first_row = None
    suspect_rows = []
    calibration_rows = []
    histogram = defaultdict(int)
    total = 0
    skipped_active = 0

    for row in tautulli.iter_history(grouping=0, include_activity=0, after=after):
        # 正在播放的活动会话没有 row_id、时长还在增长，既不能判定也不能删除
        if is_active_session(row):
            skipped_active += 1
            continue

        total += 1
        if first_row is None:
            first_row = row

        play_seconds = get_row_play_seconds(row)
        for low, high in HISTOGRAM_BUCKETS:
            if play_seconds >= low and (high is None or play_seconds < high):
                histogram[(low, high)] += 1
                break

        if play_seconds >= COARSE_SECONDS:
            suspect_rows.append(row)
        elif (
            len(calibration_rows) < CALIBRATION_SAMPLE
            and play_seconds >= CALIBRATION_MIN_SECONDS
            and 30 <= clamp_percent(row.get("percent_complete")) <= 100
            and not int(row.get("live") or 0)
        ):
            calibration_rows.append(row)

    if not total:
        print("未取到任何 history 记录，请检查 TAUTULLI_URL / TAUTULLI_APIKEY 配置。")
        return

    # ------------------------------------------------------------------
    print(SEP)
    print(
        "① 字段清单（判定依赖 row_id / user_id / percent_complete / live / rating_key）"
    )
    print(SEP)
    for key in sorted(first_row.keys()):
        print(f"  {key:<28} = {first_row[key]!r}")
    print()

    for required in ("row_id", "user_id", "percent_complete", "live", "rating_key"):
        if required not in first_row:
            print(f"  [!] 缺少字段 {required}，判定逻辑需要调整")
    print()

    # ------------------------------------------------------------------
    print(SEP)
    print("② 媒体时长单位自检")
    print(SEP)
    print(
        "拿正常记录比对：get_metadata 给出的媒体时长 vs「播放时长 / 播放进度」的推算值。"
    )
    print("关注的是量级：单位若不是毫秒，偏差会是 1000x 级别，判定将大面积误判，")
    print("必须先修正 MediaDurationResolver 再继续。")
    print("零点几倍的偏差属正常——用户从中间续播或跳转时，进度推进与播放时长本就不等。")
    print()
    if not calibration_rows:
        print("  没有取到合适的样本，无法自检。")
    for row in calibration_rows:
        play_seconds = get_row_play_seconds(row)
        percent = clamp_percent(row.get("percent_complete"))
        implied = play_seconds / (percent / 100)
        actual = resolver.get(row.get("rating_key"))
        if not actual:
            print(f"  {row.get('full_title', '')[:40]:<42} 媒体时长取不到")
            continue
        ratio = implied / actual
        flag = "OK" if 0.05 <= ratio <= 20 else "!! 量级异常，检查单位换算"
        print(
            f"  {str(row.get('full_title', ''))[:40]:<42} "
            f"推算 {fmt_hours(implied):>8} / 实际 {fmt_hours(actual):>8} "
            f"= {ratio:>6.2f}x  {flag}"
        )
    print()

    # ------------------------------------------------------------------
    print(SEP)
    print("③ 播放时长分布（用于评估粗筛阈值）")
    print(SEP)
    print("粗筛阈值以上的记录才会去查媒体元数据。阈值定得越低覆盖越全，")
    print("但细查量（即 get_metadata 调用次数）也越大。累计列 = 该档及以上的条数。\n")
    cumulative = 0
    for low, high in reversed(HISTOGRAM_BUCKETS):
        count = histogram.get((low, high), 0)
        cumulative += count
        label = (
            f">= {low / 3600:.1f}h"
            if high is None
            else f"{low / 3600:.1f}h ~ {high / 3600:.1f}h"
        )
        mark = " <- 当前阈值" if low <= COARSE_SECONDS < (high or float("inf")) else ""
        print(f"  {label:<14} {count:>7} 条   累计 {cumulative:>7} 条{mark}")
    print()

    # ------------------------------------------------------------------
    print(SEP)
    print("④ 可疑记录判定")
    print(SEP)
    print(f"总记录数 {total}，进入细查 {len(suspect_rows)} 条")
    print(f"（已跳过 {skipped_active} 条正在播放的活动会话）\n")

    verdicts = [judge_row(row, resolver) for row in suspect_rows]
    ghosts = [v for v in verdicts if v.status == STATUS_GHOST]
    undetermined = [v for v in verdicts if v.status == STATUS_UNDETERMINED]

    if verdicts:
        print(
            f"  {'row_id':>8}  {'用户':<16} {'标题':<32} "
            f"{'原始':>8} {'媒体':>8} {'进度':>5} {'补偿':>8}  判定"
        )
        print("  " + "-" * 100)
        for v in sorted(verdicts, key=lambda x: x.raw_seconds, reverse=True):
            label = {
                STATUS_GHOST: "幽灵",
                STATUS_UNDETERMINED: "无法判定",
            }.get(v.status, "正常")
            print(
                f"  {str(v.row_id):>8}  {v.friendly_name[:14]:<16} {v.title[:30]:<32} "
                f"{fmt_hours(v.raw_seconds):>8} {fmt_hours(v.media_seconds):>8} "
                f"{v.percent_complete:>4}% {fmt_hours(v.compensated_seconds):>8}  {label}"
            )
        print()
        for v in sorted(ghosts, key=lambda x: x.raw_seconds, reverse=True)[:10]:
            print(
                f"  row_id={v.row_id} {fmt_ts(v.started)} -> {fmt_ts(v.stopped)}  {v.reason}"
            )
        print()

    print(f"  判为幽灵    : {len(ghosts)} 条")
    print(f"  无法判定    : {len(undetermined)} 条（媒体元数据缺失，需人工确认）")
    print()

    # ------------------------------------------------------------------
    print(SEP)
    print("⑤ 按用户汇总影响")
    print(SEP)
    if not ghosts:
        print("  没有检出幽灵记录。")
        return

    per_user = defaultdict(lambda: {"count": 0, "raw": 0, "comp": 0, "name": ""})
    for v in ghosts:
        entry = per_user[v.user_id]
        entry["count"] += 1
        entry["raw"] += v.raw_seconds
        entry["comp"] += v.compensated_seconds
        entry["name"] = v.friendly_name

    print(
        f"  {'user_id':>10}  {'用户':<16} {'条数':>4} "
        f"{'原始时长':>10} {'补偿时长':>10} {'虚增':>10}"
    )
    print("  " + "-" * 70)
    total_inflated = 0
    for user_id, e in sorted(
        per_user.items(), key=lambda kv: kv[1]["raw"] - kv[1]["comp"], reverse=True
    ):
        inflated = e["raw"] - e["comp"]
        total_inflated += inflated
        print(
            f"  {str(user_id):>10}  {e['name'][:14]:<16} {e['count']:>4} "
            f"{fmt_hours(e['raw']):>10} {fmt_hours(e['comp']):>10} {fmt_hours(inflated):>10}"
        )
    print("  " + "-" * 70)
    print(f"  合计虚增 {fmt_hours(total_inflated)}，涉及 {len(per_user)} 个用户")
    print()
    print("以上为只读结果，没有任何数据被修改。确认无误后再执行清理。")


if __name__ == "__main__":
    main()
