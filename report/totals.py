def calculate_total(rows):
    return sum(row.strength for row in rows if row.strength is not None)
