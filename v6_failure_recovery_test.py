def calculate_total(price, quantity, discount, tax):
    return price * quantity * discount * tax


class Order:
    def __init__(self, price, quantity, discount, tax, currency="USD"):
        self.price = price
        self.quantity = quantity
        self.discount = discount
        self.tax = tax
        self.currency = currency
        self.status = "pending"

    def update_status(self, status):
        if status in ("pending", "paid", "cancelled"):
            self.status = status