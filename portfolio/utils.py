def get_coin_balance(transactions):
    balance = 0
    for transaction in transactions:
        if transaction.transaction_type == "buy":
            balance += transaction.amount
        elif transaction.transaction_type == "sell":
            balance -= transaction.amount
    return balance
