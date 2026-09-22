"""Evaluate snapshots supplied by a future chain-specific adapter."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping


def amount(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a finite non-negative number") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field} must be a finite non-negative number")
    return result


@dataclass(frozen=True)
class Position:
    position_id: str
    contributed_usd: Decimal
    principal_value_usd: Decimal
    unclaimed_fees_usd: Decimal
    withdrawn_usd: Decimal
    estimated_exit_cost_usd: Decimal

    @classmethod
    def from_dict(cls, data: Mapping) -> "Position":
        position_id = data["position_id"]
        if not isinstance(position_id, str) or not position_id.strip():
            raise ValueError("position_id must be a non-empty string")
        fields = (
            "contributed_usd", "principal_value_usd", "unclaimed_fees_usd",
            "withdrawn_usd", "estimated_exit_cost_usd",
        )
        values = {field: amount(data[field], field) for field in fields}
        if values["contributed_usd"] == 0:
            raise ValueError("contributed_usd must be greater than zero")
        return cls(position_id=position_id, **values)


def evaluate(position: Position, target_percent: Decimal) -> dict:
    target_percent = amount(target_percent, "target_percent")
    # Principal excludes fees. Historical withdrawals include already collected fees.
    net_profit = (
        position.principal_value_usd + position.unclaimed_fees_usd
        + position.withdrawn_usd - position.contributed_usd
        - position.estimated_exit_cost_usd
    )
    return_percent = net_profit / position.contributed_usd * 100
    return {
        "position_id": position.position_id,
        "net_profit_usd": str(net_profit),
        "return_percent": str(return_percent),
        "target_percent": str(target_percent),
        "decision": "TARGET_REACHED" if return_percent >= target_percent else "HOLD",
        "mode": "simulation",
        "transaction_submitted": False,
    }
