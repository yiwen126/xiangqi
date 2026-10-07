"""Client for talking to a local Pikafish engine process.

Note: despite the module name (kept for continuity with the "UCCI" terminology
common in Xiangqi tooling), Pikafish is actually a Stockfish-derived engine and
speaks the standard **UCI** protocol adapted for Xiangqi FEN — `uci`/`uciok`,
`isready`/`readyok`, `position fen ...`, `go depth N`, `setoption name MultiPV
value N`, `info ... multipv N score cp X pv ...`, `bestmove ...`. This client
implements that protocol.
"""
from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass, field


class EngineNotAvailable(RuntimeError):
    pass


@dataclass
class PvLine:
    multipv: int
    score_cp: int | None
    score_mate: int | None
    pv: list[str] = field(default_factory=list)

    @property
    def best_move(self) -> str | None:
        return self.pv[0] if self.pv else None


class UCCIEngine:
    def __init__(self, path: str, timeout: float = 15.0):
        self.path = path
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None
        # Re-entrant so a locked helper can be called from an already-locked
        # section (analyze -> _set_multipv_locked) without deadlocking.
        self._lock = threading.RLock()
        self._multipv: int | None = None

    def start(self) -> None:
        try:
            self._proc = subprocess.Popen(
                [self.path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                # run with cwd = the engine binary's own directory so it finds
                # pikafish.nnue via its default relative EvalFile option
                cwd=os.path.dirname(os.path.abspath(self.path)) or None,
            )
        except (FileNotFoundError, PermissionError, OSError) as e:
            raise EngineNotAvailable(f"cannot start engine at {self.path}: {e}") from e
        self._multipv = None  # fresh process is back to the engine's default
        self._send("uci")
        self._read_until(lambda l: l.strip() == "uciok")
        self._send("isready")
        self._read_until(lambda l: l.strip() == "readyok")

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            self._send("quit")
            self._proc.wait(timeout=3)
        except Exception:
            self._proc.kill()
        self._proc = None

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _send(self, cmd: str) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise EngineNotAvailable("engine process is not running")
        self._proc.stdin.write(cmd + "\n")
        self._proc.stdin.flush()

    def _read_until(self, predicate, collect: list[str] | None = None) -> str:
        if self._proc is None or self._proc.stdout is None:
            raise EngineNotAvailable("engine process is not running")
        while True:
            line = self._proc.stdout.readline()
            if line == "":
                raise EngineNotAvailable("engine process exited unexpectedly")
            line = line.rstrip("\n")
            if collect is not None:
                collect.append(line)
            if predicate(line):
                return line

    def _set_multipv_locked(self, n: int) -> None:
        """Caller must already hold self._lock."""
        if n == self._multipv:
            return
        self._send(f"setoption name MultiPV value {n}")
        self._send("isready")
        self._read_until(lambda l: l.strip() == "readyok")
        self._multipv = n

    def set_multipv(self, n: int) -> None:
        with self._lock:
            self._set_multipv_locked(n)

    def new_game(self) -> None:
        with self._lock:
            self._send("ucinewgame")
            self._send("isready")
            self._read_until(lambda l: l.strip() == "readyok")

    def analyze(
        self,
        fen: str,
        moves: list[str] | None = None,
        depth: int = 14,
        movetime_ms: int | None = None,
        multipv: int = 3,
    ) -> list[PvLine]:
        """Run a search and return PV lines sorted by multipv index (1 = best).

        The whole exchange is held under one lock: setting MultiPV, sending the
        position and reading back to `bestmove` must not interleave with another
        thread's search on a single shared engine process.
        """
        with self._lock:
            self._set_multipv_locked(multipv)
            pos_cmd = f"position fen {fen}"
            if moves:
                pos_cmd += " moves " + " ".join(moves)
            self._send(pos_cmd)
            if movetime_ms:
                self._send(f"go movetime {movetime_ms}")
            else:
                self._send(f"go depth {depth}")

            lines: dict[int, PvLine] = {}
            raw: list[str] = []
            self._read_until(lambda l: l.startswith("bestmove"), collect=raw)

        best_move = None
        for line in raw:
            if line.startswith("bestmove"):
                parts = line.split()
                if len(parts) >= 2 and parts[1] != "(none)":
                    best_move = parts[1]
                continue
            if not line.startswith("info"):
                continue
            tokens = line.split()
            if "multipv" not in tokens or "pv" not in tokens:
                continue
            mpv_idx = int(tokens[tokens.index("multipv") + 1])
            score_cp = None
            score_mate = None
            if "score" in tokens:
                si = tokens.index("score")
                kind = tokens[si + 1]
                val = int(tokens[si + 2])
                if kind == "cp":
                    score_cp = val
                elif kind == "mate":
                    score_mate = val
            pv_idx = tokens.index("pv")
            pv = tokens[pv_idx + 1:]
            lines[mpv_idx] = PvLine(multipv=mpv_idx, score_cp=score_cp, score_mate=score_mate, pv=pv)

        result = [lines[k] for k in sorted(lines.keys())]
        if not result and best_move:
            result = [PvLine(multipv=1, score_cp=0, score_mate=None, pv=[best_move])]
        return result
