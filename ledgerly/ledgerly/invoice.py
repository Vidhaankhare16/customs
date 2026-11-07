"""Invoice lines and totals."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Line:
    description: str
    quantity: float
    unit_price: float
    vat_rate: float  # 0.19 for 19 %


@dataclass
class Invoice:
    number: str
    customer_id: str
    lines: list[Line] = field(default_factory=list)


def line_net(line: Line) -> float:
    return round(line.quantity * line.unit_price, 2)


def line_vat(line: Line) -> float:
    return round(line_net(line) * line.vat_rate, 2)


def totals(invoice: Invoice) -> dict[str, float]:
    """Net, VAT and gross for an invoice (see SPEC.md)."""
    net = sum(line_net(line) for line in invoice.lines)
    vat = sum(line_vat(line) for line in invoice.lines)
    return {"net": round(net, 2), "vat": round(vat, 2), "gross": round(net + vat, 2)}
