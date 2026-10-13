from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

Id = Annotated[str, Field(min_length=1, max_length=128)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Entity(StrictModel):
    id: Id
    name: str = Field(max_length=500)
    raw: dict[str, JsonValue] = Field(default_factory=dict)


class Wallet(Entity):
    currency: str = Field(pattern=r"^(?:[A-Z]{3}|UNKNOWN)$")
    decimals: int = Field(ge=0, le=8)


class Entry(StrictModel):
    id: Id
    title: str = Field(max_length=500)
    note: str = Field(default="", max_length=2000)
    amount: str = Field(max_length=40, pattern=r"^-?[0-9]{1,13}(?:\.[0-9]{1,8})?$")
    occurred_at: datetime
    local_date: date
    income: bool
    paid: bool
    skipped: bool
    kind: Literal["upcoming", "subscription", "repetitive", "credit", "debt"] | None = None
    wallet_id: Id
    category_id: Id
    subcategory_id: Id | None = None
    paired_id: Id | None = None
    raw: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("amount")
    @classmethod
    def valid_amount(cls, value):
        try:
            amount = Decimal(value)
        except InvalidOperation:
            raise ValueError("invalid amount") from None
        if not amount.is_finite() or abs(amount) > Decimal("1000000000000"):
            raise ValueError("amount out of range")
        if amount.as_tuple().exponent < -8:
            raise ValueError("amount precision exceeds 8 decimals")
        return format(amount, "f")

    @field_validator("occurred_at")
    @classmethod
    def aware_date(cls, value):
        if value.tzinfo is None:
            raise ValueError("timezone required")
        return value


class Snapshot(StrictModel):
    protocol: Literal[1]
    schema_version: Literal[46]
    snapshot_id: Id
    base_revision: int = Field(ge=0)
    app_version: str = Field(min_length=1, max_length=100)
    generated_at: datetime
    timezone: Literal["Asia/Shanghai"]
    restored_backup: bool = False
    wallets: list[Wallet] = Field(max_length=10000)
    categories: list[Entity] = Field(max_length=10000)
    budgets: list[Entity] = Field(max_length=10000)
    objectives: list[Entity] = Field(max_length=10000)
    transactions: list[Entry] = Field(max_length=100000)

    @model_validator(mode="after")
    def references(self):
        for group in (self.wallets, self.categories, self.budgets, self.objectives, self.transactions):
            if len({x.id for x in group}) != len(group):
                raise ValueError("duplicate source id")
        wallets = {w.id: w for w in self.wallets}
        categories = {c.id for c in self.categories}
        for entry in self.transactions:
            if entry.wallet_id not in wallets or entry.category_id not in categories:
                raise ValueError("missing wallet or category")
            if entry.subcategory_id is not None and entry.subcategory_id not in categories:
                raise ValueError("missing subcategory")
            if Decimal(entry.amount) != Decimal(entry.amount).quantize(
                Decimal(1).scaleb(-wallets[entry.wallet_id].decimals)
            ):
                raise ValueError("amount exceeds wallet precision")
            if entry.local_date != entry.occurred_at.date():
                raise ValueError("local date mismatch")
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at timezone required")
        return self
