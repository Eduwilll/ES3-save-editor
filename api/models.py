import datetime
from sqlalchemy import ForeignKey, String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


class GamePassword(Base):
    __tablename__ = "game_passwords"

    game_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    passwords: Mapped[list["Password"]] = relationship(back_populates="game", cascade="all, delete-orphan")

class Password(Base):
    __tablename__ = "passwords"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    parent_game_id: Mapped[int] = mapped_column(ForeignKey("game_passwords.game_id"))
    game: Mapped["GamePassword"] = relationship(back_populates="passwords")
    password: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    
