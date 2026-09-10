class Order:
    def __init__(self, price, quantity, discount, tax, currency="USD"):
        self.price = price
        self.quantity = quantity
        self.discount = discount
        self.tax = tax
        self.currency = currency
        self.status = "pending"

    def update_status(self, status):
        if status in ["pending", "paid", "cancelled"]:
            self.status = status


def summarize_paid_orders(orders):
    total = 0
    for order in orders:
        if order.status == "paid":
            total += order.price * order.quantity * order.discount * order.tax
    return total


def find_orders_by_status(orders, status):
    return [order for order in orders if order.status == status]


def count_orders(orders):
    return len(orders)


def calculate_total(price, quantity, discount, tax):
    return price * quantity * discount * tax