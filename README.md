# gomoku-jev

和 [TypeSafe Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) 下五子棋，同时测一测 Jev 在五子棋上到底能起多大作用。

纯 Python 标准库实现，无第三方依赖。

## 运行

```bash
cp config.example.py config.py   # 填入 TYPESAFE_API_KEY
python gomoku.py
# 打开 http://localhost:8765
```

没有 key 时，本地引擎等级照样能玩，用到 Jev 的等级会退回本地启发式。

## 等级

| 等级 | 说明 |
|---|---|
| 宗师 `master` | 必走棋（成五 / 堵五 / 自己 VCF）直接下；否则 alpha-beta 搜索与威胁引擎两路并行，一致直接下；分歧时先排除会让对手必胜的点，两点搜索分接近时才交给 Jev 裁决 |
| 本地 `local` | 同上，但不调用 Jev，分歧取 alpha-beta |
| 辅助 `assisted` | 成五 / 堵五本地处理，其余由启发式挑 8 个候选交给 Jev 选 |
| 直觉 `pure` | 周围所有空点交给 Jev 选，无提示、无兜底，事后标记失误 |

页面上会显示每一步的决策来源，以及本局 Jev 参与的步数。每局结束后，手数和棋谱会写入 `games.jsonl`。

## 文件

- `gomoku.py`：HTTP 服务、Jev 调用、各等级走子逻辑
- `engine.py`：本地引擎（5 格窗口增量评估、alpha-beta、VCF）
- `index.html`：棋盘页面
- `tactics.py`：残局测试，比较两种给 Jev 的棋盘表示
- `selfplay.py`：两个等级之间自对弈，例如 `python selfplay.py master local`

## 实验结论（2026-09，jev-latest）

**残局测试**（6 个必须下在某一点的局面，每个 3 次，纯 Jev）：

| 给 Jev 的棋盘表示 | 正确率 |
|---|---|
| 只给棋盘文字图 | 6/18，只认得横向 |
| 额外列出每条横 / 竖 / 斜线 | 12/18，斜向也能认出，但对手竖向冲四仍然不会堵 |

**自对弈**（4 个开局 × 双方轮流执黑）：

| 对局 | 比分 |
|---|---|
| 本地 vs 辅助 | 8 : 0 |
| 本地 vs 本地 | 执黑全胜，基准为 4 : 4 |
| 宗师 vs 本地 | 2 : 6 |
| 分歧时用抛硬币代替 Jev | 3 : 5 / 4 : 4 |

在这组样本里，由 Jev 裁决的效果不比随机选择好。棋力基本来自本地引擎。样本量小，仅供参考。
