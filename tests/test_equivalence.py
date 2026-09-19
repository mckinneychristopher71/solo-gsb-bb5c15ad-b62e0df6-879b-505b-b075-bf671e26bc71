"""随机对照：朴素三维 DP vs app 的向量化实现。仅开发/CI 使用。"""
import random
import time

from app.main import _column_cost, _normalize_and_split, align_three

MASKS = list(range(1, 8))


def naive(seq):
    a, b, c = seq
    na, nb, nc = len(a), len(b), len(c)
    INF = 10**9
    cost = [[[INF] * (nc + 1) for _ in range(nb + 1)] for _ in range(na + 1)]
    choice = [[[0] * (nc + 1) for _ in range(nb + 1)] for _ in range(na + 1)]
    cost[0][0][0] = 0

    def pref(m):
        return (m.bit_count(), -m)  # popcount 降序 -> 取大；mask 升序 -> 取 -m 大

    for i in range(na + 1):
        for j in range(nb + 1):
            for k in range(nc + 1):
                if i == j == k == 0:
                    continue
                for m in MASKS:
                    pi, pj, pk = i - (m & 1 != 0), j - ((m >> 1) & 1), k - ((m >> 2) & 1)
                    if pi < 0 or pj < 0 or pk < 0:
                        continue
                    vals = (
                        a[pi] if m & 1 else None,
                        b[pj] if m & 2 else None,
                        c[pk] if m & 4 else None,
                    )
                    v = cost[pi][pj][pk] + _column_cost(*vals)
                    if v < cost[i][j][k] or (
                        v == cost[i][j][k] and pref(m) > pref(choice[i][j][k])
                    ):
                        cost[i][j][k] = v
                        choice[i][j][k] = m
    # 回溯
    path = []
    i, j, k = na, nb, nc
    while i or j or k:
        m = choice[i][j][k]
        pi, pj, pk = i - (m & 1 != 0), j - ((m >> 1) & 1), k - ((m >> 2) & 1)
        path.append((m, pi if m & 1 else -1, pj if m & 2 else -1, pk if m & 4 else -1))
        i, j, k = pi, pj, pk
    path.reverse()
    return path, cost[na][nb][nc]


def validate_path(seq, path):
    pos = [0, 0, 0]
    total = 0
    for m, ia, ib, ic in path:
        assert 1 <= m <= 7
        idxs = [ia, ib, ic]
        for s in range(3):
            used = bool(m & (1 << s))
            assert (idxs[s] >= 0) == used
            if used:
                assert idxs[s] == pos[s]
                pos[s] += 1
        vals = tuple(seq[s][idxs[s]] if idxs[s] >= 0 else None for s in range(3))
        total += _column_cost(*vals)
    assert pos == [len(s) for s in seq]
    return total


def main():
    random.seed(20260919)
    alphabet = list("甲乙丙丁abc天地人") + ["é", "é", "ﬁ", "한"]
    for trial in range(400):
        lens = [random.randint(0, 7) for _ in range(3)]
        seq = [[random.choice(alphabet) for _ in range(n)] for n in lens]
        p1, t1 = align_three(seq)
        p2, t2 = naive(seq)
        assert t1 == t2, (seq, t1, t2)
        assert validate_path(seq, p1) == t1
        # 平局规则：路径（含 mask 序列）必须一致
        assert [c[0] for c in p1] == [c[0] for c in p2], (
            seq,
            [c[0] for c in p1],
            [c[0] for c in p2],
        )
    print("random equivalence: 400/400 passed")

    # 相同长文本、完全不同长文本、120 上限性能
    cases = [
        ["天地玄黄宇宙洪荒日月盈昃"] * 3,
        ["a" * 120, "b" * 120, "c" * 120],
        ["".join(random.choice("甲乙丙丁") for _ in range(120)) for _ in range(3)],
    ]
    for cs in cases:
        seq = [_normalize_and_split(x) for x in cs]
        t0 = time.perf_counter()
        p, total = align_three(seq)
        dt = time.perf_counter() - t0
        assert validate_path(seq, p) == total
        print(f"len={[len(s) for s in seq]} total_cost={total} time={dt:.3f}s cols={len(p)}")
        assert all(len(s) <= 120 for s in seq)


if __name__ == "__main__":
    main()
