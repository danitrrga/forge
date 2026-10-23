"""The events the shop emits. Each one sends the customer one email (shop/emails/)."""
from dataclasses import dataclass
from datetime import date


@dataclass
class Order:
    id: str
    customer_name: str
    email: str
    total_cents: int


@dataclass
class Shipment:
    """Created by the warehouse when the parcel is handed to the carrier."""
    carrier: str
    tracking_number: str


@dataclass
class OrderPlaced:
    order: Order


@dataclass
class PaymentFailed:
    order: Order
    reason: str


@dataclass
class OrderShipped:
    order: Order
    shipment: Shipment


@dataclass
class OrderDelivered:
    order: Order
    shipment: Shipment
    delivered_on: date
