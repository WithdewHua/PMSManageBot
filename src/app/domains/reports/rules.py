from datetime import timedelta


def hex_to_int(value):
    """Convert hex value to integer"""
    try:
        return int(value, 16)
    except (ValueError, TypeError):
        return 0


def sizeof_fmt(num, suffix="B"):
    # Function found https://stackoverflow.com/a/1094933
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"


def date_split(to_split):
    split_year = int(to_split.split("-")[0])
    split_month = int(to_split.split("-")[1])
    split_day = int(to_split.split("-")[2])
    return [split_year, split_month, split_day]


def add_to_dictval(d, key, val):
    if key not in d:
        d[key] = val
    else:
        d[key] += val


def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + timedelta(n)
