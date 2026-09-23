"""本地五子棋引擎（无禁手，>=5 连即胜）。

- Pos: 棋盘 + 所有「5 格窗口」的黑白计数，落子/悔子时增量更新局面分
- search(): 路线 A，alpha-beta 搜索
- vcf():    连续冲四取胜搜索
- threat_move(): 路线 B，威胁引擎（自己的 VCF / 破对手 VCF / 静态攻防）
"""

import time

SIZE = 15
EMPTY, BLACK, WHITE = 0, 1, 2
WIN = 10_000_000
# 窗口里只有一方 n 个子时的分值
V = [0, 1, 12, 150, 2000, WIN]

# ---- 预计算所有 5 格窗口 ----
WINDOWS = []
for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
    for r in range(SIZE):
        for c in range(SIZE):
            er, ec = r + 4 * dr, c + 4 * dc
            if 0 <= er < SIZE and 0 <= ec < SIZE:
                WINDOWS.append(tuple((r + i * dr) * SIZE + (c + i * dc) for i in range(5)))
CELL_WINDOWS = [[] for _ in range(SIZE * SIZE)]
for wi, w in enumerate(WINDOWS):
    for idx in w:
        CELL_WINDOWS[idx].append(wi)
NEAR = []
for idx in range(SIZE * SIZE):
    r, c = divmod(idx, SIZE)
    NEAR.append([rr * SIZE + cc for rr in range(r - 2, r + 3) for cc in range(c - 2, c + 3)
                 if 0 <= rr < SIZE and 0 <= cc < SIZE and (rr, cc) != (r, c)])


def other(who):
    return BLACK if who == WHITE else WHITE


def sign(who):
    return 1 if who == BLACK else -1


def wval(b, w):
    if b and w:
        return 0
    if b:
        return V[b]
    if w:
        return -V[w]
    return 0


