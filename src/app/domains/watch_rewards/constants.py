# 幽灵会话扫描窗口（天）。Tautulli 的 get_history 按 stopped 过滤，而幽灵会话
# 落库时 stopped 即落库时刻，因此只要落库后 3 天内扫过一次就必定命中，
# 无需为「started 很早」的记录扩大窗口。留 3 天是为了容忍某轮任务失败。
GHOST_SCAN_DAYS = 3

# 积分结算水位线：记录已经完成结算的最后一个日期（YYYY-MM-DD）。
# 幽灵会话的补偿判定必须依赖它而非当前时刻——清理任务既会在结算前被调用，
# 也会作为独立定时任务在白天运行，只有水位线能稳定回答「这天结算过没有」。
GHOST_SETTLEMENT_CONFIG_TYPE = "ghost_session"

GHOST_SETTLEMENT_CONFIG_KEY = "settled_through_date"
