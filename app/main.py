"""抄本核对 API:对三份独立抄录做三维全局对齐并生成共识文本。"""
from __future__ import annotations

import unicodedata

import grapheme
from fastapi import FastAPI, HTTPException

from .reconcile import reconcile
from .schemas import ReconcileRequest, ReconcileResponse

MAX_GRAPHEMES = 120

app = FastAPI(
    title="抄本核对 API",
    version="1.0.0",
    description="接收三段抄录文本,NFC 规范化后做三维全局动态规划对齐,输出共识文本、对齐列与总成本。",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/reconcile", response_model=ReconcileResponse)
def post_reconcile(req: ReconcileRequest) -> dict:
    seqs: list[list[str]] = []
    for idx, raw in enumerate(req.texts):
        normalized = unicodedata.normalize("NFC", raw)
        clusters = list(grapheme.graphemes(normalized))
        if len(clusters) > MAX_GRAPHEMES:
            raise HTTPException(
                status_code=422,
                detail=f"texts[{idx}] 超过 {MAX_GRAPHEMES} 个字素簇(当前 {len(clusters)} 个)",
            )
        seqs.append(clusters)
    return reconcile(*seqs)
