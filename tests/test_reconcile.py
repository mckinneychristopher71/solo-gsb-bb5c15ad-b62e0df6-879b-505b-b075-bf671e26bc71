"""核心对齐逻辑与 API 的测试。"""
from __future__ import annotations

import itertools
import random
import unicodedata

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.reconcile import MASK_PRIORITY, align_three, column_cost, reconcile

client = TestClient(app)


# ---------------------------------------------------------------- 参考实现

def _slow_align(a, b, c):
    """纯 Python 三维 DP 参考实现,用于交叉验证。"""
    n1, n2, n3 = len(a), len(b), len(c)
    inf = float("inf")
    dp = {}
    ch = {}

    def col_cost(g):
        cost = 0
        for x, y in ((0, 1), (0, 2), (1, 2)):
            gx, gy = g[x], g[y]
            if gx is None and gy is None:
                continue
            if gx is None or gy is None or gx != gy:
                cost += 1
        return cost

    for i in range(n1 + 1):
        for j in range(n2 + 1):
            for k in range(n3 + 1):
                if i == j == k == 0:
                    dp[(0, 0, 0)] = 0
                    continue
                best, best_mask = inf, None
                for mask in MASK_PRIORITY:
                    di, dj, dk = mask & 1, (mask >> 1) & 1, (mask >> 2) & 1
                    if di > i or dj > j or dk > k:
                        continue
                    g = [
                        a[i - 1] if di else None,
                        b[j - 1] if dj else None,
                        c[k - 1] if dk else None,
                    ]
                    v = dp[(i - di, j - dj, k - dk)] + col_cost(g)
                    if v < best:
                        best, best_mask = v, mask
                dp[(i, j, k)] = best
                ch[(i, j, k)] = best_mask

    columns = []
    i, j, k = n1, n2, n3
    while i or j or k:
        m = ch[(i, j, k)]
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
    return dp[(n1, n2, n3)], columns


# ---------------------------------------------------------------- 基础性质

def test_identical_texts_zero_cost():
    total, columns = align_three(list("档案抄录"), list("档案抄录"), list("档案抄录"))
    assert total == 0
    assert all(m == 7 for m, _, _ in columns)
    assert len(columns) == 4


def test_column_cost_rules():
    assert column_cost(["甲", "甲", "甲"]) == 0
    assert column_cost(["甲", "甲", "乙"]) == 2
    assert column_cost(["甲", "乙", "丙"]) == 3
    assert column_cost(["甲", "甲", None]) == 2
    assert column_cost(["甲", "乙", None]) == 3
    assert column_cost(["甲", None, None]) == 2
    assert column_cost([None, None, None]) == 0


def test_total_cost_matches_column_sum():
    rng = random.Random(7)
    for _ in range(30):
        seqs = [[rng.choice("甲乙丙丁") for _ in range(rng.randint(0, 6))] for _ in range(3)]
        total, columns = align_three(*seqs)
        assert total == sum(column_cost(g) for _, g, _ in columns)


def test_fuzz_against_slow_reference():
    rng = random.Random(42)
    alphabets = ["甲乙", "甲乙丙", "甲乙丙丁戊"]
    for _ in range(120):
        alpha = rng.choice(alphabets)
        seqs = [[rng.choice(alpha) for _ in range(rng.randint(0, 5))] for _ in range(3)]
        fast_total, fast_cols = align_three(*seqs)
        slow_total, slow_cols = _slow_align(*seqs)
        assert fast_total == slow_total, seqs
        assert fast_cols == slow_cols, seqs  # 平局规则一致,列应完全相同


def test_tie_break_prefers_more_sources_then_smaller_mask():
    # 手工验算:dp[1,2,1] 处掩码 7、6、2 同为 4 分,按优先级选 7
    total, columns = align_three(list("甲"), list("甲乙"), list("乙"))
    assert total == 4
    assert [m for m, _, _ in columns] == [2, 7]
    assert columns[1][1] == ["甲", "乙", "乙"]


def test_positions_are_original_indices():
    total, columns = align_three(list("甲X乙"), list("甲乙"), list("甲乙"))
    assert total == 2
    assert [m for m, _, _ in columns] == [7, 1, 7]
    # 第二列只消费来源 0 的 "X"(原位置 1)
    m, g, p = columns[1]
    assert m == 1 and g == ["X", None, None] and p == [1, None, None]
    # 其余列三方对齐,位置各自对应原序列下标
    assert columns[0][1] == ["甲", "甲", "甲"]
    assert columns[0][2] == [0, 0, 0]
    assert columns[2][2] == [2, 1, 1]


