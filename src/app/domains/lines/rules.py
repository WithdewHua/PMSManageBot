from app.core.config import settings


def normalize_line_domain(line_domain: str) -> str:
    """
    将线路域名规范化为纯主机名（host 或 host:port），去除协议前缀和路径后缀。

    数据库 line_traffic_stats/line_traffic_monthly_stats 中的 line 字段存储的是
    不含协议、不含路径的主机名（例如 example.com:8096），而 CustomLine.domain
    用户提交时可能包含协议前缀（https://）或路径后缀，需要统一处理后才能匹配。

    示例：
        "https://example.com:8096"      -> "example.com:8096"
        "https://example.com:8096/path" -> "example.com:8096"
        "example.com:8096/path"         -> "example.com:8096"
        "example.com:8096"              -> "example.com:8096"
        "example.com"                   -> "example.com"

    Args:
        line_domain: 原始线路域名

    Returns:
        规范化后的纯主机名
    """
    from urllib.parse import urlparse

    domain = line_domain.strip()
    # 如果不含协议前缀，urlparse 无法正确解析 netloc，需手动补充
    if "://" not in domain:
        domain = "dummy://" + domain
    parsed = urlparse(domain)
    # netloc 即为 host(:port)，若解析失败则回退到去除路径的原始值
    netloc = parsed.netloc or domain.split("/")[0].replace("dummy://", "")
    return netloc


def is_binded_premium_line(line: str) -> bool:
    """检查绑定线路是否为高级线路

    通用函数，适用于 Plex 和 Emby

    Args:
        line: 线路名称

    Returns:
        bool: 是否为高级线路
    """
    for premium_line in settings.PREMIUM_STREAM_BACKEND:
        if premium_line in line:
            return True
    return False