class Pos:
    def __init__(self, board):
        self.grid = [v for row in board for v in row]
        self.cnt = {BLACK: [0] * len(WINDOWS), WHITE: [0] * len(WINDOWS)}
        self.stones = []
        self.score = 0  # 黑方视角
        for idx, v in enumerate(self.grid):
            if v:
                self.grid[idx] = EMPTY
                self.place(idx, v)

    def place(self, idx, who):
        cb, cw = self.cnt[BLACK], self.cnt[WHITE]
        mine = self.cnt[who]
        for wi in CELL_WINDOWS[idx]:
            before = wval(cb[wi], cw[wi])
            mine[wi] += 1
            self.score += wval(cb[wi], cw[wi]) - before
        self.grid[idx] = who
        self.stones.append(idx)

    def undo(self, idx, who):
        cb, cw = self.cnt[BLACK], self.cnt[WHITE]
        mine = self.cnt[who]
        for wi in CELL_WINDOWS[idx]:
            before = wval(cb[wi], cw[wi])
            mine[wi] -= 1
            self.score += wval(cb[wi], cw[wi]) - before
        self.grid[idx] = EMPTY
        self.stones.pop()

    def gain(self, idx, who):
        """who 在 idx 落子后，局面分对 who 的提升量。"""
        cb, cw = self.cnt[BLACK], self.cnt[WHITE]
        d = 0
        for wi in CELL_WINDOWS[idx]:
            b, w = cb[wi], cw[wi]
            before = wval(b, w)
            d += (wval(b + 1, w) if who == BLACK else wval(b, w + 1)) - before
        return d * sign(who)

    def points(self, who, n):
        """窗口里 who 有 n 子、对方 0 子时，窗口内的空点。n=4 即成五点，n=3 即冲四点。"""
        mine, theirs = self.cnt[who], self.cnt[other(who)]
        out = set()
        for wi, w in enumerate(WINDOWS):
            if mine[wi] == n and theirs[wi] == 0:
                out.update(i for i in w if self.grid[i] == EMPTY)
        return out

    def fives(self, who):
        return self.points(who, 4)

    def candidates(self):
        if not self.stones:
            return [SIZE * SIZE // 2]
        seen = set()
        for s in self.stones:
            for n in NEAR[s]:
                if self.grid[n] == EMPTY:
                    seen.add(n)
        return list(seen)

    def ordered(self, who, k):
        """按「自己进攻收益 + 阻止对方收益」排序的前 k 个点。"""
        opp = other(who)
        scored = [(self.gain(i, who) + 0.9 * self.gain(i, opp), i) for i in self.candidates()]
        scored.sort(reverse=True)
        return [i for _, i in scored[:k]]


# ---------------- 路线 A：alpha-beta ----------------

class Timeout(Exception):
    pass


def negamax(pos, who, depth, alpha, beta, ply, deadline, width):
    if time.time() > deadline:
        raise Timeout
    opp = other(who)
    if pos.fives(who):
        return WIN - ply
    opp_fives = pos.fives(opp)
    if len(opp_fives) >= 2:
        return -(WIN - ply - 1)
    if depth == 0:
        return pos.score * sign(who)
    moves = list(opp_fives) if opp_fives else pos.ordered(who, width)
    best = -WIN * 2
    for m in moves:
        pos.place(m, who)
        try:
            v = -negamax(pos, opp, depth - 1, -beta, -alpha, ply + 1, deadline, width)
        finally:
            pos.undo(m, who)
        if v > best:
            best = v
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


def search(pos, who, depth=8, width=10, time_limit=6.0):
    """迭代加深，返回 (最佳点, 分值, 已完成深度, [(点, 分值), ...])。"""
    deadline = time.time() + time_limit
    opp = other(who)
    root = pos.ordered(who, width + 4)
    result = (root[0], 0, 0, [])
    for d in range(2, depth + 1):
        try:
            scored = []
            alpha = -WIN * 2
            for m in root:
                pos.place(m, who)
                try:
                    v = -negamax(pos, opp, d - 1, -WIN * 2, -alpha, 1, deadline, width)
                finally:
                    pos.undo(m, who)
                scored.append((v, m))
                alpha = max(alpha, v)
            scored.sort(reverse=True)
            root = [m for _, m in scored]  # 下一轮按本轮结果排序
            result = (scored[0][1], scored[0][0], d, [(m, v) for v, m in scored])
        except Timeout:
            break  # 用上一层完整结果
    return result


def search_move(pos, who, m, depth, width=10, time_limit=6.0):
    """用与 search 相同的深度评估指定的一步。"""
    deadline = time.time() + time_limit
    pos.place(m, who)
    try:
        return -negamax(pos, other(who), depth - 1, -WIN * 2, WIN * 2, 1, deadline, width)
    except Timeout:
        return -WIN  # 评估不完就当作不可取
    finally:
        pos.undo(m, who)


# ---------------- VCF：连续冲四取胜 ----------------

def vcf(pos, who, depth=12, budget=None):
    """who 先走时若有连续冲四必胜，返回第一手；否则 None。"""
    budget = budget if budget is not None else [4000]
    return _vcf(pos, who, depth, budget)


def _vcf(pos, who, depth, budget):
    opp = other(who)
    my_fives = pos.fives(who)
    if my_fives:
        return next(iter(my_fives))
    if depth <= 0 or budget[0] <= 0:
        return None
    opp_fives = pos.fives(opp)
    if len(opp_fives) >= 2:
        return None
    moves = pos.points(who, 3)
    if opp_fives:
        moves &= opp_fives  # 必须边堵边冲四
    for m in moves:
        budget[0] -= 1
        pos.place(m, who)
        fs = pos.fives(who)
        found = False
        if len(fs) >= 2:
            found = True  # 双四 / 活四
        elif len(fs) == 1:
            block = next(iter(fs))
            pos.place(block, opp)
            found = _vcf(pos, who, depth - 1, budget) is not None
            pos.undo(block, opp)
        pos.undo(m, who)
        if found:
            return m
    return None


# ---------------- 路线 B：威胁引擎 ----------------

def threat_move(pos, who, width=15):
    """返回 (点, 理由)。"""
    opp = other(who)
    ordered = pos.ordered(who, width)
    if vcf(pos, opp) is not None:
        for m in ordered:
            pos.place(m, who)
            safe = vcf(pos, opp) is None
            pos.undo(m, who)
            if safe:
                return m, "breaks opponent's winning sequence of fours"
        return ordered[0], "opponent has a forced win; best static move"
    return ordered[0], "best attack/defense shape score"


def unsafe(pos, who, m):
    """who 下 m 之后，对方是否立即成五或有 VCF。"""
    opp = other(who)
    pos.place(m, who)
    bad = vcf(pos, opp) is not None  # 含对方直接成五
    pos.undo(m, who)
    return bad


def forced(pos, who):
    """必走棋：自己成五 / 堵对方成五 / 自己 VCF。返回 (点, 理由) 或 None。"""
    opp = other(who)
    f = pos.fives(who)
    if f:
        return min(f), "winning move"
    f = pos.fives(opp)
    if f:
        return min(f), "forced block"
    m = vcf(pos, who)
    if m is not None:
        return m, "forced win by continuous fours (VCF)"
    return None
