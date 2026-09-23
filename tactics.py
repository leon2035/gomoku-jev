"""残局测试：看 Jev 在「必须下某点」的局面里能不能下对。

python tactics.py                        # 默认：grid 与 lines 两种棋盘表示（bare 提问）
python tactics.py lines:bare lines:rules lines:local   # 指定 棋盘表示:提问方式
"""

import sys

import gomoku
from gomoku import BLACK, WHITE, label, pure_move

ROUNDS = 3


def pos(black, white):
    b = [[0] * gomoku.SIZE for _ in range(gomoku.SIZE)]
    for who, stones in ((BLACK, black), (WHITE, white)):
        for s in stones.split():
            b[int(s[1:]) - 1][gomoku.COLS.index(s[0])] = who
    return b


# (名称, 局面, 正确落点)；Jev 始终执白
TESTS = [
    ("横向冲四-该赢", pos("D8 F7 G9 J6", "E8 F8 G8 H8"), {"I8"}),
    ("跳四-该赢", pos("G7 G9 F6 J10", "E8 F8 H8 I8"), {"G8"}),
    ("斜向冲四-该赢", pos("C3 I5 C10 K11", "D4 E5 F6 G7"), {"H8"}),
    ("竖向冲四-该堵", pos("J5 J6 J7 J8", "J4 H8 G7"), {"J9"}),
    ("斜向跳四-该堵", pos("D4 E5 G7 H8", "C3 I9 J6"), {"F6"}),
    ("实战第6手-斜向活三该堵", pos("H8 I9 J10", "G8 I8"), {"G7", "K11"}),
    ("竖向冲四-该赢", pos("E4 D6 F7 G9", "E5 E6 E7 E8"), {"E9"}),
    ("反斜活三-该堵", pos("H8 G9 F10", "J5 K6"), {"I7", "E11"}),
    ("自己活三-冲活四", pos("B2 N2 B14", "F9 G9 H9"), {"E9", "I9"}),
    ("横向活三-该堵", pos("F8 G8 H8", "G7 H9"), {"E8", "I8"}),
]


def run(view, prompt="bare"):
    gomoku.JEV_VIEW, gomoku.JEV_PROMPT = view, prompt
    right = total = 0
    print(f"\n=== view = {view}, prompt = {prompt} ===", flush=True)
    for name, board, answer in TESTS:
        marks = []
        for _ in range(ROUNDS):
            _, _, info = pure_move(board, WHITE)
            ok = info.get("choice") in answer
            right += ok
            total += 1
            marks.append(f"{info.get('choice')}{'✓' if ok else '❌'}({info.get('confidence', 0):.2f})")
        print(f"{name:<16} 正确 {'/'.join(sorted(answer)):<7} {' '.join(marks)}")
    print(f"合计 {right}/{total}")
    return right, total


if __name__ == "__main__":
    for arg in sys.argv[1:] or ["grid", "lines"]:
        run(*arg.split(":"))
