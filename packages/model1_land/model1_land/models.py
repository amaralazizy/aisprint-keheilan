from datetime import date, datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Relationship


class Parcel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    governorate: str
    area_feddan: float
    price_egp: float
    road_access: int = Field(ge=1, le=10)
    price_trend_pct: float = 0.0
    lease_price_egp_per_season: float = 0.0  # set by company

    # AI outputs (cached)
    fair_price_egp: Optional[float] = None
    undervaluation_pct: Optional[float] = None
    undervaluation_confidence: Optional[float] = None
    undervaluation_reasoning: Optional[str] = None

    risk_tier: str = "Medium"
    risk_score: Optional[float] = None
    risk_reasoning: Optional[str] = None
    risk_factors_json: Optional[str] = None

    available_for_lease: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

    leases: list["LeaseRecord"] = Relationship(back_populates="parcel")
    shares: list["Share"] = Relationship(back_populates="parcel")
    payouts: list["Payout"] = Relationship(back_populates="parcel")


class LeaseRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    parcel_id: int = Field(foreign_key="parcel.id")
    farmer_name: str
    season: str
    rent_egp: float
    start_date: date
    end_date: date
    parcel: Optional[Parcel] = Relationship(back_populates="leases")
    payouts: list["Payout"] = Relationship(back_populates="lease")


class Investor(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: Optional[str] = None
    budget_egp: float = 0.0
    horizon_years: int = 3
    risk_appetite: str = "Medium"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    shares: list["Share"] = Relationship(back_populates="investor")
    payouts: list["Payout"] = Relationship(back_populates="investor")


class Share(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    parcel_id: int = Field(foreign_key="parcel.id")
    investor_id: int = Field(foreign_key="investor.id")
    share_count: int = Field(gt=0)
    price_per_share_egp: float
    created_at: datetime = Field(default_factory=datetime.utcnow)

    parcel: Optional[Parcel] = Relationship(back_populates="shares")
    investor: Optional[Investor] = Relationship(back_populates="shares")


class Payout(SQLModel, table=True):
    """Snapshot of rent distribution for one investor on one lease."""
    id: Optional[int] = Field(default=None, primary_key=True)
    lease_id: int = Field(foreign_key="leaserecord.id")
    parcel_id: int = Field(foreign_key="parcel.id")
    investor_id: int = Field(foreign_key="investor.id")
    share_count: int
    share_pct: float
    amount_egp: float
    created_at: datetime = Field(default_factory=datetime.utcnow)

    lease: Optional[LeaseRecord] = Relationship(back_populates="payouts")
    parcel: Optional[Parcel] = Relationship(back_populates="payouts")
    investor: Optional[Investor] = Relationship(back_populates="payouts")


class CropAdvice(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    parcel_id: int = Field(foreign_key="parcel.id")
    target_crop: str
    recommendation_text: str
    narrative: str
    raw_input_json: str
    overall_confidence_pct: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
