def get_coin_balance(transactions):
    balance = 0
    for transaction in transactions:
        if transaction.type == "buy":
            balance += transaction.amount
        elif transaction.type == "sell":
            balance -= transaction.amount
    return balance
