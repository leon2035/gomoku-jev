"""五子棋 vs Jev。

运行: python gomoku.py  然后浏览器打开 http://localhost:8765
TYPESAFE_API_KEY 放在环境变量或同目录 config.py；没有 key 或调用失败时退回本地启发式。

等级（页面可切，JEV_MODE 设默认值）:
  master   宗师：必走棋直接下；否则 alpha-beta 与威胁引擎两路并行，一致直接下，
           分歧时先做安全检查，都安全才交给 Jev 裁决（见 engine_move）
  local    本地引擎：同上但不问 Jev，分歧取 alpha-beta
  assisted 辅助：成五/堵五本地处理，其余由启发式挑 8 个候选交给 Jev 选
  pure     纯 Jev：周围所有空点交给 Jev 选，无提示无兜底，事后标记失误
JEV_VIEW=lines（默认）在棋盘图之外列出每条有子的横/竖/斜线；grid 只给棋盘图。
残局测试: python tactics.py    自对弈: python selfplay.py
"""

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import engine

SIZE = 15
EMPTY, BLACK, WHITE = 0, 1, 2
COLS = "ABCDEFGHIJKLMNO"
DIRS = [(0, 1), (1, 0), (1, 1), (1, -1)]

def load_config():
    """读取同目录 config.py 里的 KEY=VALUE（值可带可不带引号），环境变量优先。"""
    path = Path(__file__).parent / "config.py"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


load_config()

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = os.environ.get("JEV_MODEL", "jev-latest")
TOP_K = 8
# 默认等级（页面可切换）：master / local / assisted / pure，见 LEVELS
JEV_MODE = os.environ.get("JEV_MODE", "master")
# grid: 只给棋盘文字图；lines: 额外列出每条有子的横/竖/斜线
JEV_VIEW = os.environ.get("JEV_VIEW", "lines")
# 纯 Jev 等级的提问方式：bare / rules / local，见 pure_prompt
JEV_PROMPT = os.environ.get("JEV_PROMPT", "local")
PORT = int(os.environ.get("PORT", "8765"))


def label(r, c):
    return f"{COLS[c]}{r + 1}"


def in_board(r, c):
    return 0 <= r < SIZE and 0 <= c < SIZE


def line_info(board, r, c, dr, dc, who):
    """假设 (r,c) 落 who 后，该方向的连子数和两端开放数。"""
    count, open_ends = 1, 0
    for sign in (1, -1):
        rr, cc = r + dr * sign, c + dc * sign
        while in_board(rr, cc) and board[rr][cc] == who:
            count += 1
            rr += dr * sign
            cc += dc * sign
        if in_board(rr, cc) and board[rr][cc] == EMPTY:
            open_ends += 1
    return count, open_ends


def is_five(board, r, c, who):
    return any(line_info(board, r, c, dr, dc, who)[0] >= 5 for dr, dc in DIRS)


def shape_score(count, open_ends):
    if count >= 5:
        return 100000
    if open_ends == 0:
        return 0
    table = {
        4: (10000, 1000),  # 活四 / 冲四
        3: (1000, 100),
        2: (100, 10),
        1: (10, 1),
    }
    live, dead = table[count]
    return live if open_ends == 2 else dead


def describe(count, open_ends):
    if count >= 5:
        return "five"
    kind = "open" if open_ends == 2 else "closed"
    return f"{kind} {count}"


def evaluate(board, r, c, me, opp):
    attack = defend = 0
    notes = []
    for dr, dc in DIRS:
        a = line_info(board, r, c, dr, dc, me)
        d = line_info(board, r, c, dr, dc, opp)
        attack += shape_score(*a)
        defend += shape_score(*d)
        if a[0] >= 3 and a[1] > 0:
            notes.append(f"makes my {describe(*a)}")
        if d[0] >= 3 and d[1] > 0:
            notes.append(f"denies opponent's {describe(*d)}")
    # 进攻略优先于防守
    return attack * 1.1 + defend, notes


