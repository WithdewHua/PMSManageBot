"""Pure byte-size formatting with no domain or configuration dependencies."""


def format_bytes(bytes_size: int) -> str:
    """Format a byte count using the legacy binary-unit display contract."""
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
    return f"{size:.2f} {units[unit_index]}"
