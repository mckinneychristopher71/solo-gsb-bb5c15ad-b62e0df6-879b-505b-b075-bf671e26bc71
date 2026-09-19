"""三抄本三维全局对齐核校 API。"""
from __future__ import annotations

import unicodedata
from typing import Optional

import numpy as np
import regex
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

app = FastAPI(
    title="三抄本核校 API",
    description="对档案员的三份独立抄录做 NFC 规范化、字素簇切分与三维全局动态规划对齐。",
    version="1.0.0",
)

MAX_GRAPHEMES = 120
# 平局判定顺序：消费来源数（位掩码 popcount）多者优先；同数则位掩码小者优先，
# 即 7(111) > 3(011) > 5(101) > 6(110) > 1(001) > 2(010) > 4(100)。
# DP 平面放置顺序与此一致；掩码 4 因沿 k 轴形成链式松弛而最后处理
# （平局时任何非 4 入口都优先于 mask 4，符合该顺序）。
MASK_ORDER: tuple[int, ...] = (7, 3, 5, 6, 1, 2, 4)
REPLACEMENT = "�"


class ReconcileRequest(BaseModel):
    texts: list[str] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="恰好三段待核校文本（顺序对应来源 A/B/C）。",
    )
    model_config = {
        "json_schema_extra": {
            "examples": [{"texts": ["古籍抄本甲", "古籍抄本乙", "古籍钞本甲"]}]
        }
    }

    @field_validator("texts")
    @classmethod
    def _validate_items(cls, v: list[str]) -> list[str]:
        for t in v:
            if not isinstance(t, str):
                raise ValueError("texts 必须全部为字符串")
        return v


class SourceGrapheme(BaseModel):
    char: Optional[str] = Field(
        ..., description="该来源在本列的字素；来源被跳过（空位）时为 null"
    )
    pos: Optional[int] = Field(
        ..., description="该字素在 NFC 规范化后原文本中的 0 基位置；空位时为 null"
    )


class AlignColumn(BaseModel):
    mask: int = Field(..., description="本列消费的来源位掩码（A=1, B=2, C=4）")
    consensus: str = Field(..., description="共识字素；无共识时为 U+FFFD（�）")
    conflict: bool = Field(..., description="是否未达成至少两份相同非空字素的共识")
    cost: int = Field(..., description="本列对齐成本")
    sources: list[SourceGrapheme] = Field(
        ..., min_length=3, max_length=3, description="来源 A/B/C 在本列的字素与原位置"
    )


class ReconcileResponse(BaseModel):
    total_cost: int
    columns: list[AlignColumn]
    normalized_lengths: list[int] = Field(
        ..., min_length=3, max_length=3, description="三段文本 NFC 规范化后的字素簇数"
    )


_GRAPHEME_RE = regex.compile(r"\X")


def _normalize_and_split(text: str) -> list[str]:
    """NFC 规范化后切分为 Unicode 字素簇（grapheme clusters）。"""
    return _GRAPHEME_RE.findall(unicodedata.normalize("NFC", text))


def _column_cost(a: object, b: object, c: object) -> int:
    """列内三对位置逐对计分（sum-of-pairs）。

    字符对字符：不等计 1、相等计 0；
    字符与空位配对：每对计 1；
    空位与空位配对：计 0。
    """
    vals = (a, b, c)
    present = [x is not None for x in vals]
    n = present.count(True)
    if n == 3:
        return int(a != b) + int(a != c) + int(b != c)
    if n == 2:
        chars = [x for x in vals if x is not None]
        return int(chars[0] != chars[1]) + 2  # 字符对 + 两个字符-空位对
    if n == 1:
        return 2  # 字素与两个空位各配一对
    return 0  # 合法列不会为空（每列至少消费一个来源）


