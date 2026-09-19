# 三抄本核校 API（Tripartite Reconciliation）

供档案员核对三份独立抄录的 HTTP 服务：对三段文本先做 **NFC 规范化** 与
**Unicode 字素簇（grapheme cluster）切分**，再做**三维全局动态规划对齐**，
输出逐列对齐结果、共识字素与总成本。

- 框架：Python 3.12 + FastAPI + Uvicorn（NumPy 向量化 DP）
- 每段文本上限：120 个字素簇（NFC 规范化后计数）

## 一条命令启动

```bash
docker compose up --build -d
```

## 访问地址与端口

- 服务地址：<http://localhost:8000>
- 接口：`POST http://localhost:8000/reconcile`
- 健康检查：`GET http://localhost:8000/health`
- 交互式文档（Swagger UI）：<http://localhost:8000/docs>

停止服务：`docker compose down`

## 请求

`POST /reconcile`，JSON 体中 `texts` 必须是**恰好 3 个字符串**（依次为来源 A/B/C，
允许空字符串），每段 NFC 规范化后不超过 120 个字素簇，否则返回 `422`。

```bash
curl -s -X POST http://localhost:8000/reconcile \
  -H 'Content-Type: application/json' \
  -d '{"texts": ["古籍抄本甲", "古籍抄本甲", "古籍钞本甲"]}'
```

## 响应

| 字段 | 说明 |
| --- | --- |
| `total_cost` | 三维 DP 最小化后的全局对齐总成本 |
| `normalized_lengths` | 三段文本 NFC 规范化后的字素簇数量 |
| `columns[]` | 对齐列（按对齐顺序） |
| `columns[].mask` | 本列消费的来源位掩码：A=1，B=2，C=4（如 7 表示三份同列） |
| `columns[].consensus` | 共识字素；不满足共识条件时为 `�`（U+FFFD） |
| `columns[].conflict` | 是否无共识（`consensus` 为 U+FFFD 时为 `true`） |
| `columns[].cost` | 本列成本 |
| `columns[].sources[]` | 固定 3 项，依次为来源 A/B/C；`char` 为该列字素（空位为 `null`），`pos` 为其在 NFC 规范化后原文本中的 **0 基**位置（空位为 `null`） |

### 对齐与计分规则

- 每个对齐列可消费**任意非空来源组合**（位掩码 1–7），各来源字素在自己的
  序列中至多出现一次、保持原有顺序。
- 列内将三个位置（来源 A/B/C，未消费为空位）**两两配成三对**逐对计分
  （sum-of-pairs）：**字符与字符不相等计 1、相等计 0；字符与空位配对每对
  计 1；空位与空位配对计 0**。各列成本为：
  - 三份字素全相同：0
  - 恰好两份相同（如 `天,天,地`）：2（字符对 0 + 两个字符-空位对 1+1）
  - 三份互不相同（如 `a,b,c`）：3
  - 仅两份且字素不同（如 `甲,乙,空`）：3（字符对 1 + 两个字符-空位对 1+1）
  - 仅一份非空（如 `甲,空,空`）：2（两个字符-空位对）
- DP 最小化所有列的总成本。**总成本相同时的平局偏好**依次为：
  1. 该列消费来源数更多（位掩码 popcount 更大）；
  2. 位掩码数值更小（来源顺序 A<B<C，故 `3(A,B) < 5(A,C) < 6(B,C)`）。
- 当某列**至少有两份相同的非空字素**时，将该字素写入 `consensus`；
  否则 `consensus` 写入 `�`，并在 `sources` 中返回各来源字素及其原位置，
  供档案员人工裁定。

响应示例（节选）：

```json
{
  "total_cost": 3,
  "normalized_lengths": [5, 5, 5],
  "columns": [
    {
      "mask": 7,
      "consensus": "古",
      "conflict": false,
      "cost": 0,
      "sources": [
        {"char": "古", "pos": 0},
        {"char": "古", "pos": 0},
        {"char": "古", "pos": 0}
      ]
    }
  ]
}
```

## 本地开发（不使用容器）

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
