def safe_divide(x, y):
    if y == 0:
        raise ValueError('無法除以零')
    return x / y