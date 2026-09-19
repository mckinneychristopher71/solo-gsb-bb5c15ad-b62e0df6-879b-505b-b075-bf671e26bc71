"""请求/响应模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ReconcileRequest(BaseModel):
    """恰好三段待核对文本。"""

    texts: list[str] = Field(..., description="恰好三段文本,每段不超过 120 个字素簇")

    @field_validator("texts")
    @classmethod
    def _exactly_three(cls, v: list[str]) -> list[str]:
        if len(v) != 3:
            raise ValueError("必须恰好提供三段文本(texts 长度须为 3)")
        return v


class SourceCell(BaseModel):
    """某列中一个来源的字素及其原位置;空位均为 null。"""

    grapheme: str | None
    position: int | None


class Column(BaseModel):
    index: int = Field(..., description="列序号(0 起始)")
    mask: int = Field(..., description="本列消费的来源位掩码,bit0/1/2 对应 texts[0/1/2]")
    cost: int = Field(..., description="本列成本")
    sources: list[SourceCell] = Field(..., description="三个来源的字素与原位置")
    consensus: str = Field(..., description="本列共识字素,未达成时为 �")


class UncertainColumn(BaseModel):
    column: int = Field(..., description="未达成共识的列序号")
    sources: list[SourceCell] = Field(..., description="三个来源的字素与原位置")


class ReconcileResponse(BaseModel):
    consensus: str = Field(..., description="共识文本")
    total_cost: int = Field(..., description="对齐总成本")
    columns: list[Column] = Field(..., description="对齐列")
    uncertain: list[UncertainColumn] = Field(..., description="写入 � 的列及各来源字素与原位置")
