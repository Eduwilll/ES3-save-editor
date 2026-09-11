import datetime

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine, migrate_sqlite_schema
from .models import GamePassword, Password

Base.metadata.create_all(bind=engine)
migrate_sqlite_schema()

app = FastAPI(title="ES3 Save Editor API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5500", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -------------------------
# Models
# -------------------------
class Game(BaseModel):
    id: int
    steam_info: GameSteamInfo | None = None


class GameSteamInfo(BaseModel):
    name: str
    tiny_image: str | None = None
    price_overview: dict | None = None


class GameSearchResponse(BaseModel):
    total: int
    games: list[Game]


class GameES3Password(BaseModel):
    game_id: int
    password: str
    created_at: datetime.datetime | None = None


class PasswordRequest(BaseModel):
    password: str
    created_at: datetime.datetime | None = None


# -------------------------
# Steam
# -------------------------

@app.get("/games", response_model=GameSearchResponse)
async def search_games(
    search: str = Query(..., min_length=1),
):
    url = "https://store.steampowered.com/api/storesearch/"

    params = {
        "term": search,
        "l": "english",
        "cc": "us",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, params=params)

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail="Error consulting Steam",
        )

    data = response.json()

    games = []

    for game in data.get("items", []):
        steam_info = GameSteamInfo(
            name=game["name"],
            tiny_image=game.get("tiny_image"),
            price_overview=game.get("price"),
        )

        games.append(
            Game(
                id=game["id"],
                steam_info=steam_info,
            )
        )

    return GameSearchResponse(
        total=data.get("total", 0),
        games=games,
    )


# -------------------------
# Password
# -------------------------

@app.put(
    "/games/{game_id}/password",
    response_model=GameES3Password,
)
async def set_game_password(
    game_id: int,
    request: PasswordRequest,
    db: Session = Depends(get_db),
):
    saved_password = db.get(GamePassword, game_id)
    new_password = Password(password=request.password, created_at=request.created_at or datetime.datetime.utcnow())
    if saved_password is None:
        saved_password = GamePassword(
            game_id=game_id,
            passwords=[new_password]
        )
        db.add(saved_password)
    else:
        saved_password.passwords.append(new_password)
    db.commit()

    return GameES3Password(
        game_id=game_id,
        password=request.password,
    )


@app.get(
    "/games/{game_id}/password",
    response_model=list[GameES3Password],
)
async def get_game_password(game_id: int, db: Session = Depends(get_db)):
    saved_password = db.get(GamePassword, game_id)

    if saved_password is None:
        raise HTTPException(
            status_code=404,
            detail="Password not found for this game",
        )

    return [
        GameES3Password(
            game_id=game_id,
            password=p.password,
            created_at=p.created_at,

        )
        for p in saved_password.passwords
    ]