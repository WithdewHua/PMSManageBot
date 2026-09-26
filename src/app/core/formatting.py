def format_traffic_size(bytes_size: int) -> str:
    """
    格式化流量大小为可读格式
    :param bytes_size: 字节大小
    :return: 格式化后的字符串
    """
    if bytes_size == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(bytes_size)

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    else:
        return f"{size:.2f} {units[unit_index]}"


def get_service_label(service: str) -> tuple[str, str]:
    service_name = service.upper()
    service_emoji = "🎬" if service == "plex" else "📺"
    return service_name, service_emoji
