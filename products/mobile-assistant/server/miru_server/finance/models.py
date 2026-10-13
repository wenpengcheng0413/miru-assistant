from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models import Base


class FinanceSource(Base):
    __tablename__ = "finance_sources"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    token_hash: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_id: Mapped[str] = mapped_column(Text, default="")
    synced_at: Mapped[str] = mapped_column(Text, default="")


class FinancePairing(Base):
    __tablename__ = "finance_pairings"
    code_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    expires_at: Mapped[int] = mapped_column(Integer)


class FinanceReconciliation(Base):
    __tablename__ = "finance_reconciliations"
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class FinanceSnapshot(Base):
    __tablename__ = "finance_snapshots"
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    digest: Mapped[str] = mapped_column(Text)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)