def neighbors(board):
    """只考虑已有棋子周围 2 格内的空点。"""
    cells = set()
    has_stone = False
    for r in range(SIZE):
        for c in range(SIZE):
            if board[r][c] != EMPTY:
                has_stone = True
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        rr, cc = r + dr, c + dc
                        if in_board(rr, cc) and board[rr][cc] == EMPTY:
                            cells.add((rr, cc))
    if not has_stone:
        return {(SIZE // 2, SIZE // 2)}
    return cells


def candidates(board, me, opp):
    scored = []
    for r, c in neighbors(board):
        s, notes = evaluate(board, r, c, me, opp)
        scored.append((s, r, c, notes))
    scored.sort(key=lambda x: -x[0])
    return scored[:TOP_K]


SYM = {EMPTY: ".", BLACK: "X", WHITE: "O"}
LINE_DIRS = [((0, 1), "row"), ((1, 0), "column"), ((1, 1), "diagonal ↘"), ((1, -1), "diagonal ↙")]


def board_lines():
    """所有长度 >= 5 的横/竖/斜线，每条是 (名称, [(r,c), ...])。"""
    out = []
    for (dr, dc), name in LINE_DIRS:
        for r0 in range(SIZE):
            for c0 in range(SIZE):
                # 只从线的起点出发
                if in_board(r0 - dr, c0 - dc):
                    continue
                cells = []
                r, c = r0, c0
                while in_board(r, c):
                    cells.append((r, c))
                    r, c = r + dr, c + dc
                if len(cells) >= 5:
                    out.append((name, cells))
    return out


def render_lines(board):
    """把有子的每条线截出「棋子所在范围 ±2 格」，逐格写出坐标和内容。"""
    rows = []
    for name, cells in board_lines():
        idx = [i for i, (r, c) in enumerate(cells) if board[r][c] != EMPTY]
        if len(idx) < 2:  # 单子的线没信息量，只会增加噪音
            continue
        lo, hi = max(0, idx[0] - 2), min(len(cells) - 1, idx[-1] + 2)
        seg = " ".join(f"{label(r, c)}{SYM[board[r][c]]}" for r, c in cells[lo:hi + 1])
        rows.append(f"{name}: {seg}")
    return "\n".join(rows)


def render_board(board, me):
    lines = ["   " + " ".join(COLS[:SIZE])]
    for r in range(SIZE):
        lines.append(f"{r + 1:>2} " + " ".join(SYM[v] for v in board[r]))
    text = (
        f"Gomoku (five in a row) on a {SIZE}x{SIZE} board. "
        f"X = black, O = white. You play {SYM[me]}. "
        "Getting exactly five or more in a row horizontally, vertically or diagonally wins.\n\n"
        + "\n".join(lines)
    )
    if JEV_VIEW == "lines":
        text += (
            "\n\nEvery row, column and diagonal that contains two or more stones, "
            "as consecutive cells (coordinate + content):\n" + render_lines(board)
        )
    return text


def ask_jev(board, me, criteria, instructions):
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        return None, "no TYPESAFE_API_KEY"

    body = {
        "model": JEV_MODEL,
        "state": render_board(board, me),
        "questions": {
            "move": {
                "type": "choice",
                "instructions": instructions,
                "criteria": criteria,
            }
        },
    }
    req = urllib.request.Request(
        JEV_URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"
    except Exception as e:  # 网络错误等
        return None, f"{type(e).__name__}: {e}"

    ans = (data.get("answers") or {}).get("move") or {}
    choice = ans.get("choice")
    if choice not in criteria:
        return None, f"unexpected response: {json.dumps(data)[:200]}"
    return {"choice": choice, "confidence": ans.get("confidence"),
            "probabilities": ans.get("probabilities")}, None


LEVELS = {
    "master": "宗师：两路引擎，分歧时 Jev 裁决",
    "local": "本地引擎：不用 Jev",
    "assisted": "辅助：启发式候选 + Jev 选",
    "pure": "纯 Jev：无提示无兜底",
}


def ai_move(board, me, level=None):
    level = level if level in LEVELS else JEV_MODE
    if level == "master":
        r, c, info = engine_move(board, me, use_jev=True)
    elif level == "local":
        r, c, info = engine_move(board, me, use_jev=False)
    elif level == "pure":
        r, c, info = pure_move(board, me)
    else:
        r, c, info = assisted_move(board, me)
    info.setdefault("jev_called", info.get("source") == "jev")
    return r, c, info


# 两路分歧时，B 的搜索分与 A 相差在此范围内才算「真分歧」交给 Jev
CLOSE_ABS = 150
CLOSE_REL = 0.1


def lbl(idx):
    return label(*divmod(idx, SIZE))


def engine_move(board, me, use_jev):
    """宗师 / 本地引擎。

    必走棋（成五、堵五、自己 VCF）直接下；否则
      路线 A: alpha-beta 搜索     路线 B: 威胁引擎
    两路一致 -> 直接下；分歧 -> 只有一个安全就下安全的，都安全才交给 Jev 裁决。
    本地引擎模式不问 Jev，分歧时取路线 A。
    """
    pos = engine.Pos(board)
    f = engine.forced(pos, me)
    if f:
        m, why = f
        r, c = divmod(m, SIZE)
        return r, c, {"source": "local", "jev_called": False,
                      "summary": f"必走棋 {lbl(m)}：{why}"}

    a, a_val, a_depth, a_list = engine.search(pos, me)
    b, b_why = engine.threat_move(pos, me)
    head = f"搜索引擎(深度{a_depth}) → {lbl(a)}；威胁引擎 → {lbl(b)}"

    def done(m, text, **extra):
        r, c = divmod(m, SIZE)
        return r, c, {"source": extra.pop("source", "local"), "jev_called": False,
                      "summary": f"{head}。{text}", **extra}

    if a == b:
        return done(a, "两路一致，直接落子")
    if not use_jev:
        return done(a, "两路分歧，本地模式取搜索引擎")

    a_bad, b_bad = engine.unsafe(pos, me, a), engine.unsafe(pos, me, b)
    if a_bad != b_bad:
        m = b if a_bad else a
        return done(m, f"两路分歧，{lbl(a if a_bad else b)} 会让对手有连续冲四必胜，选安全的 {lbl(m)}")

    # 用搜索引擎给 B 的点打分；B 明显更差就不是真分歧，不打扰 Jev
    # （a_list 里非最佳点的分只是 alpha-beta 上界，所以单独算一遍）
    b_val = engine.search_move(pos, me, b, a_depth)
    if a_val - b_val > max(CLOSE_ABS, abs(a_val) * CLOSE_REL):
        return done(a, f"两路分歧，但搜索评估 {lbl(b)}({b_val:+d}) 明显差于 {lbl(a)}({a_val:+d})，取搜索引擎")

    if JEV_PROMPT == "bare":
        criteria = {
            lbl(a): f"Place at {lbl(a)}: choice of a depth-{a_depth} alpha-beta search engine "
                    f"(evaluation {a_val:+d} for you)",
            lbl(b): f"Place at {lbl(b)}: choice of a threat-based engine ({b_why})",
        }
        instructions = ("Two gomoku engines disagree about your next move. "
                        "Pick the move that gives you better winning chances.")
    else:
        # 与纯 Jev 相同的提问方式：通用规则 + 每个点四条线上的棋子
        criteria = {lbl(m): f"Place a stone at {lbl(m)}. Stones around it — "
                            f"{local_view(board, *divmod(m, SIZE))}" for m in (a, b)}
        instructions = (RULES + " Both options are considered safe by an engine; "
                        "prefer the one that builds more of your own open lines "
                        "while limiting the opponent's.")
    result, err = ask_jev(board, me, criteria, instructions)
    if not result:
        return done(a, f"两路分歧，Jev 调用失败（{err}），取搜索引擎")
    m = a if result["choice"] == lbl(a) else b
    r, c = divmod(m, SIZE)
    return r, c, {"source": "jev", "jev_called": True, "choice": result["choice"],
                  "confidence": result["confidence"], "probabilities": result["probabilities"],
                  "summary": f"{head}。两路分歧 → Jev 裁决选 {result['choice']}"
                             f"（置信度 {result['confidence']:.0%}）"}


RULES = (
    "Pick your next move in this gomoku game. Apply these rules in order: "
    "1) if a move completes five of your stones in a row, play it; "
    "2) otherwise, if the opponent could complete five on their next move, occupy that cell; "
    "3) otherwise, if you can make an open four (four in a row with both ends empty), play it; "
    "4) otherwise, if the opponent has an open three or a broken three, block one of its ends or its gap; "
    "5) otherwise, extend your own longest line while keeping its ends open."
)


def local_view(board, r, c):
    """(r,c) 四个方向各 4 格内的棋子，候选点记为 [坐标]。只描述棋盘内容，不做判断。"""
    parts = []
    for (dr, dc), name in LINE_DIRS:
        seg = []
        for k in range(-4, 5):
            rr, cc = r + dr * k, c + dc * k
            if not in_board(rr, cc):
                continue
            seg.append(f"[{label(rr, cc)}]" if k == 0 else f"{label(rr, cc)}{SYM[board[rr][cc]]}")
        parts.append(f"{name}: {' '.join(seg)}")
    return "; ".join(parts)


def pure_prompt(board, me, cells):
    """JEV_PROMPT: bare（只有坐标）/ rules（通用优先级规则）/ local（规则 + 每个点周围的棋子）。"""
    if JEV_PROMPT == "bare":
        return ({label(r, c): f"Place a stone at {label(r, c)}" for r, c in cells},
                "Pick the strongest next move for you.")
    if JEV_PROMPT == "rules":
        return {label(r, c): f"Place a stone at {label(r, c)}" for r, c in cells}, RULES
    return ({label(r, c): f"Place a stone at {label(r, c)}. Stones around it — "
                          f"{local_view(board, r, c)}" for r, c in cells},
            RULES + " Each option lists the stones on the four lines through that cell; "
                    "the candidate cell is shown in brackets.")


def pure_move(board, me):
    """纯 Jev：周围所有空点都给它选，不给提示、不做本地兜底，只在事后判定失误。"""
    opp = BLACK if me == WHITE else WHITE
    cells = sorted(neighbors(board))  # 按棋盘位置排序，避免排名暗示
    wins = {label(r, c) for r, c in cells if is_five(board, r, c, me)}
    blocks = {label(r, c) for r, c in cells if is_five(board, r, c, opp)}

    criteria, instructions = pure_prompt(board, me, cells)
    result, err = ask_jev(board, me, criteria, instructions)
    if not result:
        _, r, c, _ = candidates(board, me, opp)[0]
        return r, c, {"source": "heuristic", "reason": err or "fallback"}

    choice = result["choice"]
    mistake = None
    if wins and choice not in wins:
        mistake = f"漏掉了必胜点 {'/'.join(sorted(wins))}"
    elif not wins and blocks and choice not in blocks:
        mistake = f"没堵对手的五连点 {'/'.join(sorted(blocks))}"
    top = sorted(result["probabilities"].items(), key=lambda x: -x[1])[:3]
    for r, c in cells:
        if label(r, c) == choice:
            return r, c, {"source": "jev", "mode": "pure", "choice": choice,
                          "confidence": result["confidence"], "options": len(cells),
                          "top3": top, "mistake": mistake}


def assisted_move(board, me):
    opp = BLACK if me == WHITE else WHITE
    empties = neighbors(board)

    for r, c in empties:
        if is_five(board, r, c, me):
            return r, c, {"source": "local", "reason": "winning move"}
    for r, c in empties:
        if is_five(board, r, c, opp):
            return r, c, {"source": "local", "reason": "forced block"}

    cands = candidates(board, me, opp)
    if len(cands) == 1:
        _, r, c, _ = cands[0]
        return r, c, {"source": "local", "reason": "only candidate"}

    criteria = {}
    for _, r, c, notes in cands:
        hint = "; ".join(notes) if notes else "positional move"
        criteria[label(r, c)] = f"Place a stone at {label(r, c)} ({hint})"
    result, err = ask_jev(board, me, criteria, (
        "Pick the strongest next move for you. Prioritize winning, "
        "then blocking the opponent's open threes/fours, then building "
        "your own double threats."
    ))
    if result:
        lbl = result["choice"]
        for _, r, c, _ in cands:
            if label(r, c) == lbl:
                return r, c, {"source": "jev", **result,
                              "candidates": [label(r2, c2) for _, r2, c2, _ in cands]}

    _, r, c, _ = cands[0]
    return r, c, {"source": "heuristic", "reason": err or "fallback"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (Path(__file__).parent / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length))
        if self.path == "/record":
            return self._record(req)
        if self.path != "/move":
            return self._send(404, "not found", "text/plain")
        board, me = req["board"], req["ai"]
        move_no = sum(v != EMPTY for row in board for v in row) + 1
        r, c, info = ai_move(board, me, req.get("level"))
        win = is_five(board, r, c, me)
        print(f"#{move_no} AI -> {label(r, c)}  {info}")
        self._send(200, json.dumps({"row": r, "col": c, "win": win, "info": info}),
                   "application/json")

    def _record(self, req):
        """每局结束追加一行到 games.jsonl：时间、执子、胜方、总手数、棋谱。"""
        rec = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "human": "black" if req["human"] == BLACK else "white",
            "winner": req["winner"],
            "total_moves": len(req["moves"]),
            "level": req.get("level", JEV_MODE),
            "jev_calls": req.get("jev_calls", 0),
            "ai_moves": req.get("ai_moves", 0),
            "view": JEV_VIEW,
            "jev_mistakes": req.get("mistakes", []),
            "moves": req["moves"],
        }
        with open(Path(__file__).parent / "games.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"对局结束: 胜方={rec['winner']} 共 {rec['total_moves']} 手 "
              f"[{rec['level']}] Jev 调用 {rec['jev_calls']}/{rec['ai_moves']} 步 "
              f"Jev 失误 {len(rec['jev_mistakes'])} 次  {' '.join(rec['moves'])}")
        self._send(200, "{}", "application/json")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    if not os.environ.get("TYPESAFE_API_KEY"):
        mode = "本地启发式（未设置 TYPESAFE_API_KEY）"
    else:
        mode = "Jev 已接入"
    mode += f"；页面默认等级 {LEVELS[JEV_MODE]}"
    print(f"五子棋已启动: http://localhost:{PORT}   AI 模式: {mode}   棋盘表示: {JEV_VIEW}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
