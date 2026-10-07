from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from ..engine.ucci import EngineNotAvailable, UCCIEngine
from ..game import GameSession, IllegalMoveError
from ..library.records import RecordError, summarize
from ..library.store import GameStore, RecordNotFound, StoreError
from .schemas import (
    GameRecord,
    GameSummary,
    GotoRequest,
    LoadedGameResponse,
    MoveRequest,
    MoveResultResponse,
    NewGameRequest,
    NoteRequest,
    NoteResponse,
    OpenRequest,
    PositionResponse,
    RenameRequest,
    SaveAsRequest,
    StepRequest,
)

router = APIRouter()

_DEFAULT_ENGINE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "engine", "pikafish",
)
ENGINE_PATH = os.environ.get("ENGINE_PATH", _DEFAULT_ENGINE_PATH)

_DEFAULT_GAMES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data", "games",
)
GAMES_DIR = os.environ.get("GAMES_DIR", _DEFAULT_GAMES_DIR)

_engine = UCCIEngine(ENGINE_PATH)
_store = GameStore(GAMES_DIR)
_session = GameSession(_engine, _store)


def _ensure_engine() -> None:
    if not _engine.is_running():
        try:
            _engine.start()
        except EngineNotAvailable as e:
            raise HTTPException(
                status_code=503,
                detail=f"引擎不可用（Engine not available）: {e}. "
                        f"请运行 scripts/setup_engine.sh 下载 Pikafish，或设置环境变量 ENGINE_PATH。",
            ) from e


def start_engine_quietly() -> None:
    """Called from the app lifespan. The server is allowed to come up without
    an engine; individual endpoints then answer 503 with setup instructions."""
    try:
        _ensure_engine()
    except HTTPException:
        pass


def shutdown_engine() -> None:
    _engine.stop()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "engine_running": _engine.is_running(), "engine_path": ENGINE_PATH}


@router.post("/game/new", response_model=PositionResponse)
def new_game(req: NewGameRequest) -> dict:
    _ensure_engine()
    _session.new_game(req.fen)
    return _session.position_payload()


@router.get("/game/position", response_model=PositionResponse)
def get_position() -> dict:
    _ensure_engine()
    return _session.position_payload()


@router.post("/game/move", response_model=MoveResultResponse)
def make_move(req: MoveRequest) -> dict:
    _ensure_engine()
    try:
        return _session.make_move(req.from_sq, req.to_sq)
    except IllegalMoveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/game/engine_move", response_model=MoveResultResponse)
def engine_move() -> dict:
    _ensure_engine()
    try:
        return _session.engine_move()
    except IllegalMoveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/game/undo", response_model=PositionResponse)
def undo_move(req: StepRequest | None = None) -> dict:
    """悔棋：回退 plies 步（默认一步）。"""
    _ensure_engine()
    try:
        return _session.undo((req or StepRequest()).plies)
    except IllegalMoveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/game/redo", response_model=PositionResponse)
def redo_move(req: StepRequest | None = None) -> dict:
    """重做：恢复被悔掉的 plies 步（默认一步）。"""
    _ensure_engine()
    try:
        return _session.redo((req or StepRequest()).plies)
    except IllegalMoveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/game/goto", response_model=PositionResponse)
def goto_ply(req: GotoRequest) -> dict:
    """跳转到走子历史中的第 ply 步（0 = 起始局面）。"""
    _ensure_engine()
    try:
        return _session.goto(req.ply)
    except IllegalMoveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ---------------------------------------------------------------------------
# 对局库：browsing, renaming, deleting, exporting, opening and importing must
# all work with the engine down, so none of these calls `_ensure_engine()`.
# ---------------------------------------------------------------------------


def _load_record(game_id: str) -> GameRecord:
    """Fetch a saved game, mapping store failures onto HTTP. A game that is
    not in the library is a 404; a bad id or an unreadable file is a 400."""
    try:
        return _store.load(game_id)
    except RecordNotFound as e:  # a StoreError subclass — must come first
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (RecordError, StoreError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/games", response_model=list[GameSummary])
def list_games() -> list[GameSummary]:
    """对局库列表，newest first. One unreadable file is skipped, not fatal."""
    return _store.list()


@router.post("/games/import", response_model=LoadedGameResponse)
def import_game(body: dict) -> dict:
    """导入复盘：the body is the raw 对局文件 object. It is validated by
    `GameRecord.parse` rather than by a request model, so every structural
    rule lives in one place and none of them can be skipped on the way in."""
    try:
        record = GameRecord.parse(body)
        return {**_session.import_record(record), "plies": _session._line_plies()}
    except (RecordError, StoreError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/games/{game_id}", response_model=GameRecord)
def get_game(game_id: str) -> GameRecord:
    """读取一局对局的完整文件（用于导出）。"""
    return _load_record(game_id)


@router.patch("/games/{game_id}", response_model=GameSummary)
def rename_game(game_id: str, req: RenameRequest) -> GameSummary:
    """重命名一局对局。Store-level: renaming a game that is not the one
    currently open must work, and must not disturb the open game."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="名字不能为空")
    if len(name) > 80:
        raise HTTPException(status_code=400, detail="名字太长了")
    # Under the session lock: DELETE holds it for the same reason, so an
    # auto-save of the open game cannot interleave with this load-modify-save
    # and resurrect the old name.
    with _session.lock:
        record = _load_record(game_id)
        record.name = name
        try:
            saved = _store.save(record)
        except StoreError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        _session.sync_renamed_record(game_id, name)
    return summarize(saved)


@router.delete("/games/{game_id}")
def delete_game(game_id: str) -> dict:
    """删除一局对局。The open game is protected: the session auto-saves into
    its file, so deleting it would silently drop the game in progress."""
    with _session.lock:
        if game_id == _session.record_id:
            raise HTTPException(status_code=409, detail="这是当前对局，请先开新对局")
        try:
            _store.delete(game_id)
        except StoreError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    return {"deleted": game_id}


@router.post("/game/save_as", response_model=PositionResponse)
def save_as(req: SaveAsRequest) -> dict:
    """另存为：copy the current line into a fresh library entry."""
    # The same name rule as PATCH: a whitespace-only name must never become
    # the live `game_name` (save_as sets it directly).
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="名字不能为空")
    if len(name) > 80:
        raise HTTPException(status_code=400, detail="名字太长了")
    try:
        return _session.save_as(name)
    except IllegalMoveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/game/open", response_model=LoadedGameResponse)
def open_game(req: OpenRequest) -> dict:
    """打开对局：replay a saved game into the live session. Unlike the other
    /game endpoints this still works without the engine — the whole line is
    replayed from board rules alone."""
    try:
        return {**_session.open_record(req.id), "plies": _session._line_plies()}
    except RecordNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (RecordError, StoreError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/game/note", response_model=NoteResponse)
def set_note(req: NoteRequest) -> dict:
    """写笔记：第 ply 步（1 起，按整条线路数，含重做分支）或整局（ply 为 null）。"""
    try:
        return _session.set_note(req.ply, req.text)
    except IllegalMoveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