def align_three(seq: list[list[str]]) -> tuple[list[tuple[int, int, int, int]], int]:
    """三维全局 DP 对齐。

    状态 (i, j, k)：三段前缀已消费的字素数。每列用非空位掩码 m ∈ 1..7
    同时推进对应来源，成本由该列被消费字素决定：
      - 两两比较：字符不等 1，字符对空位 1，空位对空位 0。
    平局（同成本路径）依次偏好：列内消费来源数更多、位掩码更小。
    实现为逐 i-平面（J×K）向量化；掩码 4（仅推进 k）形成沿 k 轴的
    常代价链，用 cumulative-minimum 一次性松弛。

    返回 (列序列, 总成本)；列序列元素为 (mask, i, j, k)，其中 i/j/k
    为该列消费字素在各来源中的 0 基位置（被跳过的来源为 -1）。
    """
    a, b, c = seq
    na, nb, nc = len(a), len(b), len(c)

    # 字素不等矩阵（object 数组直接比较字符串）
    ab = np.array(a, dtype=object).reshape(na, 1) != np.array(b, dtype=object)
    ac = np.array(a, dtype=object).reshape(na, 1) != np.array(c, dtype=object)
    bc = np.array(b, dtype=object).reshape(nb, 1) != np.array(c, dtype=object)

    J, K = nb + 1, nc + 1
    INF = 10**9
    # choice[i, j, k]：到达 (i,j,k) 的最后一列掩码；0 表示起点或不可达
    choice = np.zeros((na + 1, J, K), dtype=np.uint8)
    k_axis = np.arange(nc, dtype=np.int64)  # mask 4 链闭式解用
    # 上一个 i-平面的成本
    prev = np.full((J, K), INF, dtype=np.int64)
    prev[0, 0] = 0
    choice[0, 0, 0] = 0

    for i in range(na + 1):
        cur = np.full((J, K), INF, dtype=np.int64)

        # ---- 入边：来自前一个 i-平面（新列消费 A，掩码含位 0），整平面放置 ----
        if i > 0:
            ia = i - 1
            # mask 7：消费 (A_i, B_{j-1}, C_{k-1})
            if nb >= 1 and nc >= 1:
                add = (
                    ab[ia, :nb].reshape(nb, 1).astype(np.int64)
                    + ac[ia, :nc].reshape(1, nc).astype(np.int64)
                    + bc[:nb, :nc].astype(np.int64)
                )
                cand = prev[:-1, :-1] + add
                better = cand < cur[1:, 1:]
                cur[1:, 1:] = np.where(better, cand, cur[1:, 1:])
                choice[i, 1:, 1:][better] = 7

            # mask 3：消费 (A_i, B_{j-1}, C 空位)：字符对 + 两个字符-空位对
            if nb >= 1:
                cand = prev[:-1, :] + ab[ia, :nb].reshape(nb, 1).astype(np.int64) + 2
                better = cand < cur[1:, :]
                cur[1:, :] = np.where(better, cand, cur[1:, :])
                choice[i, 1:, :][better] = 3

            # mask 5：消费 (A_i, B 空位, C_{k-1})
            if nc >= 1:
                cand = prev[:, :-1] + ac[ia, :nc].reshape(1, nc).astype(np.int64) + 2
                better = cand < cur[:, 1:]
                cur[:, 1:] = np.where(better, cand, cur[:, 1:])
                choice[i, :, 1:][better] = 5

            # mask 1：仅消费 A_i（B/C 空位）=> 2
            cand = prev + 2
            better = cand < cur
            cur = np.where(better, cand, cur)
            choice[i][better] = 1
        elif i == 0:
            cur[0, 0] = 0  # 起点

        # ---- 平面内二维松弛（掩码不含 A：6、2、4）----
        # 依赖顺序（关键）：
        #   * mask 6 (B,C) 前驱 (j-1,k-1) 与 mask 2 (仅 B) 前驱 (j-1,k)
        #     都取上一行的 finalized 值——该值可由上一行 mask 4 链到达，
        #     链中消费的 C 位置严格小于 k，顺序合法。
        #   * mask 4 (仅 C) 只能沿【同一行】从更小的 k 转移；它不得作为
        #     mask 2/6 前驱行内、在目标 k 之后再沿 k 前进的步骤。
        # 故先在 pre4 上按行放置 6/2（只引用上一行 finalized 值），
        # 再对每行独立做 mask 4 的沿轴链式松弛，得到该行 finalized 值。
        pre4 = cur.copy()  # mask 4 松弛前的平面（6/2 及 i-入边值）

        def take_row(
            base: np.ndarray, mask: int, j: int, cand: np.ndarray, rk: slice
        ) -> None:
            """行 j 内严格小于时替换（候选按 MASK_ORDER 处理，平局不覆盖）。"""
            better = cand < base[j, rk]
            if better.any():
                base[j, rk] = np.where(better, cand, base[j, rk])
                choice[i, j, rk][better] = mask

        for j in range(J):
            if j >= 1:
                # mask 6：消费 (B_{j-1}, C_{k-1})，来自上一 finalized 行；
                # 字符对 + 两个字符-空位对
                if nc >= 1:
                    cand = cur[j - 1, :-1] + bc[j - 1, :nc].astype(np.int64) + 2
                    take_row(pre4, 6, j, cand, slice(1, K))
                # mask 2：仅消费 B_{j-1}（A/C 空位）=> 两个字符-空位对，步长 2；
                # 前驱 (j-1,k) 取上一行 finalized 值；其上最后一列若为 mask 4
                # 链，链中消费的 C 位置均 < k，顺序合法。
                cand = cur[j - 1, :] + 2
                take_row(pre4, 2, j, cand, slice(0, K))

            # mask 4：仅消费 C（A/B 空位），沿 k 的常代价 2 链。
            # 目标 k（>=1）取 min_{0<=r<k} pre4[j,r] + 2(k-r)
            #                 = 2k + min_{r<k}(pre4[j,r] - 2r)。
            # pre4 不含本行任何 mask4 步骤，链上每步即一个 mask4 列；
            # 平局时入口（非 4 掩码）优先于链。
            if nc >= 1:
                entrance = pre4[j, :nc]
                running = np.minimum.accumulate(entrance - 2 * k_axis) + 2 * k_axis + 2
                take_row(pre4, 4, j, running, slice(1, K))
            cur[j, :] = pre4[j, :]

        prev = cur

    total = int(prev[nb, nc])

    # 回溯
    columns: list[tuple[int, int, int, int]] = []
    i, j, k = na, nb, nc
    while i > 0 or j > 0 or k > 0:
        m = int(choice[i, j, k])
        if m == 0:
            raise RuntimeError("对齐回溯遇到不可达状态")
        pi = i - (1 if m & 1 else 0)
        pj = j - (1 if m & 2 else 0)
        pk = k - (1 if m & 4 else 0)
        columns.append((m, pi if m & 1 else -1, pj if m & 2 else -1, pk if m & 4 else -1))
        i, j, k = pi, pj, pk
    columns.reverse()
    return columns, total


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/reconcile", response_model=ReconcileResponse)
def reconcile(req: ReconcileRequest) -> ReconcileResponse:
    seqs = [_normalize_and_split(t) for t in req.texts]
    for idx, s in enumerate(seqs):
        if len(s) > MAX_GRAPHEMES:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"第 {idx + 1} 段文本有 {len(s)} 个字素簇，"
                    f"超过上限 {MAX_GRAPHEMES}"
                ),
            )

    path, total_cost = align_three(seqs)

    out_cols: list[AlignColumn] = []
    recomputed = 0
    for m, ia, ib, ic in path:
        vals = (
            seqs[0][ia] if ia >= 0 else None,
            seqs[1][ib] if ib >= 0 else None,
            seqs[2][ic] if ic >= 0 else None,
        )
        cost = _column_cost(*vals)
        recomputed += cost
        non_null = [v for v in vals if v is not None]
        # 至少两份相同非空字素 -> 共识
        consensus = REPLACEMENT
        for v in non_null:
            if non_null.count(v) >= 2:
                consensus = v
                break
        conflict = consensus == REPLACEMENT
        out_cols.append(
            AlignColumn(
                mask=m,
                consensus=consensus,
                conflict=conflict,
                cost=cost,
                sources=[
                    SourceGrapheme(char=vals[0], pos=ia),
                    SourceGrapheme(char=vals[1], pos=ib),
                    SourceGrapheme(char=vals[2], pos=ic),
                ],
            )
        )

    assert recomputed == total_cost, f"成本不一致: 列和 {recomputed} != DP {total_cost}"
    return ReconcileResponse(
        total_cost=total_cost,
        columns=out_cols,
        normalized_lengths=[len(s) for s in seqs],
    )
