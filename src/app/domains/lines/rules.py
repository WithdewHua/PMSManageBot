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


def is_binded_premium_line(
    line: str | None, premium_lines: tuple[str, ...] | list[str]
) -> bool:
    """Return whether a bound line belongs to the supplied premium catalog."""
    if not line:
        return False
    return any(premium_line in line for premium_line in premium_lines)


def match_catalog_line(line: str, catalog_lines: tuple[str, ...] | list[str]) -> bool:
    """Categorize line using historical substring match: line.lower() in cat_line.lower()."""
    line_lower = line.lower()
    return any(line_lower in cat_line.lower() for cat_line in catalog_lines)
