# 抄本核对 API

供档案员核对三份独立抄录的 Web API:对三段文本做 NFC 规范化后,用三维全局动态规划对齐,生成共识文本,并报告对齐列与总成本。

## 启动

只需一条命令(依赖随镜像构建自动安装):

```bash
docker compose up --build
```

- 服务地址: <http://localhost:8000>
- 交互式文档(Swagger UI): <http://localhost:8000/docs>
- 健康检查: <http://localhost:8000/health>

## 接口

### `POST /reconcile`

请求体为恰好三段文本,每段不超过 **120 个 Unicode 字素簇**(按 UAX #29 切分,如 `👨‍👩‍👧‍👦` 计 1 个;先 NFC 规范化再对齐):

```json
{
  "texts": ["甲丙", "甲丁", "甲乙"]
}
```

```bash
curl -X POST http://localhost:8000/reconcile \
  -H "Content-Type: application/json" \
  -d '{"texts": ["甲丙", "甲丁", "甲乙"]}'
```

响应示例:

```json
{
  "consensus": "甲�",
  "total_cost": 3,
  "columns": [
    {
      "index": 0,
      "mask": 7,
      "cost": 0,
      "sources": [
        {"grapheme": "甲", "position": 0},
        {"grapheme": "甲", "position": 0},
        {"grapheme": "甲", "position": 0}
      ],
      "consensus": "甲"
    },
    {
      "index": 1,
      "mask": 7,
      "cost": 3,
      "sources": [
        {"grapheme": "丙", "position": 1},
        {"grapheme": "丁", "position": 1},
        {"grapheme": "乙", "position": 1}
      ],
      "consensus": "�"
    }
  ],
  "uncertain": [
    {
      "column": 1,
      "sources": [
        {"grapheme": "丙", "position": 1},
        {"grapheme": "丁", "position": 1},
        {"grapheme": "乙", "position": 1}
      ]
    }
  ]
}
```

## 对齐规则

- 每列可消费任意非空来源组合,以位掩码表示:bit0/1/2 分别对应 `texts[0]/texts[1]/texts[2]`(如 `mask=5` 表示该列消费来源 0 与 2)。
- 单列成本:两两配对中,字符不等或字符与空位配对各计 1,空位与空位计 0;总成本为各列之和,取全局最小。
- 平局时依次偏好:消费来源数更多的掩码、位掩码更小的掩码(优先级 `7 > 3 > 5 > 6 > 1 > 2 > 4`)。
- 共识:某列至少两份相同非空字素时写入该字素,否则写入 `�`,并在 `uncertain` 中列出该列各来源的字素与原位置(0 起始,空位为 `null`)。

## 本地开发

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload        # http://localhost:8000
python -m pytest tests/              # 运行测试(含与纯 Python 参考实现的随机对拍)
```
