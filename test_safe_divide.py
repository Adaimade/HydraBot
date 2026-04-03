import safe_divide
try:
    print(safe_divide.safe_divide(10, 2))
except ValueError as e:
    print(f'捕獲異常: {e}')