def test_empty_texts():
    total, columns = align_three([], [], [])
    assert total == 0 and columns == []
    total, columns = align_three(list("甲乙"), [], [])
    assert total == 4  # 两列,每列仅一个非空字素,成本各 2
    assert [m for m, _, _ in columns] == [1, 1]


# ---------------------------------------------------------------- 共识规则

def test_consensus_majority_and_replacement():
    result = reconcile(list("甲丙"), list("甲丁"), list("甲乙"))
    assert result["consensus"] == "甲�"
    assert result["total_cost"] == 3  # 首列全同计 0,次列三者互异计 3
    assert len(result["uncertain"]) == 1
    u = result["uncertain"][0]
    assert u["column"] == 1
    assert [s["grapheme"] for s in u["sources"]] == ["丙", "丁", "乙"]
    assert [s["position"] for s in u["sources"]] == [1, 1, 1]


def test_consensus_two_of_three_agree_with_gap():
    # 来源 2 为空位,来源 0/1 一致 -> 仍达成共识
    result = reconcile(list("甲乙"), list("甲丙"), [])
    assert result["consensus"] == "甲�"
    assert result["uncertain"][0]["sources"][2] == {"grapheme": None, "position": None}


def test_consensus_all_identical():
    result = reconcile(list("档案"), list("档案"), list("档案"))
    assert result["consensus"] == "档案"
    assert result["total_cost"] == 0
    assert result["uncertain"] == []


# ---------------------------------------------------------------- API

def test_api_happy_path():
    resp = client.post("/reconcile", json={"texts": ["档案", "档案", "档案"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["consensus"] == "档案"
    assert body["total_cost"] == 0
    assert len(body["columns"]) == 2
    assert body["uncertain"] == []


def test_api_nfc_normalization():
    # "é" 的分解形式(NFD)与组合形式(NFC)应视为同一字素
    nfd = unicodedata.normalize("NFD", "é")
    nfc = unicodedata.normalize("NFC", "é")
    assert nfd != nfc
    resp = client.post("/reconcile", json={"texts": [nfd, nfc, nfc]})
    assert resp.status_code == 200
    assert resp.json()["total_cost"] == 0
    assert resp.json()["consensus"] == nfc


def test_api_grapheme_clusters_counted_not_codepoints():
    # 家庭 emoji 是单个字素簇但含多个码点;120 个簇合法,121 个拒绝
    family = "👨‍👩‍👧‍👦"
    ok = client.post("/reconcile", json={"texts": [family * 120, "", ""]})
    assert ok.status_code == 200
    too_many = client.post("/reconcile", json={"texts": [family * 121, "", ""]})
    assert too_many.status_code == 422


def test_api_requires_exactly_three_texts():
    for payload in ({"texts": ["a", "b"]}, {"texts": ["a", "b", "c", "d"]}, {"texts": []}):
        assert client.post("/reconcile", json=payload).status_code == 422


def test_api_rejects_over_120_graphemes():
    assert client.post("/reconcile", json={"texts": ["字" * 121, "", ""]}).status_code == 422
    assert client.post("/reconcile", json={"texts": ["字" * 120, "", ""]}).status_code == 200


def test_api_response_shape():
    resp = client.post("/reconcile", json={"texts": ["甲乙", "甲丙", "甲丁"]})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"consensus", "total_cost", "columns", "uncertain"}
    col = body["columns"][0]
    assert set(col) == {"index", "mask", "cost", "sources", "consensus"}
    assert len(col["sources"]) == 3
    assert body["consensus"] == "甲�"
    assert len(body["uncertain"]) == 1


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


# ---------------------------------------------------------------- 性能

def test_worst_case_performance():
    import time

    rng = random.Random(1)
    alphabet = [chr(0x4E00 + i) for i in range(200)]
    seqs = [[rng.choice(alphabet) for _ in range(120)] for _ in range(3)]
    start = time.perf_counter()
    result = reconcile(*seqs)
    elapsed = time.perf_counter() - start
    assert result["total_cost"] > 0
    assert elapsed < 10, f"120x120x120 对齐耗时 {elapsed:.1f}s"
