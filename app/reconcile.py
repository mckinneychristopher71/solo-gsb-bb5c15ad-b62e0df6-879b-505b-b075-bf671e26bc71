"""三维全局动态规划对齐与共识生成。

三份抄录分别视为序列 A、B、C(均为 NFC 规范化后的字素簇列表)。
每列可消费任意非空来源组合(位掩码 1..7,bit0=A、bit1=B、bit2=C):
  - 字符不等、字符与空位配对:各计 1
  - 空位与空位配对:计 0
目标为总成本最小;平局时依次偏好消费来源数更多、位掩码更小,
即掩码优先级 7 > 3 > 5 > 6 > 1 > 2 > 4。
"""
from __future__ import annotations

import numpy as np

#: 平局时的掩码优先级(消费来源数降序,其次掩码值升序)
MASK_PRIORITY = (7, 3, 5, 6, 1, 2, 4)

#: 共识无法达成时写入的替换字符
REPLACEMENT = "�"

_INF = 1 << 28


def _encode(seq: list[str], vocab: dict[str, int]) -> np.ndarray:
    """把字素簇序列编码为整数数组,便于用 numpy 做相等性比较。"""
    codes = np.empty(len(seq), dtype=np.int32)
    for i, g in enumerate(seq):
        code = vocab.get(g)
        if code is None:
            code = len(vocab)
            vocab[g] = code
        codes[i] = code
    return codes


def align_three(a: list[str], b: list[str], c: list[str]) -> tuple[int, list[tuple[int, list, list]]]:
    """对三段字素簇序列做三维全局对齐。

    返回 (总成本, 列列表);每列为 (mask, [g0, g1, g2], [p0, p1, p2]),
    空位以 None 表示,p* 为字素在对应来源中的原位置(0 起始)。
    """
    n1, n2, n3 = len(a), len(b), len(c)
    vocab: dict[str, int] = {}
    A = _encode(a, vocab)
    B = _encode(b, vocab)
    C = _encode(c, vocab)

    dp = np.full((n1 + 1, n2 + 1, n3 + 1), _INF, dtype=np.int32)
    choice = np.zeros((n1 + 1, n2 + 1, n3 + 1), dtype=np.uint8)
    dp[0, 0, 0] = 0

    # neq_ac[i, k] = 0/1,表示 A[i] 与 C[k] 是否不等
    neq_ac = (A[:, None] != C[None, :]).astype(np.int32)
    neq_bc = (B[:, None] != C[None, :]).astype(np.int32)
    ks = np.arange(n3 + 1, dtype=np.int32)
    two_k = 2 * ks

    priority_rank = {m: r for r, m in enumerate(MASK_PRIORITY)}

    for i in range(n1 + 1):
        for j in range(n2 + 1):
            if i == 0 and j == 0:
                # 只能逐列消费来源 C(掩码 4),每列成本 2
                dp[0, 0, :] = two_k
                choice[0, 0, 1:] = 4
                continue

            # 先处理不依赖本行 k-1 状态的六个掩码(沿 k 向量化)
            best = np.full(n3 + 1, _INF, dtype=np.int32)
            pick = np.zeros(n3 + 1, dtype=np.uint8)
            neq_ab = int(A[i - 1] != B[j - 1]) if i and j else 0

            candidates: list[tuple[int, np.ndarray]] = []
            if i and j:
                if n3:
                    v7 = np.full(n3 + 1, _INF, dtype=np.int32)
                    v7[1:] = dp[i - 1, j - 1, :n3] + neq_ab + neq_ac[i - 1] + neq_bc[j - 1]
                    candidates.append((7, v7))
                candidates.append((3, dp[i - 1, j - 1, :] + 2 + neq_ab))
            if i:
                if n3:
                    v5 = np.full(n3 + 1, _INF, dtype=np.int32)
                    v5[1:] = dp[i - 1, j, :n3] + 2 + neq_ac[i - 1]
                    candidates.append((5, v5))
                candidates.append((1, dp[i - 1, j, :] + 2))
            if j:
                if n3:
                    v6 = np.full(n3 + 1, _INF, dtype=np.int32)
                    v6[1:] = dp[i, j - 1, :n3] + 2 + neq_bc[j - 1]
                    candidates.append((6, v6))
                candidates.append((2, dp[i, j - 1, :] + 2))

            candidates.sort(key=lambda mc: priority_rank[mc[0]])
            for mask, vec in candidates:
                better = vec < best  # 严格更小才更新,平局保留高优先级掩码
                best = np.where(better, vec, best)
                pick = np.where(better, mask, pick)

            # 掩码 4(仅消费 C):dp[k] = min(best[k], dp[k-1] + 2)
            # 即 dp[k] = 2k + min_{t<=k} (best[t] - 2t),用累积最小值向量化
            t = best - two_k
            cumm = np.minimum.accumulate(t)
            dp[i, j, :] = cumm + two_k
            prev = np.empty(n3 + 1, dtype=np.int32)
            prev[0] = _INF
            prev[1:] = cumm[:-1]
            # 平局 t[k] == prev[k] 时优先 best 的掩码(掩码 4 优先级最低)
            choice[i, j, :] = np.where(t <= prev, pick, 4)

    # 回溯复原对齐列
    columns: list[tuple[int, list, list]] = []
    i, j, k = n1, n2, n3
    while i or j or k:
        m = int(choice[i, j, k])
        g = [None, None, None]
        p = [None, None, None]
        if m & 1:
            i -= 1
            g[0], p[0] = a[i], i
        if m & 2:
            j -= 1
            g[1], p[1] = b[j], j
        if m & 4:
            k -= 1
            g[2], p[2] = c[k], k
        columns.append((m, g, p))
    columns.reverse()
    return int(dp[n1, n2, n3]), columns


def column_cost(g: list) -> int:
    """单列成本:字符不等或字符与空位配对各计 1,空位间计 0。"""
    cost = 0
    for x in range(3):
        for y in range(x + 1, 3):
            gx, gy = g[x], g[y]
            if gx is None and gy is None:
                continue
            if gx is None or gy is None or gx != gy:
                cost += 1
    return cost


def reconcile(a: list[str], b: list[str], c: list[str]) -> dict:
    """对齐三段字素簇序列并生成共识结果。"""
    total_cost, columns = align_three(a, b, c)

    out_columns = []
    uncertain = []
    consensus_chars = []
    for idx, (mask, g, p) in enumerate(columns):
        cost = column_cost(g)
        non_empty = [x for x in g if x is not None]
        # 至少两份相同非空字素时达成共识(三个来源下该字素必唯一)
        cons = next((x for x in non_empty if non_empty.count(x) >= 2), None)
        sources = [{"grapheme": g[s], "position": p[s]} for s in range(3)]
        if cons is None:
            cons = REPLACEMENT
            uncertain.append({"column": idx, "sources": sources})
        consensus_chars.append(cons)
        out_columns.append(
            {
                "index": idx,
                "mask": mask,
                "cost": cost,
                "sources": sources,
                "consensus": cons,
            }
        )

    return {
        "consensus": "".join(consensus_chars),
        "total_cost": total_cost,
        "columns": out_columns,
        "uncertain": uncertain,
    }
