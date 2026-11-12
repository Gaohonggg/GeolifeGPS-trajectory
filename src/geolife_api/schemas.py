"""Response của API, khớp components/schemas trong docs/openapi.yaml."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Health(BaseModel):
    status: Literal["ok", "unavailable"]
    model_loaded: bool
    db_connected: bool


class ModelInfo(BaseModel):
    name: str
    version: int


class PlacePrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    hours: float = Field(ge=0)
    days: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)
    regularity: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=1)


class HomeAbstain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abstain_reason: Literal["no_night_stay", "insufficient_nights"]


class OfficeAbstain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abstain_reason: Literal["no_distinct_office", "insufficient_workdays"]


class TimeRange(BaseModel):
    start: str
    end: str


class UserPrediction(BaseModel):
    user_id: int
    n_points: int
    time_range: TimeRange
    model: ModelInfo
    home: PlacePrediction | HomeAbstain
    office: PlacePrediction | OfficeAbstain
