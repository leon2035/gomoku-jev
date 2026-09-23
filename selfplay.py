"""自对弈：比较两个等级的棋力。

python selfplay.py master local     # 宗师 vs 本地引擎（看 Jev 裁决有没有用）
python selfplay.py local assisted

每个开局两方各执一次黑，结果追加到 selfplay.jsonl。
"""

import json
import sys
import time
from datetime import datetime

import engine
import gomoku
from gomoku import BLACK, WHITE, SIZE, label

# 固定几个开局（黑、白、黑），避免确定性引擎每局都一样
OPENINGS = [
    ["H8", "I9", "G9"],
    ["H8", "H9", "I7"],
    ["H8", "I8", "I9"],
    ["H8", "J10", "G7"],
]
SEARCH_DEPTH = 6


def play(black_level, white_level, opening):
    board = [[0] * SIZE for _ in range(SIZE)]
    moves, jev = [], {BLACK: [0, 0], WHITE: [0, 0]}  # [Jev 调用, AI 步数]
    who = BLACK
    for mv in opening:
        board[int(mv[1:]) - 1][gomoku.COLS.index(mv[0])] = who
        moves.append(mv)
        who = WHITE if who == BLACK else BLACK
    while len(moves) < SIZE * SIZE:
        level = black_level if who == BLACK else white_level
        r, c, info = gomoku.ai_move(board, who, level)
        jev[who][1] += 1
        jev[who][0] += bool(info.get("jev_called"))
        board[r][c] = who
        moves.append(label(r, c))
        if gomoku.is_five(board, r, c, who):
            return who, moves, jev
        who = WHITE if who == BLACK else BLACK
    return None, moves, jev


def main(a, b):
    engine_search = engine.search
    engine.search = lambda pos, who: engine_search(pos, who, depth=SEARCH_DEPTH)
    score = {a: 0, b: 0, "draw": 0}
    for op in OPENINGS:
        for black, white in ((a, b), (b, a)):
            t = time.time()
            winner, moves, jev = play(black, white, op)
            name = {BLACK: black, WHITE: white}.get(winner, "draw")
            score[name] += 1
            calls = {black: jev[BLACK], white: jev[WHITE]}
            print(f"{' '.join(op):<12} 黑={black:<8} 白={white:<8} 胜={name:<8} "
                  f"{len(moves)} 手 {time.time() - t:5.1f}s  Jev 调用 "
                  + ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in calls.items()), flush=True)
            with open("selfplay.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"),
                                    "black": black, "white": white, "winner": name,
                                    "total_moves": len(moves), "jev_calls": calls,
                                    "moves": moves}, ensure_ascii=False) + "\n")
    print("总比分:", score)


if __name__ == "__main__":
    main(*(sys.argv[1:3] if len(sys.argv) >= 3 else ("master", "local")))
