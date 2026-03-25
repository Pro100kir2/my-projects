# hintsage_mac.py — Secure Messenger backend (часть 1 — ~450 строк)

import json
import logging
import os
import secrets
import shutil
import time
import uuid
from base64 import urlsafe_b64encode
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, AsyncGenerator, Dict, List, Optional
from urllib import request
from uuid import uuid4

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from dotenv import load_dotenv
from fastapi import (
    Body,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
    Form
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from jwt import ExpiredSignatureError, InvalidTokenError
from jwt import decode as jwt_decode
from pwdlib import PasswordHash
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    delete,
    func,
    or_,
    select,
    update,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

load_dotenv()

# ────────────────────────────────────────────────
# Временное хранилище путей файлов импорта
# ────────────────────────────────────────────────
import_file_paths = {}

# ────────────────────────────────────────────────
# Конфигурация
# ────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://admin:1bbCrExkYrhtIOOO01ORzQ@localhost/messenger",
)
JWT_SECRET = os.getenv("JWT_SECRET", "v9NPSbrGa!MTmVYIUleN_dTL+frX5BKg1mpkW9ag-M419o")
# Уникальный ключ сервера только для служебных данных (email, etc.)
SERVER_ENCRYPTION_KEY = urlsafe_b64encode(
    os.getenv("SERVER_ENCRYPTION_KEY", "qEDPUx1hDeNRuRXvwOLCT-jLsslx6wHxyrw3PY7pLGA").encode()[
        :32
    ]
)
# Для пользовательских сообщений будем использовать индивидуальные ключи
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 14

ADMIN_TAG = "@admin"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "nrurQgllQWDcHLNXymdzlg!")
ADMIN_PHONE = "89776985620"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

AVATAR_DIR = "static/avatars"

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
os.makedirs(AVATAR_DIR, exist_ok=True)

# Создаем папку для аватарок, если она не существует
os.makedirs(AVATAR_DIR, exist_ok=True)

pwd_hasher = PasswordHash.recommended()
server_fernet = Fernet(SERVER_ENCRYPTION_KEY)
# Для пользовательских сообщений ключи будут генерироваться индивидуально

# ────────────────────────────────────────────────
# Общие регулярки и фильтр нецензурной лексики
# ────────────────────────────────────────────────
import re

NAME_REGEX = re.compile(r"^[A-Za-zА-Яа-яЁё0-9]+$")
TAG_CORE_REGEX = re.compile(r"^[A-Za-zА-Яа-яЁё0-9_]+$")
PHONE_REGEX = re.compile(r"^\+?[0-9\s\-()]{7,20}$")

BAD_WORDS = [
    "хуй",
    "хуе",
    "хуя",
    "пизд",
    "еба",
    "ебл",
    "бля",
    "сука",
    "мраз",
    "говн",
    "дерьм",
    "нигер",
    "пидр",
    "fuck",
    "shit",
    "bitch",
    "dick",
    "cunt",
    "asshole",
    "niger",
]


def contains_bad_words(text: str) -> bool:
    lower = text.lower()
    return any(w in lower for w in BAD_WORDS)


# Асинхронный движок и сессия
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

logging.basicConfig(level=logging.INFO)

# Rate limiting: Redis if configured, else in-memory
from collections import defaultdict

RATE_LIMIT = 120
RATE_PERIOD = 60
LOGIN_FAIL_MAX = 5
LOGIN_FAIL_WINDOW = 900  # 15 min in seconds

user_requests = defaultdict(list)
_redis_client: Optional[Any] = None


async def get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if REDIS_URL:
        try:
            from redis.asyncio import Redis

            _redis_client = Redis.from_url(REDIS_URL, decode_responses=True)
            await _redis_client.ping()
            return _redis_client
        except Exception as e:
            logging.warning("Redis unavailable, using in-memory rate limit: %s", e)
    return None


async def check_rate(user_id: Any):
    redis = await get_redis()
    if redis:
        key = f"rate:{user_id}"
        now = time.time()

        pipe = redis.pipeline()
        pipe.zadd(key, {str(now): now})
        pipe.zremrangebyscore(key, 0, now - RATE_PERIOD)
        pipe.zcard(key)
        pipe.expire(key, RATE_PERIOD + 10)

        results = await pipe.execute()
        count = results[2]

        if count > RATE_LIMIT:
            raise HTTPException(status_code=429, detail="Too many requests")
        return

    # fallback без Redis
    now = time.time()
    uid = str(user_id)
    reqs = [t for t in user_requests.get(uid, []) if now - t < RATE_PERIOD]

    if len(reqs) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many requests")

    user_requests[uid] = reqs + [now]


async def check_login_bruteforce(identifier: str) -> None:
    """Raise 429 if too many failed logins for this identifier."""
    redis = await get_redis()
    if not redis:
        return
    key = f"login_fail:{identifier}"
    n = await redis.get(key)
    if n and int(n) >= LOGIN_FAIL_MAX:
        ttl = await redis.ttl(key)
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {max(1, ttl)} seconds.",
        )


async def record_login_failure(identifier: str) -> None:
    redis = await get_redis()
    if redis:
        key = f"login_fail:{identifier}"
        await redis.incr(key)
        await redis.expire(key, LOGIN_FAIL_WINDOW)
    return


async def clear_login_failures(identifier: str) -> None:
    redis = await get_redis()
    if redis:
        await redis.delete(f"login_fail:{identifier}")


# ────────────────────────────────────────────────
# SQLAlchemy модели (ORM)
# ────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tag_name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone_hash: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, nullable=True
    )
    email_enc: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, nullable=True
    )
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verification_token: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_seen: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_messages_only_from_friends: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    banned_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    online_visibility: Mapped[str] = mapped_column(
        String(20), default="all", nullable=False
    )  # all | nobody | friends_only
    allow_calls_from: Mapped[str] = mapped_column(
        String(10), default="all", nullable=False
    )  # all | friends

    devices = relationship("Device", back_populates="user")
    sent_messages = relationship(
        "Message", foreign_keys="[Message.from_id]", back_populates="from_user"
    )
    received_messages = relationship(
        "Message", foreign_keys="[Message.to_id]", back_populates="to_user"
    )
    sent_requests = relationship(
        "FriendRequest",
        foreign_keys="[FriendRequest.from_id]",
        back_populates="from_user",
    )
    received_requests = relationship(
        "FriendRequest", foreign_keys="[FriendRequest.to_id]", back_populates="to_user"
    )
    friends = relationship(
        "Friend", foreign_keys="[Friend.user_id]", back_populates="user"
    )
    groups_owned = relationship("Group", back_populates="owner")
    group_memberships = relationship("GroupMember", back_populates="user")
    channels_owned = relationship("Channel", back_populates="owner")
    avatars = relationship(
        "UserAvatar", back_populates="user", order_by="UserAvatar.created_at.desc()"
    )
    device_notifications = relationship(
        "DeviceConfirmationNotification",
        back_populates="user",
        cascade="all, delete-orphan"
    )


class UserAvatar(Base):
    __tablename__ = "user_avatars"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    avatar_url: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user = relationship("User", back_populates="avatars")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    device_name: Mapped[str] = mapped_column(String(100), default="Unknown Device")
    device_fingerprint: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    public_key_x25519: Mapped[str] = mapped_column(Text)
    # Зашифрованные ключи для кросс-устройственной синхронизации
    encrypted_keys: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Статус подтверждения устройства
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmation_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    confirmation_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Время активности
    last_active: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    user = relationship("User", back_populates="devices")


class DeviceConfirmationNotification(Base):
    __tablename__ = "device_confirmation_notifications"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    device_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    confirmation_token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=datetime.now(timezone.utc))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="device_notifications")


class SystemNotification(Base):
    __tablename__ = "system_notifications"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))  # 'active' | 'system'
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON с доп данными
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user = relationship("User")


class TelegramImportRequest(Base):
    __tablename__ = "telegram_import_requests"

    id: Mapped[str] = mapped_column(String(255), primary_key=True, default=lambda: str(uuid.uuid4()))
    requester_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    target_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    telegram_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    total_messages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    processed_messages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    imported_messages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=datetime.now(timezone.utc),
                                                 onupdate=datetime.now(timezone.utc))

    requester = relationship("User", foreign_keys=[requester_id])
    target_user = relationship("User", foreign_keys=[target_user_id])


class FriendRequest(Base):
    __tablename__ = "friend_requests"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    from_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    to_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending / accepted / rejected
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    from_user = relationship(
        "User", foreign_keys=[from_id], back_populates="sent_requests"
    )
    to_user = relationship(
        "User", foreign_keys=[to_id], back_populates="received_requests"
    )

    __table_args__ = (
        UniqueConstraint("from_id", "to_id", name="unique_friend_request"),
    )


class Friend(Base):
    __tablename__ = "friends"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    friend_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user = relationship("User", foreign_keys=[user_id], back_populates="friends")

    __table_args__ = (
        UniqueConstraint("user_id", "friend_id", name="unique_friendship"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    from_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    to_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("groups.id"), nullable=True
    )
    encrypted_content: Mapped[str] = mapped_column(Text)
    encrypted_session_keys: Mapped[str] = mapped_column(Text)
    nonce: Mapped[str] = mapped_column(String(24))
    version: Mapped[str] = mapped_column(String(8), default="v1")
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_attempted: Mapped[bool] = mapped_column(default=False)

    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    edited_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    pinned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    suspicious: Mapped[bool] = mapped_column(Boolean, default=False)
    suspicious_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suspicious_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    attachment_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    attachment_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Server-side encrypted plaintext (Fernet) for cross-device fallback
    plain_content_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Reply & forward support
    reply_to_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("messages.id"), nullable=True
    )
    forward_from_tag: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    from_user = relationship(
        "User", foreign_keys=[from_id], back_populates="sent_messages"
    )
    to_user = relationship(
        "User", foreign_keys=[to_id], back_populates="received_messages"
    )
    reactions = relationship(
        "MessageReaction", back_populates="message", cascade="all, delete-orphan"
    )
    __table_args__ = (
        Index("ix_messages_conversation", "from_id", "to_id", "timestamp"),
        Index("ix_messages_group", "group_id", "timestamp"),
    )


class MessageReaction(Base):
    __tablename__ = "message_reactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    user_tag: Mapped[str] = mapped_column(String(50))
    emoji: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    message = relationship("Message", back_populates="reactions")
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", "emoji", name="unique_reaction"),
    )


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    owner = relationship("User", back_populates="groups_owned")
    members = relationship("GroupMember", back_populates="group")


class GroupMember(Base):
    __tablename__ = "group_members"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    group = relationship("Group", back_populates="members")
    user = relationship("User", back_populates="group_memberships")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    from_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reported_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    screenshot_urls: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    reasons: Mapped[str] = mapped_column(Text, default="[]")  # JSON array of reasons
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | banned | declined | clarify
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    from_user = relationship("User", foreign_keys=[from_user_id])
    reported_user = relationship("User", foreign_keys=[reported_user_id])


class UserPinnedMessage(Base):
    """Per-user pinned messages (visible only to the user who pinned)."""

    __tablename__ = "user_pinned_messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    pinned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="unique_user_pinned"),
    )


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    owner = relationship("User", back_populates="channels_owned")


# ────────────────────────────────────────────────
# Зависимость для сессии БД
# ────────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)

    # Migrations: add columns that may not exist in older deployments
    migrations = [
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS attachment_url VARCHAR(500)",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS attachment_type VARCHAR(20)",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS edited_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN DEFAULT FALSE",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_id INTEGER REFERENCES messages(id)",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS forward_from_tag VARCHAR(50)",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS plain_content_enc TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS banned_until TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS online_visibility VARCHAR(20) DEFAULT 'all'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS allow_calls_from VARCHAR(10) DEFAULT 'all'",
        "ALTER TABLE reports ADD COLUMN IF NOT EXISTS reasons TEXT DEFAULT '[]'",
        "ALTER TABLE reports ADD COLUMN IF NOT EXISTS is_urgent BOOLEAN DEFAULT FALSE",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS encrypted_keys TEXT",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS device_name VARCHAR(100) DEFAULT 'Unknown Device'",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS device_fingerprint VARCHAR(255) UNIQUE",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS is_confirmed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS confirmation_token VARCHAR(255)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS confirmation_requested_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMP WITH TIME ZONE",
        """CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
            from_user_id UUID NOT NULL REFERENCES users(id),
            reported_user_id UUID NOT NULL REFERENCES users(id),
            text TEXT NOT NULL,
            screenshot_urls TEXT DEFAULT '[]',
            reasons TEXT DEFAULT '[]',
            is_urgent BOOLEAN DEFAULT FALSE,
            status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            resolved_at TIMESTAMP WITH TIME ZONE
        )""",
        """CREATE TABLE IF NOT EXISTS user_pinned_messages (
            id SERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id),
            message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            pinned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            CONSTRAINT unique_user_pinned UNIQUE (user_id, message_id)
        )""",
        """CREATE TABLE IF NOT EXISTS device_confirmation_notifications (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            device_id UUID NOT NULL REFERENCES devices(id),
            device_name VARCHAR(100) NOT NULL,
            device_fingerprint VARCHAR(255) NOT NULL,
            confirmation_token VARCHAR(255) UNIQUE NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            resolved_at TIMESTAMP WITH TIME ZONE
        )""",
        # Обновление plain_content_enc для старых импортированных сообщений
        """
        UPDATE messages 
        SET plain_content_enc = CASE 
            WHEN version = 'imported' AND plain_content_enc IS NULL AND encrypted_content != 'imported_message_fallback'
            THEN (
                CASE 
                    WHEN encrypted_content LIKE 'g%' THEN encrypted_content  -- Если уже выглядит как Fernet
                    ELSE NULL  -- Иначе оставляем NULL, будет обработано ниже
                END
            )
            ELSE plain_content_enc
        END
        WHERE version = 'imported' AND plain_content_enc IS NULL
        """,
    ]
    for sql in migrations:
        try:
            async with engine.begin() as conn:
                await conn.execute(sa_text(sql))
        except Exception as e:
            logging.warning(f"Migration warning (non-fatal): {e}")

    # Ensure uploads directory exists
    os.makedirs("static/uploads", exist_ok=True)
    os.makedirs("static/reports", exist_ok=True)

    # Создаём дефолтного администратора если его нет
    async with async_session() as session:
        result = await session.execute(select(User).where(User.tag_name == "@admin"))
        admin = result.scalars().first()

        if not admin:
            logging.info("Creating default admin user...")

            password_hash = pwd_hasher.hash("admin123456")

            admin_user = User(
                tag_name="@admin",
                name="Admin",
                phone_hash=pwd_hasher.hash("0000000000"),
                email_enc=server_fernet.encrypt(b"admin@example.com").decode(),
                email_verified=True,
                password_hash=password_hash,
                created_at=datetime.now(timezone.utc),
            )

            session.add(admin_user)
            await session.commit()
            await session.refresh(admin_user)

            # Создаём устройство для админа
            device = Device(
                user_id=admin_user.id,
                public_key_x25519="admin-public-key",
                device_name="Admin Device",
                device_fingerprint="admin_default_device",
                is_confirmed=True,
                confirmed_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                last_active=datetime.now(timezone.utc),
            )

            session.add(device)
            await session.commit()

            logging.info("Default admin created: @admin / admin123456")
        else:
            logging.info("Admin already exists")


# ────────────────────────────────────────────────
# Pydantic схемы (модели для валидации)
# ────────────────────────────────────────────────
class UserRegister(BaseModel):
    name: str
    tag_name: str
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    password: str

    # серверная валидация имени / тега / телефона

    @field_validator("name")
    def validate_name(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("Имя обязательно")
        if not NAME_REGEX.match(value):
            raise ValueError(
                "Имя может содержать только буквы и цифры без пробелов и спецсимволов"
            )
        if contains_bad_words(value):
            raise ValueError("Имя содержит запрещённые слова")
        return value

    @field_validator("tag_name")
    def validate_tag(cls, v: str) -> str:
        raw = v.strip()
        if not raw:
            raise ValueError("Tag обязателен")
        core = raw.lstrip("@")
        if not TAG_CORE_REGEX.match(core):
            raise ValueError("Tag может содержать только буквы, цифры и символ _")
        if contains_bad_words(core):
            raise ValueError("Tag содержит запрещённые слова")
        # Первая буква всегда заглавная
        core = core[0].upper() + core[1:]
        return f"@{core}"

    @field_validator("phone")
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        if not value:
            return None
        if not PHONE_REGEX.match(value):
            raise ValueError("Введите корректный номер телефона")
        return value

    @field_validator("password")
    def strong_password(cls, v: str):
        if len(v) < 12:
            raise ValueError("Пароль слишком короткий (минимум 12 символов)")
        return v


class UserOut(BaseModel):
    id: str
    tag_name: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None


class SearchUserOut(BaseModel):
    id: str
    tag_name: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_friend: bool = False
    pending_request_sent: bool = False
    pending_request_received: bool = False


class AvatarOut(BaseModel):
    id: int
    avatar_url: str
    created_at: datetime
    is_active: bool


class ProfileOut(BaseModel):
    id: str
    tag_name: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    avatars: List[AvatarOut] = []
    email: Optional[str] = None
    phone: Optional[str] = None
    is_online: bool = False
    last_seen: Optional[datetime] = None
    is_friend: bool = False
    pending_request_sent: bool = False
    pending_request_received: bool = False


class FriendRequestOut(BaseModel):
    id: int
    from_id: str
    from_tag: str
    from_name: Optional[str] = None


class DeviceOut(BaseModel):
    id: str
    device_name: str
    device_fingerprint: str
    public_key_x25519: str
    is_confirmed: bool
    last_active: datetime
    created_at: datetime


class DeviceConfirmationNotificationOut(BaseModel):
    id: int
    device_id: str
    device_name: str
    device_fingerprint: str
    confirmation_token: str
    status: str
    created_at: datetime


class DeviceRegisterRequest(BaseModel):
    device_name: str
    device_fingerprint: str
    public_key_x25519: str


class LoginRequest(BaseModel):
    username: str
    password: str
    device_fingerprint: Optional[str] = None
    device_name: Optional[str] = None
    public_key_x25519: Optional[str] = None


class DeviceConfirmationRequest(BaseModel):
    confirmation_token: str
    action: str  # approve / reject


class TelegramImportRequestForm(BaseModel):
    chat_id: str
    telegram_name: str
    html_file: UploadFile


class SystemNotificationOut(BaseModel):
    id: int
    type: str
    title: str
    message: str
    data: Optional[str] = None
    is_read: bool
    created_at: datetime
    expires_at: Optional[datetime] = None


class DeviceRenameRequest(BaseModel):
    device_name: str


class TelegramImportProgress(BaseModel):
    import_id: str
    status: str  # pending, processing, completed, failed
    total: int
    processed: int
    percentage: float
    imported: Optional[int] = None
    chat_id: Optional[str] = None
    error: Optional[str] = None


class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: Optional[str] = None


class MessageSend(BaseModel):
    to_tag: Optional[str] = None
    group_id: Optional[int] = None
    encrypted_content: str
    encrypted_session_keys: Dict[str, str]
    nonce: str
    version: str = "v1"
    client_risk_score: Optional[float] = None
    client_risk_reason_code: Optional[str] = None
    attachment_url: Optional[str] = None
    attachment_type: Optional[str] = None
    reply_to_id: Optional[int] = None
    forward_from_tag: Optional[str] = None
    plain_content: Optional[str] = None  # plaintext for server-side fallback


class MessageOut(BaseModel):
    id: int
    from_tag: str
    to_tag: Optional[str]
    group_id: Optional[str]
    encrypted_content: str
    encrypted_session_keys: Dict[str, str]
    nonce: str
    version: str
    timestamp: datetime
    delivered: bool
    edited_at: Optional[datetime] = None
    edited_nonce: Optional[str] = None
    suspicious: bool = False
    suspicious_reason: Optional[str] = None
    suspicious_score: float = 0.0
    attachment_url: Optional[str] = None
    attachment_type: Optional[str] = None
    reply_to_id: Optional[int] = None
    reply_to_from_tag: Optional[str] = None
    forward_from_tag: Optional[str] = None
    # Server-side plaintext fallback (for multi-device)
    plain_content_enc: Optional[str] = None
    reactions: Optional[Dict[str, List[str]]] = None
    # Reply / forward encrypted content
    reply_to_encrypted_content: Optional[str] = None
    reply_to_encrypted_session_keys: Optional[Dict[str, str]] = None
    reply_to_nonce: Optional[str] = None


class ConversationOut(BaseModel):
    id: str
    tag_name: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    last_message_encrypted: Optional[str] = None
    last_message_encrypted_session_keys: Optional[Dict[str, str]] = None
    last_message_nonce: Optional[str] = None
    last_message_plain: Optional[str] = None
    last_message_at: Optional[datetime] = None
    last_message_from_me: bool = False
    unread_count: int = 0
    last_delivered: bool = False
    last_read_at: Optional[datetime] = None


class FriendRequestCreate(BaseModel):
    to_tag: str


class GroupCreate(BaseModel):
    name: str


class ChannelCreate(BaseModel):
    name: str


# hintsage_mac.py — часть 2 (продолжение после Channel)


# ────────────────────────────────────────────────
# JWT и аутентификация
# ────────────────────────────────────────────────
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
            expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(user_id: UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {
        "sub": str(user_id),  # <-- важное изменение
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)


async def get_current_user(
        token: Annotated[str, Depends(oauth2_scheme)], db: AsyncSession = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        user_id_raw = payload.get("sub")
        if user_id_raw is None:
            raise credentials_exception
        # Проверяем, что это не refresh-токен
        if payload.get("type") == "refresh":
            raise credentials_exception
        user_id = (
            uuid.UUID(user_id_raw) if isinstance(user_id_raw, str) else user_id_raw
        )
    except (JWTError, ValueError, TypeError):
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if user is None:
        raise credentials_exception
    # Ban check
    if user.banned_until and user.banned_until > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=403,
            detail=f"Аккаунт заблокирован до {user.banned_until.strftime('%d.%m.%Y %H:%M')} UTC",
        )
    return user


def generate_x25519_keypair():
    # Генерация приватного ключа
    private_key = x25519.X25519PrivateKey.generate()
    # Получаем публичный ключ
    public_key = private_key.public_key()

    # Сериализация в строку (PEM/bytes)
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )

    # Возвращаем в base64, чтобы удобно хранить в БД
    import base64

    return base64.b64encode(private_bytes).decode(), base64.b64encode(
        public_bytes
    ).decode()


# ────────────────────────────────────────────────
# WebSocket менеджер (поддержка нескольких устройств)
# ────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[Any, Dict[str, WebSocket]] = {}

    async def connect(self, user_id: Any, device_id: str, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = {}
        self.active_connections[user_id][device_id] = websocket

    def disconnect(self, user_id: Any, device_id: str):
        if user_id in self.active_connections:
            self.active_connections[user_id].pop(device_id, None)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_personal_message(self, user_id: Any, message: dict):
        if user_id in self.active_connections:
            for ws in self.active_connections[user_id].values():
                try:
                    await ws.send_json(message)
                except Exception:
                    pass  # Игнорируем закрытые соединения


async def save_avatar_file(file: UploadFile) -> str:
    if not file.filename:
        raise ValueError("Filename is missing")

    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file extension")

    filename = f"{uuid4()}.{ext}"
    filepath = os.path.join(AVATAR_DIR, filename)

    try:
        await asyncio.to_thread(shutil.copyfileobj, file.file, open(filepath, "wb"))
    finally:
        await file.close()

    return f"/static/avatars/{filename}"  # путь для базы


manager = ConnectionManager()


# ────────────────────────────────────────────────
# Metadata-based risk scoring (no message content access)
# ────────────────────────────────────────────────
async def metadata_risk_score(
        db: AsyncSession, from_id: Any, encrypted_content_len: int
) -> tuple[bool, Optional[str], float]:
    """Returns (suspicious, reason, score) from metadata only."""
    now = datetime.now(timezone.utc)
    one_min_ago = now - timedelta(minutes=1)
    five_min_ago = now - timedelta(minutes=5)

    count_1m = await db.execute(
        select(func.count(Message.id)).where(
            and_(Message.from_id == from_id, Message.timestamp >= one_min_ago)
        )
    )
    count_5m = await db.execute(
        select(func.count(Message.id)).where(
            and_(Message.from_id == from_id, Message.timestamp >= five_min_ago)
        )
    )
    n1 = count_1m.scalar() or 0
    n5 = count_5m.scalar() or 0

    score = 0.0
    reason = None
    if n1 >= 20:
        score = max(score, 0.8)
        reason = "Very high message rate"
    elif n1 >= 10:
        score = max(score, 0.5)
        reason = "High message rate"
    if n5 >= 50:
        score = max(score, 0.6)
        reason = reason or "Burst activity"
    if encrypted_content_len > 100_000:
        score = max(score, 0.4)
        reason = reason or "Very large payload"
    return (score >= 0.5, reason, score)


# ────────────────────────────────────────────────
# Заглушка для банковской верификации (всегда одобрено)
# ────────────────────────────────────────────────
async def verify_bank(phone: str) -> bool:
    # В реальности здесь будет вызов API банка со списанием 1₽
    # Пока всегда True, как просил
    logging.info(f"Bank verification for phone {phone} — approved (stub)")
    return True


# ────────────────────────────────────────────────
# FastAPI приложение
# ────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    print("Database initialized")
    yield
    if _redis_client:
        await _redis_client.close()
        logging.info("Redis connection closed")


app = FastAPI(
    title="Secure Messenger 2026 — with funny AI moderation",
    description="E2EE мессенджер с двойной проверкой (клиент + серверный ИИ-фильтр plaintext)",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://nexochat.online"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Check if user is admin and redirect to admin panel
    token = request.cookies.get("access_token") or request.headers.get("authorization", "").replace("Bearer ", "")
    if token:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
            if payload.get("type") != "refresh":
                user_id = uuid.UUID(payload["sub"]) if isinstance(payload["sub"], str) else payload["sub"]
                async with async_session() as session:
                    result = await session.execute(select(User).where(User.id == user_id))
                    user = result.scalars().first()
                    if user and user.tag_name == ADMIN_TAG:
                        return RedirectResponse(url="/admin-panel", status_code=302)
        except (JWTError, ValueError, TypeError, KeyError):
            pass

    return templates.TemplateResponse(request, "index.html", {"request": request})


@app.get("/invite", response_class=HTMLResponse)
async def invite_page(request: Request):
    """Serve the main app page so the invite link is handled client-side."""
    return templates.TemplateResponse(request, "index.html", {"request": request})


@app.get("/about-nexo", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse(request, "about-nexo.html", {"request": request})


@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/favicon.ico")


@app.get("/auth", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(request, "auth.html", {"request": request})


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    return templates.TemplateResponse(request, "reports.html", {"request": request})


@app.get("/job-aggregator", response_class=HTMLResponse)
async def job_aggregator_page(request: Request):
    return templates.TemplateResponse(request, "job_agregator.html", {"request": request})


@app.get("/music", response_class=HTMLResponse)
async def music_page(request: Request):
    return templates.TemplateResponse(request, "music.html", {"request": request})


# ────────────────────────────────────────────────
# Эндпоинты регистрации и авторизации
# ────────────────────────────────────────────────
def _generate_verification_token() -> str:
    return secrets.token_urlsafe(32)


@app.post("/register", response_model=Token, status_code=201)
async def register(
        name: str = Form(...),
        tag_name: str = Form(...),
        phone: Optional[str] = Form(None),
        email: Optional[str] = Form(None),
        password: str = Form(...),
        device_fingerprint: str = Form(...),
        device_name: str = Form("Default Device"),
        public_key_x25519: str = Form(...),
        db: AsyncSession = Depends(get_db)
):
    # Получаем значения опциональных полей
    phone = phone if phone and phone.strip() else None
    email = email if email and email.strip() else None
    # Валидация данных вручную
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Имя обязательно")
    if not NAME_REGEX.match(name):
        raise HTTPException(status_code=400,
                            detail="Имя может содержать только буквы и цифры без пробелов и спецсимволов")
    if contains_bad_words(name):
        raise HTTPException(status_code=400, detail="Имя содержит запрещённые слова")

    tag_name_raw = tag_name.strip()
    if not tag_name_raw:
        raise HTTPException(status_code=400, detail="Tag обязателен")
    tag_core = tag_name_raw.lstrip("@")
    if not TAG_CORE_REGEX.match(tag_core):
        raise HTTPException(status_code=400, detail="Tag может содержать только буквы, цифры и символ _")
    if contains_bad_words(tag_core):
        raise HTTPException(status_code=400, detail="Tag содержит запрещённые слова")
    # Первая буква всегда заглавная
    tag_core = tag_core[0].upper() + tag_core[1:]
    tag_name = f"@{tag_core}"

    # phone и email уже обработаны выше (None если пустые)
    if phone and not PHONE_REGEX.match(phone):
        raise HTTPException(status_code=400, detail="Введите корректный номер телефона")

    if email and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        raise HTTPException(status_code=400, detail="Введите корректный email")

    if len(password) < 12:
        raise HTTPException(status_code=400, detail="Пароль слишком короткий (минимум 12 символов)")

    # Дополнительные проверки уникальности ещё до вставки, чтобы вернуть более понятные сообщения
    existing_tag = await db.execute(select(User).where(User.tag_name == tag_name))
    if existing_tag.scalars().first():
        raise HTTPException(status_code=400, detail="Tag name already taken")

    if phone:
        existing_phone = await db.execute(
            select(User).where(User.phone_hash.is_not(None))
        )
        # phone_hash вычисляется ниже; здесь только общий запрет на дубли по телефону реализован
        # (конкретное совпадение по телефону вычислить сложно без дешифровки, поэтому доверяем front+первой регистрации)

    if email:
        existing_email = await db.execute(
            select(User).where(User.email_enc.is_not(None))
        )
        # Аналогично email: повторяющиеся адреса лучше ловить на фронтенде до отправки

    # Банковская проверка (заглушка) только если указан телефон
    if phone and not await verify_bank(phone):
        raise HTTPException(400, detail="Bank verification failed")

    # Хэшируем телефон (если есть) и пароль, шифруем email (если есть)
    phone_hash = pwd_hasher.hash(phone) if phone else None
    email_enc = server_fernet.encrypt(email.encode()).decode() if email else None
    password_hash = pwd_hasher.hash(password)

    email_verification_token = _generate_verification_token() if email else None

    user = User(
        name=name,
        tag_name=tag_name,
        phone_hash=phone_hash,
        email_enc=email_enc,
        email_verified=not email,  # no email => nothing to verify
        email_verification_token=email_verification_token,
        password_hash=password_hash,
    )

    try:
        db.add(user)
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Пользователь с таким tag_name / phone / email уже существует",
        )

    # Создаём устройство на сервере автоматически при регистрации
    device_uuid = uuid.uuid4()

    # Проверяем, не существует ли уже устройство с таким fingerprint
    existing_device = await db.execute(
        select(Device).where(Device.device_fingerprint == device_fingerprint)
    )
    if existing_device.scalars().first():
        raise HTTPException(
            status_code=409,
            detail="This device is already registered. Please login instead."
        )

    device = Device(
        id=device_uuid,
        user_id=user.id,
        public_key_x25519=public_key_x25519,
        device_name=device_name,
        device_fingerprint=device_fingerprint,
        is_confirmed=True,  # Автоматически подтверждаем устройство при регистрации
        confirmed_at=datetime.now(timezone.utc),
        last_active=datetime.now(timezone.utc)
    )
    db.add(device)
    await db.commit()

    # TODO: при наличии email-сервиса отправить письмо с ссылкой verify-email?token=...
    if email:
        logging.info(
            f"Email verification token for {tag_name}: {email_verification_token}"
        )

    # Автоматический вход после регистрации
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(user.id)

    response = JSONResponse({
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token,
        "device_id": str(device_uuid),
        "user": {
            "id": str(user.id),
            "tag_name": user.tag_name,
            "name": user.name,
            "avatar_url": user.avatar_url,
        }
    })

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=False
    )

    return response


@app.get("/verify-email", response_model=Dict[str, str])
async def verify_email(
        token: str = Query(..., description="Email verification token"),
        db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.email_verification_token == token)
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=400, detail="Invalid or expired verification token"
        )
    user.email_verified = True
    user.email_verification_token = None
    await db.commit()
    return {"status": "verified", "message": "Email verified successfully"}


from fastapi.responses import JSONResponse


@app.post("/token", response_model=Token)
async def login(
        login_data: LoginRequest,
        db: AsyncSession = Depends(get_db)
):
    username = login_data.username.strip()
    await check_login_bruteforce(username)

    # --- Поиск пользователя ---
    result = await db.execute(select(User).where(User.tag_name == username))
    user = result.scalars().first()

    if not user:
        result = await db.execute(select(User).where(User.name == username))
        user = result.scalars().first()

    if not user or not pwd_hasher.verify(login_data.password, user.password_hash):
        await record_login_failure(username)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    await clear_login_failures(username)

    now = datetime.now(timezone.utc)
    fingerprint = login_data.device_fingerprint

    # --- Если fingerprint НЕ передан ---
    if not fingerprint:
        result = await db.execute(
            select(Device).where(
                Device.user_id == user.id,
                Device.is_confirmed == True
            )
        )
        device = result.scalars().first()

        if not device:
            raise HTTPException(
                status_code=400,
                detail="Требуется device_fingerprint"
            )

        device.last_active = now
        await db.commit()

    else:
        # --- Ищем устройство глобально ---
        result = await db.execute(
            select(Device).where(Device.device_fingerprint == fingerprint)
        )
        device = result.scalars().first()

        if device:
            # --- Устройство уже существует ---
            if device.user_id != user.id:
                raise HTTPException(
                    status_code=403,
                    detail="Устройство принадлежит другому пользователю"
                )

            if not device.is_confirmed:
                raise HTTPException(
                    status_code=403,
                    detail="Устройство не подтверждено"
                )

            device.last_active = now
            await db.commit()

        else:
            # --- Новое устройство ---
            if not login_data.device_name or not login_data.public_key_x25519:
                raise HTTPException(
                    status_code=400,
                    detail="Не хватает данных устройства"
                )

            confirmation_token = secrets.token_urlsafe(32)

            new_device = Device(
                user_id=user.id,
                device_name=login_data.device_name,
                device_fingerprint=fingerprint,
                public_key_x25519=login_data.public_key_x25519,
                confirmation_token=confirmation_token,
                confirmation_requested_at=now,
                is_confirmed=False,
            )

            try:
                db.add(new_device)
                await db.commit()
                await db.refresh(new_device)

            except IntegrityError:
                # --- Race condition (устройство создалось параллельно) ---
                await db.rollback()

                result = await db.execute(
                    select(Device).where(Device.device_fingerprint == fingerprint)
                )
                device = result.scalars().first()

                if not device or device.user_id != user.id:
                    raise HTTPException(
                        status_code=409,
                        detail="Конфликт устройства"
                    )

                if not device.is_confirmed:
                    raise HTTPException(
                        status_code=403,
                        detail="Устройство ожидает подтверждения"
                    )

                device.last_active = now
                await db.commit()

            else:
                # --- Создаём уведомление ---
                notification = DeviceConfirmationNotification(
                    user_id=user.id,
                    device_id=new_device.id,
                    device_name=new_device.device_name,
                    device_fingerprint=new_device.device_fingerprint,
                    confirmation_token=confirmation_token,
                    status="pending",
                )

                db.add(notification)
                await db.commit()

                await manager.send_personal_message(
                    user.id,
                    {
                        "type": "device_confirmation_request",
                        "device_id": str(new_device.id),
                        "device_name": new_device.device_name,
                        "device_fingerprint": new_device.device_fingerprint,
                        "confirmation_token": confirmation_token,
                        "timestamp": now.isoformat()
                    }
                )

                raise HTTPException(
                    status_code=403,
                    detail="Новое устройство. Подтвердите его."
                )

    # --- Токены ---
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(user.id)

    response = JSONResponse({
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token,
    })

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=False
    )

    return response


@app.post("/refresh-token", response_model=Token)
async def refresh_token(refresh_token: str, db: AsyncSession = Depends(get_db)):
    try:
        payload = jwt.decode(refresh_token, JWT_SECRET, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        user_id_raw = payload["sub"]
        user_id = (
            uuid.UUID(user_id_raw) if isinstance(user_id_raw, str) else user_id_raw
        )
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    new_access = create_access_token({"sub": str(user.id)})
    new_refresh = create_refresh_token(user.id)

    return {
        "access_token": new_access,
        "token_type": "bearer",
        "refresh_token": new_refresh,
    }


# hintsage_mac.py — часть 3 (продолжение после refresh-token)


# ────────────────────────────────────────────────
# Эндпоинт для добавления нового устройства
# ────────────────────────────────────────────────
@app.post("/devices", response_model=DeviceOut)
async def add_device(
        public_key_x25519: str,
        device_fingerprint: Optional[str] = None,
        device_name: Optional[str] = None,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)

    # Генерируем fingerprint и имя если не предоставлены
    device_uuid = uuid.uuid4()
    if not device_fingerprint:
        device_fingerprint = f"manual_{device_uuid.hex[:16]}"
    if not device_name:
        device_name = "Manual Device"

    device = Device(
        id=device_uuid,
        user_id=current_user.id,
        public_key_x25519=public_key_x25519,
        device_fingerprint=device_fingerprint,
        device_name=device_name,
        is_confirmed=True,  # Устройства добавленные пользователем считаем подтвержденными
        confirmed_at=datetime.now(timezone.utc)
    )

    db.add(device)
    await db.commit()
    await db.refresh(device)

    return DeviceOut(
        id=str(device.id),
        device_name=device.device_name,
        device_fingerprint=device.device_fingerprint,
        public_key_x25519=device.public_key_x25519,
        is_confirmed=device.is_confirmed,
        last_active=device.last_active,
        created_at=device.created_at,
    )


# ────────────────────────────────────────────────
# Получение публичных ключей устройств другого пользователя (только для друзей)
# ────────────────────────────────────────────────
@app.get("/me/devices", response_model=List[DeviceOut])
async def get_my_devices(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Return all devices registered for the current user (for multi-device E2EE)."""
    await check_rate(current_user.id)
    devices_result = await db.execute(
        select(Device).where(Device.user_id == current_user.id)
    )
    devices = devices_result.scalars().all()
    return [
        DeviceOut(
            id=str(d.id),
            device_name=d.device_name,
            device_fingerprint=d.device_fingerprint,
            public_key_x25519=d.public_key_x25519,
            is_confirmed=d.is_confirmed,
            last_active=d.last_active,
            created_at=d.created_at,
        )
        for d in devices
    ]


# ────────────────────────────────────────────────
# Синхронизация ключей между устройствами
# ────────────────────────────────────────────────
class DeviceKeysSync(BaseModel):
    device_id: str
    encrypted_keys: str


@app.post("/devices/sync-keys")
async def sync_device_keys(
        sync_data: DeviceKeysSync,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Сохраняет зашифрованные ключи для кросс-устройственной синхронизации"""
    await check_rate(current_user.id)

    try:
        device_uuid = uuid.UUID(sync_data.device_id)
    except ValueError:
        raise HTTPException(400, detail="Invalid device_id")

    device_result = await db.execute(
        select(Device).where(
            and_(Device.id == device_uuid, Device.user_id == current_user.id)
        )
    )
    device = device_result.scalars().first()
    if not device:
        # Если устройство не найдено, возможно оно еще не создано
        # Пропускаем синхронизацию без ошибки
        return {"status": "device not found, skipping sync"}

    device.encrypted_keys = sync_data.encrypted_keys
    await db.commit()

    return {"status": "keys synced"}


@app.get("/devices/{device_id}/keys")
async def get_device_keys(
        device_id: str,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Получает зашифрованные ключи для другого устройства"""
    await check_rate(current_user.id)

    try:
        device_uuid = uuid.UUID(device_id)
    except ValueError:
        raise HTTPException(400, detail="Invalid device_id")

    device_result = await db.execute(
        select(Device).where(
            and_(Device.id == device_uuid, Device.user_id == current_user.id)
        )
    )
    device = device_result.scalars().first()
    if not device:
        # Если устройство не найдено, возвращаем null без ошибки
        return {"encrypted_keys": None}

    if not device.encrypted_keys:
        return {"encrypted_keys": None}

    return {"encrypted_keys": device.encrypted_keys}


@app.get("/users/{tag_name}/devices", response_model=List[DeviceOut])
async def get_user_devices(
        tag_name: str,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)

    result = await db.execute(select(User).where(User.tag_name == tag_name))
    target_user = result.scalars().first()
    if not target_user:
        raise HTTPException(404, detail="Пользователь не найден")

    # Allow the user to fetch their own devices without friendship check
    is_self = str(target_user.id) == str(current_user.id)
    if not is_self:
        # Проверяем, что они друзья (в обе стороны)
        friend_check = await db.execute(
            select(Friend).where(
                or_(
                    and_(
                        Friend.user_id == current_user.id,
                        Friend.friend_id == target_user.id,
                    ),
                    and_(
                        Friend.user_id == target_user.id,
                        Friend.friend_id == current_user.id,
                    ),
                )
            )
        )
        if not friend_check.scalars().first():
            raise HTTPException(403, detail="Доступно только между друзьями")

    devices_result = await db.execute(
        select(Device).where(Device.user_id == target_user.id)
    )
    devices = devices_result.scalars().all()

    return [
        DeviceOut(
            id=str(d.id),
            device_name=d.device_name,
            device_fingerprint=d.device_fingerprint,
            public_key_x25519=d.public_key_x25519,
            is_confirmed=d.is_confirmed,
            last_active=d.last_active,
            created_at=d.created_at,
        )
        for d in devices
    ]


# ────────────────────────────────────────────────
# Отправка сообщения (HTTP-версия, для совместимости)
# ────────────────────────────────────────────────
@app.post("/messages/", response_model=dict)
async def send_message_http(
        msg: MessageSend,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)

    if msg.to_tag is None and msg.group_id is None:
        raise HTTPException(400, detail="Укажите to_tag или group_id")

    recipient_id = None
    recipient_tag = None
    group_member_ids: List[Any] = []

    if msg.to_tag:
        result = await db.execute(select(User).where(User.tag_name == msg.to_tag))
        recipient = result.scalars().first()
        if not recipient:
            raise HTTPException(404, detail="Получатель не найден")
        # Admin can always message anyone
        if (
                recipient.allow_messages_only_from_friends
                and current_user.tag_name != ADMIN_TAG
        ):
            friend_check = await db.execute(
                select(Friend).where(
                    or_(
                        and_(
                            Friend.user_id == current_user.id,
                            Friend.friend_id == recipient.id,
                        ),
                        and_(
                            Friend.user_id == recipient.id,
                            Friend.friend_id == current_user.id,
                        ),
                    )
                )
            )
            if not friend_check.scalars().first():
                raise HTTPException(
                    403, detail="Этот пользователь принимает сообщения только от друзей"
                )
        recipient_id = recipient.id
        recipient_tag = recipient.tag_name

    if msg.group_id:
        members_result = await db.execute(
            select(GroupMember.user_id).where(GroupMember.group_id == msg.group_id)
        )
        group_member_ids = [row[0] for row in members_result.all()]

    client_score = msg.client_risk_score if msg.client_risk_score is not None else 0.0
    meta_suspicious, meta_reason, meta_score = await metadata_risk_score(
        db, current_user.id, len(msg.encrypted_content)
    )
    combined_score = max(client_score, meta_score)
    suspicious = combined_score > 0.7 or meta_suspicious
    reason = msg.client_risk_reason_code if client_score > 0.7 else meta_reason
    score = combined_score

    message = Message(
        from_id=current_user.id,
        to_id=recipient_id,
        group_id=msg.group_id,
        encrypted_content=msg.encrypted_content,
        encrypted_session_keys=json.dumps(msg.encrypted_session_keys),
        nonce=msg.nonce,
        version=msg.version,
        suspicious=suspicious,
        suspicious_reason=reason,
        suspicious_score=score,
        attachment_url=msg.attachment_url,
        attachment_type=msg.attachment_type,
        reply_to_id=msg.reply_to_id,
        forward_from_tag=msg.forward_from_tag,
        plain_content_enc=None  # Убираем серверное шифрование для соблюдения E2EE
    )

    db.add(message)
    await db.commit()
    await db.refresh(message)

    # Fetch reply preview if needed
    reply_preview: Optional[Dict] = None
    if msg.reply_to_id:
        rr = await db.execute(
            select(
                Message.encrypted_content,
                Message.encrypted_session_keys,
                Message.nonce,
                User.tag_name.label("from_tag"),
            )
            .join(User, User.id == Message.from_id)
            .where(Message.id == msg.reply_to_id)
        )
        row = rr.first()
        if row:
            reply_preview = {
                "reply_to_encrypted_content": row.encrypted_content,
                "reply_to_encrypted_session_keys": json.loads(
                    row.encrypted_session_keys
                ),
                "reply_to_nonce": row.nonce,
                "reply_to_from_tag": row.from_tag,
            }

    payload = {
        "type": "message",
        "id": message.id,
        "from_tag": current_user.tag_name,
        "to_tag": recipient_tag,
        "group_id": message.group_id,
        "encrypted_content": message.encrypted_content,
        "encrypted_session_keys": json.loads(message.encrypted_session_keys),
        "nonce": message.nonce,
        "version": message.version,
        "timestamp": message.timestamp.isoformat(),
        "delivered": message.delivered,
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
        "suspicious": message.suspicious,
        "suspicious_reason": message.suspicious_reason,
        "suspicious_score": message.suspicious_score,
        "attachment_url": message.attachment_url,
        "attachment_type": message.attachment_type,
        "reply_to_id": message.reply_to_id,
        "forward_from_tag": message.forward_from_tag,
        "plain_content_enc": message.plain_content_enc or None,  # Только зашифрованный серверный fallback
    }

    if reply_preview:
        payload.update(reply_preview)

    if recipient_id:
        await manager.send_personal_message(recipient_id, payload)
    for uid in group_member_ids:
        if uid != current_user.id:
            await manager.send_personal_message(uid, payload)

    await manager.send_personal_message(current_user.id, payload)

    return {"status": "отправлено", "message_id": message.id, "suspicious": suspicious}


# ────────────────────────────────────────────────
# Получение истории сообщений с конкретным пользователем
# ────────────────────────────────────────────────
@app.get("/messages/{to_tag}", response_model=List[MessageOut])
async def get_messages(
        to_tag: str,
        limit: int = Query(1000, ge=1, le=5000),
        offset: int = Query(0, ge=0),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    # Ищем целевого пользователя
    target_result = await db.execute(select(User).where(User.tag_name == to_tag))
    target = target_result.scalars().first()
    if not target:
        raise HTTPException(404, detail="Пользователь не найден")

    # Делаем JOIN с таблицей User, чтобы сразу получить from_tag
    messages_result = await db.execute(
        select(
            Message.id,
            Message.from_id,
            Message.to_id,
            Message.group_id,
            Message.encrypted_content,
            Message.encrypted_session_keys,
            Message.nonce,
            Message.version,
            Message.timestamp,
            Message.delivered,
            Message.read_at,
            Message.suspicious,
            Message.suspicious_reason,
            Message.suspicious_score,
            Message.attachment_url,
            Message.attachment_type,
            Message.edited_at,
            Message.is_pinned,
            Message.is_deleted,
            Message.reply_to_id,
            Message.forward_from_tag,
            Message.plain_content_enc,
            User.tag_name.label("from_tag"),
        )
        .join(User, User.id == Message.from_id)
        .where(
            and_(
                or_(
                    and_(
                        Message.from_id == current_user.id, Message.to_id == target.id
                    ),
                    and_(
                        Message.from_id == target.id, Message.to_id == current_user.id
                    ),
                ),
                Message.is_deleted == False,
            )
        )
        .order_by(Message.timestamp.asc())
        .limit(limit)
        .offset(offset)
    )

    messages = messages_result.all()

    await db.execute(
        update(Message)
        .where(
            and_(
                Message.to_id == current_user.id,
                Message.from_id == target.id,
                Message.delivered == False,
            )
        )
        .values(delivered=True, delivery_attempted=True)
    )
    await db.commit()

    # Load reactions for all messages
    msg_ids = [m.id for m in messages]
    reactions_by_msg: Dict[int, Dict[str, List[str]]] = {}
    if msg_ids:
        reactions_result = await db.execute(
            select(MessageReaction).where(MessageReaction.message_id.in_(msg_ids))
        )
        for r in reactions_result.scalars().all():
            if r.message_id not in reactions_by_msg:
                reactions_by_msg[r.message_id] = {}
            reactions_by_msg[r.message_id].setdefault(r.emoji, []).append(r.user_tag)

    # Load reply-to message previews
    reply_ids = list({m.reply_to_id for m in messages if m.reply_to_id is not None})
    replied_map: Dict[int, Any] = {}
    if reply_ids:
        rr = await db.execute(
            select(
                Message.id,
                Message.encrypted_content,
                Message.encrypted_session_keys,
                Message.nonce,
                User.tag_name.label("from_tag"),
            )
            .join(User, User.id == Message.from_id)
            .where(Message.id.in_(reply_ids))
        )
        for row in rr.all():
            replied_map[row.id] = row

    out = []
    for m in messages:
        reply = replied_map.get(m.reply_to_id) if m.reply_to_id else None
        out.append(
            MessageOut(
                id=m.id,
                from_tag=m.from_tag,
                to_tag=target.tag_name if m.to_id == target.id else current_user.tag_name,
                group_id=m.group_id,
                encrypted_content=m.encrypted_content,
                encrypted_session_keys=json.loads(m.encrypted_session_keys),
                nonce=m.nonce,
                version=m.version or "1",
                timestamp=m.timestamp,
                delivered=m.delivered,
                edited_at=m.edited_at,
                suspicious=m.suspicious,
                suspicious_reason=m.suspicious_reason,
                suspicious_score=m.suspicious_score or 0.0,
                attachment_url=m.attachment_url,
                attachment_type=m.attachment_type,
                reply_to_id=m.reply_to_id,
                reply_to_from_tag=reply.from_tag if reply else None,
                forward_from_tag=m.forward_from_tag,
                plain_content_enc=m.plain_content_enc,  # Только зашифрованный серверный fallback
                reactions=reactions_by_msg.get(m.id),
                reply_to_encrypted_content=reply.encrypted_content if reply else None,
                reply_to_encrypted_session_keys=json.loads(reply.encrypted_session_keys)
                if reply
                else None,
                reply_to_nonce=reply.nonce if reply else None,
            )
        )

    return out


@app.post("/decrypt-fernet")
async def decrypt_fernet(
        request: dict,
        current_user: User = Depends(get_current_user),
):
    """Расшифровка Fernet для импортированных сообщений (E2EE compliant)"""
    encrypted_data = request.get("encrypted_data")
    if not encrypted_data:
        return {"decrypted_text": None}

    try:
        fernet_key = Fernet(SERVER_ENCRYPTION_KEY)
        decrypted_text = fernet_key.decrypt(encrypted_data.encode()).decode()
        print(
            f"📁 DEBUG: Successfully decrypted fernet data for user {current_user.tag_name}: '{decrypted_text[:50]}{'...' if len(decrypted_text) > 50 else ''}'")
        return {"decrypted_text": decrypted_text}
    except Exception as e:
        print(f"📁 DEBUG: Fernet decryption error for user {current_user.tag_name}: {e}")
        print(
            f"📁 DEBUG: Encrypted data length: {len(encrypted_data)}, starts with: {encrypted_data[:50] if len(encrypted_data) > 50 else encrypted_data}")
        return {"decrypted_text": None}


@app.post("/decrypt-fernet-batch")
async def decrypt_fernet_batch(
        request: dict,
        current_user: User = Depends(get_current_user),
):
    """Пакетная расшифровка Fernet для импортированных сообщений"""
    encrypted_data_array = request.get("encrypted_data_array", [])
    if not encrypted_data_array:
        return {"decrypted_texts": {}}

    fernet_key = Fernet(SERVER_ENCRYPTION_KEY)
    decrypted_texts = {}

    for encrypted_data in encrypted_data_array:
        if not encrypted_data:
            decrypted_texts[encrypted_data] = None
            continue

        try:
            decrypted_text = fernet_key.decrypt(encrypted_data.encode()).decode()
            decrypted_texts[encrypted_data] = decrypted_text
        except Exception as e:
            print(f"📁 DEBUG: Batch fernet decryption error for user {current_user.tag_name}: {e}")
            decrypted_texts[encrypted_data] = None

    print(f"📁 DEBUG: Batch decrypted {len(encrypted_data_array)} items for user {current_user.tag_name}")
    return {"decrypted_texts": decrypted_texts}


def _safe_server_fernet_decrypt(enc: Optional[str]) -> Optional[str]:
    """Decrypt server-encrypted content (email, etc.), returning None on any failure."""
    if not enc:
        return None
    try:
        return server_fernet.decrypt(enc.encode()).decode()
    except Exception:
        return None


# -------------------------
# WebSocket эндпоинт (реальное время для сообщений, read-receipts и т.д.)
# -------------------------


@app.websocket("/ws")
async def websocket_endpoint(
        websocket: WebSocket,
        db: AsyncSession = Depends(get_db),
):
    # Парсим токен и device_id из query params
    token = websocket.query_params.get("token")
    device_id_raw = websocket.query_params.get("device_id")

    if not token or not device_id_raw:
        await websocket.close(code=1008)
        return

    # Декодируем JWT
    try:
        payload = jwt_decode(token, JWT_SECRET, algorithms=["HS256"])
    except ExpiredSignatureError:
        await websocket.close(code=1008)
        return
    except InvalidTokenError:
        await websocket.close(code=1008)
        return

    # Получаем UUID пользователя и device_id
    try:
        user_id = str(uuid.UUID(payload["sub"]))  # str(UUID) для asyncpg
        device_id = str(uuid.UUID(device_id_raw))
    except ValueError:
        await websocket.close(code=1008)
        return

    # Получаем пользователя из БД
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        await websocket.close(code=1008)
        return

    # Проверяем, что устройство принадлежит пользователю и подтверждено
    device_result = await db.execute(
        select(Device).where(
            Device.id == device_id,
            Device.user_id == user_id,
            Device.is_confirmed == True
        )
    )
    device = device_result.scalars().first()
    if not device:
        await websocket.close(code=1008)  # 403 Forbidden
        return

    print(f"User {user.id} connected via WS from device {device_id}")

    # Обновляем статус онлайн и время активности устройства
    user.is_online = True
    user.last_seen = datetime.now(timezone.utc)
    device.last_active = datetime.now(timezone.utc)
    await db.commit()

    # Регистрируем соединение в менеджере
    await manager.connect(user.id, device_id, websocket)

    # Уведомляем друзей о выходе онлайн
    friends_res = await db.execute(
        select(Friend.friend_id).where(Friend.user_id == user.id)
    )
    friend_ids_online = [r[0] for r in friends_res.all()]
    for fid in friend_ids_online:
        await manager.send_personal_message(
            fid,
            {
                "type": "user_status",
                "tag": user.tag_name,
                "is_online": True,
            },
        )

    try:
        while True:
            try:
                data = await websocket.receive_text()
                msg_data = json.loads(data)
                msg_type = msg_data.get("type")

                if msg_type == "typing":
                    to_tag = msg_data.get("to_tag")
                    if to_tag:
                        target_res = await db.execute(
                            select(User).where(User.tag_name == to_tag)
                        )
                        target_user = target_res.scalars().first()
                        if target_user:
                            await manager.send_personal_message(
                                target_user.id,
                                {"type": "typing", "from_tag": user.tag_name},
                            )

                elif msg_type in (
                        "call_offer",
                        "call_answer",
                        "call_ice",
                        "call_end",
                        "call_reject",
                        # Новые типы для LiveKit сигнализации
                        "call_request",
                        "call_accepted",
                        "call_declined",
                        "call_ended",
                ):
                    print(f"📞 Received call message: {msg_type} from {user.id}")

                    # Поддерживаем оба формата: to_tag и to_user_id
                    to_tag = msg_data.get("to_tag")
                    to_user_id = msg_data.get("to_user_id")

                    target_user = None

                    if to_tag:
                        print(f"📞 Looking for user by tag: {to_tag}")
                        target_res = await db.execute(
                            select(User).where(User.tag_name == to_tag)
                        )
                        target_user = target_res.scalars().first()
                    elif to_user_id:
                        print(f"📞 Looking for user by ID: {to_user_id}")
                        # Если передан user_id, ищем по ID
                        try:
                            target_uuid = uuid.UUID(to_user_id)
                            target_res = await db.execute(
                                select(User).where(User.id == target_uuid)
                            )
                            target_user = target_res.scalars().first()
                        except ValueError as e:
                            print(f"📞 Invalid UUID format: {e}")
                            pass

                    if target_user:
                        print(f"📞 Found target user: {target_user.id} ({target_user.tag_name})")
                        # Добавляем информацию об отправителе
                        forward_payload = {
                            **msg_data,
                            "from_user_id": str(user.id),
                            "from_user_name": user.name or user.tag_name,
                            "from_tag": user.tag_name
                        }
                        await manager.send_personal_message(
                            target_user.id, forward_payload
                        )
                        print(f"📞 Forwarded call message to: {target_user.id}")
                    else:
                        print(f"📞 Target user not found! to_tag={to_tag}, to_user_id={to_user_id}")

                else:
                    print(f"Received WS message from {user.id}: {msg_data}")

            except json.JSONDecodeError:
                print("Invalid JSON received")
                continue

    except WebSocketDisconnect:
        print(f"User {user.id} disconnected from device {device_id}")
        manager.disconnect(user.id, device_id)
    except Exception as e:
        print("WS error:", e)
        manager.disconnect(user.id, device_id)
    finally:
        # Обновляем статус офлайн при отключении
        user.is_online = False
        _offline_dt = datetime.now(timezone.utc)
        user.last_seen = _offline_dt
        await db.commit()
        # Уведомляем друзей об офлайне
        last_seen_iso = _offline_dt.isoformat()
        for fid in friend_ids_online:
            await manager.send_personal_message(
                fid,
                {
                    "type": "user_status",
                    "tag": user.tag_name,
                    "is_online": False,
                    "last_seen": last_seen_iso,
                },
            )
        try:
            await websocket.close(code=1011)
        except:
            pass


# ─────────────────────────────────────────────────────────────
# Настройки приватности
# ─────────────────────────────────────────────────────────────
class SettingsUpdate(BaseModel):
    online_visibility: Optional[str] = None  # all | nobody | friends_only
    allow_messages_only_from_friends: Optional[bool] = None
    allow_calls_from: Optional[str] = None  # all | friends


@app.patch("/users/me/settings")
async def update_settings(
        data: SettingsUpdate,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)
    if data.online_visibility is not None:
        if data.online_visibility not in ("all", "nobody", "friends_only"):
            raise HTTPException(400, detail="Недопустимое значение online_visibility")
        current_user.online_visibility = data.online_visibility
    if data.allow_messages_only_from_friends is not None:
        current_user.allow_messages_only_from_friends = (
            data.allow_messages_only_from_friends
        )
    if data.allow_calls_from is not None:
        if data.allow_calls_from not in ("all", "friends"):
            raise HTTPException(400, detail="Недопустимое значение allow_calls_from")
        current_user.allow_calls_from = data.allow_calls_from
    await db.commit()
    return {"status": "updated"}


# ─────────────────────────────────────────────────────────────
# Репорты
# ─────────────────────────────────────────────────────────────
class ReportCreate(BaseModel):
    reported_tag: str
    text: str
    screenshot_urls: List[str] = []


@app.post("/reports/")
async def submit_report(
        data: ReportCreate,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)
    result = await db.execute(select(User).where(User.tag_name == data.reported_tag))
    reported = result.scalars().first()
    if not reported:
        raise HTTPException(404, detail="Пользователь не найден")
    if reported.id == current_user.id:
        raise HTTPException(400, detail="Нельзя пожаловаться на себя")

    report = Report(
        from_user_id=current_user.id,
        reported_user_id=reported.id,
        text=data.text,
        screenshot_urls=json.dumps(data.screenshot_urls),
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    # Notify admin via WS
    admin_result = await db.execute(select(User).where(User.tag_name == ADMIN_TAG))
    admin = admin_result.scalars().first()
    if admin:
        await manager.send_personal_message(
            admin.id,
            {
                "type": "new_report",
                "report_id": report.id,
                "from_tag": current_user.tag_name,
                "reported_tag": reported.tag_name,
            },
        )
    return {"status": "ok", "report_id": report.id}


@app.post("/reports/upload")
async def upload_report_screenshot(
        file: UploadFile = File(...),
        current_user: User = Depends(get_current_user),
):
    await check_rate(current_user.id)
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, detail="Только изображения")
    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(400, detail="Файл слишком большой (макс. 10 МБ)")
    os.makedirs("static/uploads", exist_ok=True)
    ext = os.path.splitext(file.filename or "img")[1] or ".jpg"
    filename = f"report_{uuid4().hex}{ext}"
    save_path = os.path.join("static/uploads", filename)
    with open(save_path, "wb") as f:
        f.write(contents)
    return {"url": f"/static/uploads/{filename}"}


@app.post("/api/reports")
async def submit_enhanced_report(
        reported_user_id: str = Form(...),
        text: str = Form(...),
        reasons: str = Form(...),
        is_urgent: bool = Form(False),
        files: List[UploadFile] = File(default=[]),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)

    # Validate reported user
    try:
        reported_uuid = uuid.UUID(reported_user_id)
    except ValueError:
        raise HTTPException(400, detail="Неверный ID пользователя")

    result = await db.execute(select(User).where(User.id == reported_uuid))
    reported = result.scalars().first()
    if not reported:
        raise HTTPException(404, detail="Пользователь не найден")
    if reported.id == current_user.id:
        raise HTTPException(400, detail="Нельзя пожаловаться на себя")

    # Handle file uploads
    screenshot_urls = []

    # Create report first to get ID
    report = Report(
        from_user_id=current_user.id,
        reported_user_id=reported.id,
        text=text,
        screenshot_urls="[]",  # Will be updated
        reasons=reasons,
        is_urgent=is_urgent,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    # Create directory for report screenshots
    report_dir = f"static/reports/{report.id}"
    os.makedirs(report_dir, exist_ok=True)

    for file in files:
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(400, detail=f"Файл {file.filename} не является изображением")
        contents = await file.read()
        if len(contents) > 10 * 1024 * 1024:
            raise HTTPException(400, detail=f"Файл {file.filename} слишком большой (макс. 10 МБ)")

        ext = os.path.splitext(file.filename or "img")[1] or ".jpg"
        filename = f"screenshot_{uuid4().hex}{ext}"
        save_path = os.path.join(report_dir, filename)
        with open(save_path, "wb") as f:
            f.write(contents)
        screenshot_urls.append(f"/static/reports/{report.id}/{filename}")

    # Update report with screenshot URLs
    report.screenshot_urls = json.dumps(screenshot_urls)
    await db.commit()

    # Notify admin via WS
    admin_result = await db.execute(select(User).where(User.tag_name == ADMIN_TAG))
    admin = admin_result.scalars().first()
    if admin:
        await manager.send_personal_message(
            admin.id,
            {
                "type": "new_report",
                "report_id": report.id,
                "from_tag": current_user.tag_name,
                "reported_tag": reported.tag_name,
                "is_urgent": is_urgent,
            },
        )
    return {"status": "ok", "report_id": report.id, "redirect": "/"}


# ─────────────────────────────────────────────────────────────
# Администраторские эндпоинты
# ─────────────────────────────────────────────────────────────
async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.tag_name != ADMIN_TAG:
        raise HTTPException(403, detail="Нет доступа")
    return current_user


@app.get("/admin/users")
async def admin_list_users(
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        _admin: User = Depends(require_admin),
        db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).offset(offset).limit(limit))
    users = result.scalars().all()
    return [
        {
            "id": str(u.id),
            "tag_name": u.tag_name,
            "name": u.name,
            "avatar_url": u.avatar_url,
            "is_online": u.is_online,
            "created_at": u.created_at.isoformat(),
            "banned_until": u.banned_until.isoformat() if u.banned_until else None,
        }
        for u in users
    ]


@app.get("/admin/reports")
async def admin_list_reports(
        status: Optional[str] = Query(None),
        _admin: User = Depends(require_admin),
        db: AsyncSession = Depends(get_db),
):
    q = select(Report).order_by(Report.created_at.desc())
    if status:
        q = q.where(Report.status == status)
    result = await db.execute(q)
    reports = result.scalars().all()
    out = []
    for r in reports:
        from_res = await db.execute(select(User).where(User.id == r.from_user_id))
        reported_res = await db.execute(
            select(User).where(User.id == r.reported_user_id)
        )
        from_u = from_res.scalars().first()
        reported_u = reported_res.scalars().first()
        out.append(
            {
                "id": r.id,
                "from_tag": from_u.tag_name if from_u else "?",
                "from_name": from_u.name if from_u else "?",
                "reported_tag": reported_u.tag_name if reported_u else "?",
                "reported_name": reported_u.name if reported_u else "?",
                "text": r.text,
                "screenshot_urls": json.loads(r.screenshot_urls or "[]"),
                "reasons": json.loads(r.reasons or "[]"),
                "is_urgent": r.is_urgent,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            }
        )
    return out


@app.post("/admin/reports/{report_id}/action")
async def admin_resolve_report(
        report_id: int,
        action: str = Query(..., pattern="^(ban|decline|clarify)$"),
        ban_hours: Optional[int] = Query(None, ge=1),
        _admin: User = Depends(require_admin),
        db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalars().first()
    if not report:
        raise HTTPException(404, detail="Репорт не найден")

    report.resolved_at = datetime.now(timezone.utc)

    if action == "ban":
        if ban_hours is None:
            raise HTTPException(400, detail="Укажите ban_hours")
        reported_result = await db.execute(
            select(User).where(User.id == report.reported_user_id)
        )
        reported_user = reported_result.scalars().first()
        if reported_user:
            if ban_hours >= 876000:  # ~100 лет = пожизненный
                reported_user.banned_until = datetime(9999, 12, 31, tzinfo=timezone.utc)
            else:
                reported_user.banned_until = datetime.now(timezone.utc) + timedelta(
                    hours=ban_hours
                )
            # Kick them from WS
            _ban_until = reported_user.banned_until
            await manager.send_personal_message(
                reported_user.id,
                {
                    "type": "banned",
                    "until": _ban_until.isoformat() if _ban_until else None,
                },
            )
        report.status = "banned"

    elif action == "decline":
        report.status = "declined"

    elif action == "clarify":
        # Notify reporter via WS (admin initiates chat)
        from_result = await db.execute(
            select(User).where(User.id == report.from_user_id)
        )
        from_user = from_result.scalars().first()
        report.status = "clarify"
        if from_user:
            await manager.send_personal_message(
                from_user.id,
                {
                    "type": "admin_clarify",
                    "report_id": report_id,
                    "admin_tag": ADMIN_TAG,
                },
            )

    await db.commit()
    return {"status": "ok", "action": action}


@app.post("/admin/users/{tag}/ban")
async def admin_ban_user(
        tag: str,
        ban_hours: int = Query(..., ge=1),
        _admin: User = Depends(require_admin),
        db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.tag_name == tag))
    user = result.scalars().first()
    if not user:
        raise HTTPException(404, detail="Пользователь не найден")
    if ban_hours >= 876000:
        user.banned_until = datetime(9999, 12, 31, tzinfo=timezone.utc)
    else:
        user.banned_until = datetime.now(timezone.utc) + timedelta(hours=ban_hours)
    await db.commit()
    _ban_dt = user.banned_until
    _ban_iso = _ban_dt.isoformat() if _ban_dt else None
    await manager.send_personal_message(
        user.id,
        {"type": "banned", "until": _ban_iso},
    )
    return {"status": "banned", "until": _ban_iso}


@app.post("/admin/users/{tag}/unban")
async def admin_unban_user(
        tag: str,
        _admin: User = Depends(require_admin),
        db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.tag_name == tag))
    user = result.scalars().first()
    if not user:
        raise HTTPException(404, detail="Пользователь не найден")
    user.banned_until = None
    await db.commit()
    return {"status": "unbanned"}


# ─────────────────────────────────────────────────────────────
# Маршрут для страницы администратора
# ─────────────────────────────────────────────────────────────
@app.get("/admin-panel", response_class=HTMLResponse)
async def admin_panel_page(request: Request):
    # Check if user is admin
    token = request.cookies.get("access_token") or request.headers.get("authorization", "").replace("Bearer ", "")
    if not token:
        return RedirectResponse(url="/?error=403", status_code=302)
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            user_id = uuid.UUID(payload["sub"]) if isinstance(payload["sub"], str) else payload["sub"]
            async with async_session() as session:
                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalars().first()
                if user and user.tag_name == ADMIN_TAG:
                    return templates.TemplateResponse(request, "admin-index.html", {"request": request})
    except (JWTError, ValueError, TypeError, KeyError):
        pass

    return RedirectResponse(url="/?error=403", status_code=302)


# -------------------------
# Запросы на дружбу
# -------------------------
@app.post("/friend-requests/", response_model=Dict[str, str])
async def send_friend_request(
        req: FriendRequestCreate,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)

    to_result = await db.execute(select(User).where(User.tag_name == req.to_tag))
    to_user: Optional[User] = to_result.scalars().first()
    if not to_user:
        raise HTTPException(404, detail="Пользователь не найден")

    # Проверяем существующий запрос
    existing_req_result = await db.execute(
        select(FriendRequest).where(
            and_(
                FriendRequest.from_id == current_user.id,
                FriendRequest.to_id == to_user.id,
                FriendRequest.status == "pending",
            )
        )
    )
    if existing_req_result.scalars().first():
        raise HTTPException(400, detail="Запрос уже отправлен")

    friend_req = FriendRequest(from_id=current_user.id, to_id=to_user.id)
    db.add(friend_req)
    await db.commit()

    # Уведомление через WS
    await manager.send_personal_message(
        to_user.id,
        {
            "type": "friend_request",
            "from_tag": current_user.tag_name,
            "from_name": current_user.name,
        },
    )
    return {"status": "запрос отправлен"}


@app.put("/friend-requests/{req_id}", response_model=Dict[str, str])
async def update_friend_request(
        req_id: int,
        accept: Annotated[bool, Query(...)] = True,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)

    req_result = await db.execute(
        select(FriendRequest).where(
            and_(
                FriendRequest.id == req_id,
                FriendRequest.to_id == current_user.id,
                FriendRequest.status == "pending",
            )
        )
    )
    friend_req: Optional[FriendRequest] = req_result.scalars().first()
    if not friend_req:
        raise HTTPException(404, detail="Запрос не найден или уже обработан")

    if accept:
        friend_req.status = "accepted"
        existing = await db.execute(
            select(Friend).where(
                and_(
                    Friend.user_id == current_user.id,
                    Friend.friend_id == friend_req.from_id,
                )
            )
        )
        if not existing.scalars().first():
            db.add(Friend(user_id=current_user.id, friend_id=friend_req.from_id))
            db.add(Friend(user_id=friend_req.from_id, friend_id=current_user.id))
    else:
        friend_req.status = "rejected"

    await db.commit()

    status_text: str = "принят" if accept else "отклонен"
    await manager.send_personal_message(
        friend_req.from_id,
        {
            "type": "friend_request_update",
            "to_tag": current_user.tag_name,
            "status": status_text,
        },
    )
    return {"status": "обновлено"}


@app.get("/friends/", response_model=List[UserOut])
async def get_friends(
        current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await check_rate(current_user.id)

    friends_result = await db.execute(
        select(Friend).where(Friend.user_id == current_user.id)
    )
    friends: List[Friend] = list(friends_result.scalars().all())
    friend_ids: List[int] = [f.friend_id for f in friends]

    users_result = await db.execute(select(User).where(User.id.in_(friend_ids)))
    users: List[User] = list(users_result.scalars().all())

    return [
        UserOut(id=str(u.id), tag_name=u.tag_name, name=u.name, avatar_url=u.avatar_url)
        for u in users
    ]


@app.get("/chats")
async def get_chats(
        current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Получение списка чатов (друзей) для импорта"""
    await check_rate(current_user.id)

    # Получаем всех друзей пользователя
    friends_result = await db.execute(
        select(Friend).where(Friend.user_id == current_user.id)
    )
    friends = friends_result.scalars().all()

    chats = []
    for friend in friends:
        user_result = await db.execute(
            select(User).where(User.id == friend.friend_id)
        )
        user = user_result.scalars().first()
        if user:
            chats.append({
                "id": str(user.id),
                "name": user.name or user.tag_name,
                "other_user_name": user.name or user.tag_name
            })

    # Проверяем обратную дружбу
    reverse_friends_result = await db.execute(
        select(Friend).where(Friend.friend_id == current_user.id)
    )
    reverse_friends = reverse_friends_result.scalars().all()

    for friend in reverse_friends:
        user_result = await db.execute(
            select(User).where(User.id == friend.user_id)
        )
        user = user_result.scalars().first()
        if user:
            # Проверяем что уже не добавлен
            if not any(chat["id"] == str(user.id) for chat in chats):
                chats.append({
                    "id": str(user.id),
                    "name": user.name or user.tag_name,
                    "other_user_name": user.name or user.tag_name
                })

    return chats


@app.get("/notifications", response_model=List[SystemNotificationOut])
async def get_notifications(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Получение системных уведомлений"""
    await check_rate(current_user.id)

    # Удаляем просроченные уведомления
    await db.execute(
        delete(SystemNotification).where(
            and_(
                SystemNotification.user_id == current_user.id,
                SystemNotification.expires_at < datetime.now(timezone.utc)
            )
        )
    )
    await db.commit()

    # Получаем активные уведомления
    notifications_result = await db.execute(
        select(SystemNotification)
        .where(SystemNotification.user_id == current_user.id)
        .order_by(SystemNotification.created_at.desc())
        .limit(50)
    )
    notifications = notifications_result.scalars().all()

    return [
        SystemNotificationOut(
            id=n.id,
            type=n.type,
            title=n.title,
            message=n.message,
            data=n.data,
            is_read=n.is_read,
            created_at=n.created_at,
            expires_at=n.expires_at
        )
        for n in notifications
    ]


@app.post("/notifications/{notification_id}/read")
async def mark_notification_read(
        notification_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Отметить уведомление как прочитанное"""
    await check_rate(current_user.id)

    notification_result = await db.execute(
        select(SystemNotification).where(
            and_(
                SystemNotification.id == notification_id,
                SystemNotification.user_id == current_user.id
            )
        )
    )
    notification = notification_result.scalars().first()

    if not notification:
        raise HTTPException(404, detail="Уведомление не найдено")

    notification.is_read = True
    await db.commit()

    return {"status": "ok"}


@app.put("/devices/{device_id}/rename")
async def rename_device(
        device_id: str,
        rename_data: DeviceRenameRequest,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Переименование устройства"""
    await check_rate(current_user.id)

    device_result = await db.execute(
        select(Device).where(
            and_(
                Device.id == uuid.UUID(device_id),
                Device.user_id == current_user.id
            )
        )
    )
    device = device_result.scalars().first()

    if not device:
        raise HTTPException(404, detail="Устройство не найдено")

    device.device_name = rename_data.device_name
    await db.commit()

    return {"status": "ok", "device_name": rename_data.device_name}


@app.get("/conversations", response_model=List[ConversationOut])
async def get_conversations(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Возвращает список чатов с последним сообщением (зашифрованным) и количеством непрочитанных сообщений."""

    await check_rate(current_user.id)

    # Получаем список друзей
    friends_result = await db.execute(
        select(Friend).where(Friend.user_id == current_user.id)
    )
    friends = friends_result.scalars().all()
    friend_ids = [f.friend_id for f in friends]
    if not friend_ids:
        return []

    # Получаем пользователей друзей
    users_result = await db.execute(select(User).where(User.id.in_(friend_ids)))
    users = {str(u.id): u for u in users_result.scalars().all()}

    out: List[ConversationOut] = []

    for fid in friend_ids:
        u = users.get(str(fid))
        if not u:
            continue

        # Получаем последнее сообщение
        last_msg_result = await db.execute(
            select(Message)
            .where(
                and_(
                    or_(
                        and_(Message.from_id == current_user.id, Message.to_id == fid),
                        and_(Message.from_id == fid, Message.to_id == current_user.id),
                    ),
                    Message.is_deleted == False  # Исключаем удаленные сообщения
                )
            )
            .order_by(Message.timestamp.desc())
            .limit(1)
        )
        last_msg = last_msg_result.scalars().first()

        # Количество непрочитанных сообщений
        unread_count = 0
        unread_result = await db.execute(
            select(func.count(Message.id)).where(
                and_(
                    Message.from_id == fid,
                    Message.to_id == current_user.id,
                    Message.read_at.is_(None),
                    Message.is_deleted == False  # Исключаем удаленные сообщения
                )
            )
        )
        unread_count = unread_result.scalar() or 0

        out.append(
            ConversationOut(
                id=str(u.id),
                tag_name=u.tag_name,
                name=u.name,
                avatar_url=u.avatar_url,
                last_message_encrypted=last_msg.encrypted_content if last_msg else None,
                last_message_encrypted_session_keys=json.loads(
                    last_msg.encrypted_session_keys
                ) if last_msg and last_msg.encrypted_session_keys else None,
                last_message_nonce=last_msg.nonce if last_msg else None,
                last_message_plain=last_msg.plain_content_enc if last_msg else None,
                # plain_content_enc для импортированных сообщений
                last_message_at=last_msg.timestamp if last_msg else None,
                last_message_from_me=(last_msg.from_id == current_user.id) if last_msg else False,
                unread_count=unread_count,
                last_delivered=last_msg.delivered if last_msg else False,
                last_read_at=last_msg.read_at if last_msg else None,
            )
        )

    # Сортировка по времени последнего сообщения (сначала новые)
    out.sort(
        key=lambda c: c.last_message_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    return out


@app.patch("/messages/{message_id}/read")
async def mark_message_read(
        message_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)
    result = await db.execute(
        select(Message).where(
            and_(Message.id == message_id, Message.to_id == current_user.id)
        )
    )
    msg = result.scalars().first()
    if not msg:
        raise HTTPException(404, detail="Message not found")
    msg.read_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "read"}


@app.post("/messages/mark-read")
async def mark_conversation_read(
        to_tag: str = Query(..., description="Conversation partner tag"),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Mark all messages from to_tag to current user as read."""
    await check_rate(current_user.id)
    result = await db.execute(select(User).where(User.tag_name == to_tag))
    other = result.scalars().first()
    if not other:
        raise HTTPException(404, detail="User not found")
    now_ts = datetime.now(timezone.utc)
    await db.execute(
        update(Message)
        .where(
            and_(
                Message.from_id == other.id,
                Message.to_id == current_user.id,
                Message.read_at.is_(None),
            )
        )
        .values(read_at=now_ts)
    )
    await db.commit()

    # Уведомляем собеседника что его сообщения прочитаны
    await manager.send_personal_message(
        other.id,
        {
            "type": "read_receipt",
            "from_tag": current_user.tag_name,
        },
    )

    return {"status": "ok"}


# -------------------------
# Группы и каналы (базовая реализация)
# -------------------------
@app.post("/groups/", response_model=Dict[str, object])
async def create_group(
        data: GroupCreate,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)

    existing_result = await db.execute(select(Group).where(Group.name == data.name))
    if existing_result.scalars().first():
        raise HTTPException(400, detail="Группа с таким именем уже существует")

    group = Group(name=data.name, owner_id=current_user.id)
    db.add(group)
    await db.commit()
    await db.refresh(group)

    # Автоматически добавляем владельца как члена
    member = GroupMember(group_id=group.id, user_id=current_user.id)
    db.add(member)
    await db.commit()

    return {"group_id": group.id, "name": group.name}


@app.post("/channels/", response_model=Dict[str, object])
async def create_channel(
        data: ChannelCreate,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)

    existing_result = await db.execute(select(Channel).where(Channel.name == data.name))
    if existing_result.scalars().first():
        raise HTTPException(400, detail="Канал с таким именем уже существует")

    channel = Channel(name=data.name, owner_id=current_user.id)
    db.add(channel)
    await db.commit()
    await db.refresh(channel)

    return {"channel_id": channel.id, "name": channel.name}


@app.get("/search-users", response_model=List[SearchUserOut])
async def search_users(
        q: str = Query(..., min_length=2),
        limit: int = Query(20, ge=5, le=50),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)

    query = q.lower().lstrip("@")
    pattern = f"%{query}%"

    result = await db.execute(
        select(User)
        .where(
            and_(
                or_(User.tag_name.ilike(pattern), User.name.ilike(pattern)),
                User.id != current_user.id,
            )
        )
        .limit(limit)
    )
    users = result.scalars().all()
    if not users:
        return []

    user_ids = [u.id for u in users]
    friends_result = await db.execute(
        select(Friend.friend_id).where(
            and_(Friend.user_id == current_user.id, Friend.friend_id.in_(user_ids))
        )
    )
    friend_ids = {r[0] for r in friends_result.all()}

    sent_result = await db.execute(
        select(FriendRequest.to_id).where(
            and_(
                FriendRequest.from_id == current_user.id,
                FriendRequest.to_id.in_(user_ids),
                FriendRequest.status == "pending",
            )
        )
    )
    sent_to_ids = {r[0] for r in sent_result.all()}

    received_result = await db.execute(
        select(FriendRequest.from_id).where(
            and_(
                FriendRequest.to_id == current_user.id,
                FriendRequest.from_id.in_(user_ids),
                FriendRequest.status == "pending",
            )
        )
    )
    received_from_ids = {r[0] for r in received_result.all()}

    return [
        SearchUserOut(
            id=str(u.id),
            tag_name=u.tag_name,
            name=u.name,
            avatar_url=u.avatar_url,
            is_friend=u.id in friend_ids,
            pending_request_sent=u.id in sent_to_ids,
            pending_request_received=u.id in received_from_ids,
        )
        for u in users
    ]


@app.get("/users/me/profile", response_model=ProfileOut)
async def get_my_profile(
        current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await check_rate(current_user.id)
    email_val = None
    if current_user.email_enc:
        try:
            email_val = _safe_server_fernet_decrypt(current_user.email_enc)
        except Exception:
            pass

    avatars_result = await db.execute(
        select(UserAvatar).where(UserAvatar.user_id == current_user.id).limit(6)
    )
    avatars = [
        AvatarOut(
            id=a.id,
            avatar_url=a.avatar_url,
            created_at=a.created_at,
            is_active=a.is_active,
        )
        for a in avatars_result.scalars().all()
    ]

    return ProfileOut(
        id=str(current_user.id),
        tag_name=current_user.tag_name,
        name=current_user.name,
        avatar_url=current_user.avatar_url,
        avatars=avatars,
        email=email_val,
        phone=None,
        is_online=current_user.is_online,
        last_seen=current_user.last_seen,
        is_friend=False,
        pending_request_sent=False,
        pending_request_received=False,
    )


@app.get("/users/{tag_name}/profile", response_model=ProfileOut)
async def get_user_profile(
        tag_name: str,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        _check_online_vis: bool = True,
):
    await check_rate(current_user.id)
    result = await db.execute(select(User).where(User.tag_name == tag_name))
    user = result.scalars().first()
    if not user:
        raise HTTPException(404, detail="User not found")

    is_friend = False
    pending_sent = False
    pending_received = False
    if user.id != current_user.id:
        fr = await db.execute(
            select(Friend).where(
                and_(Friend.user_id == current_user.id, Friend.friend_id == user.id)
            )
        )
        is_friend = fr.scalars().first() is not None
        req_sent = await db.execute(
            select(FriendRequest).where(
                and_(
                    FriendRequest.from_id == current_user.id,
                    FriendRequest.to_id == user.id,
                    FriendRequest.status == "pending",
                )
            )
        )
        pending_sent = req_sent.scalars().first() is not None
        req_recv = await db.execute(
            select(FriendRequest).where(
                and_(
                    FriendRequest.to_id == current_user.id,
                    FriendRequest.from_id == user.id,
                    FriendRequest.status == "pending",
                )
            )
        )
        pending_received = req_recv.scalars().first() is not None

    email_val = None
    phone_val = None
    if user.id == current_user.id:
        if user.email_enc:
            try:
                email_val = _safe_server_fernet_decrypt(user.email_enc)
            except Exception:
                pass
        phone_val = None

    avatars_result = await db.execute(
        select(UserAvatar).where(UserAvatar.user_id == user.id).limit(6)
    )
    avatars = [
        AvatarOut(
            id=a.id,
            avatar_url=a.avatar_url,
            created_at=a.created_at,
            is_active=a.is_active,
        )
        for a in avatars_result.scalars().all()
    ]

    # Apply online_visibility privacy
    show_online = True
    if user.id != current_user.id:
        vis = getattr(user, "online_visibility", "all")
        if vis == "nobody":
            show_online = False
        elif vis == "friends_only" and not is_friend:
            show_online = False

    effective_online = user.is_online if show_online else False
    effective_last_seen: Optional[datetime] = None
    if show_online:
        effective_last_seen = user.last_seen
    else:
        # Show "recently" / "long ago" buckets
        if user.last_seen:
            days_ago = (datetime.now(timezone.utc) - user.last_seen).days
            if days_ago < 7:
                # bucket: "был(а) недавно"
                effective_last_seen = datetime.now(timezone.utc) - timedelta(days=1)
            else:
                effective_last_seen = None  # "был(а) давно"

    return ProfileOut(
        id=str(user.id),
        tag_name=user.tag_name,
        name=user.name,
        avatar_url=user.avatar_url,
        avatars=avatars,
        email=email_val,
        phone=phone_val,
        is_online=effective_online,
        last_seen=effective_last_seen,
        is_friend=is_friend,
        pending_request_sent=pending_sent,
        pending_request_received=pending_received,
    )


@app.delete("/friends/{friend_tag}")
async def remove_friend(
        friend_tag: str,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)
    result = await db.execute(select(User).where(User.tag_name == friend_tag))
    other = result.scalars().first()
    if not other:
        raise HTTPException(404, detail="User not found")
    await db.execute(
        delete(Friend).where(
            or_(
                and_(Friend.user_id == current_user.id, Friend.friend_id == other.id),
                and_(Friend.user_id == other.id, Friend.friend_id == current_user.id),
            )
        )
    )
    await db.commit()
    return {"status": "removed"}


@app.get("/friend-requests/received", response_model=List[FriendRequestOut])
async def get_received_friend_requests(
        current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await check_rate(current_user.id)
    result = await db.execute(
        select(FriendRequest, User.tag_name, User.name)
        .join(User, User.id == FriendRequest.from_id)
        .where(
            and_(
                FriendRequest.to_id == current_user.id,
                FriendRequest.status == "pending",
            )
        )
    )
    rows = result.all()
    return [
        FriendRequestOut(
            id=req.id, from_id=str(req.from_id), from_tag=tag, from_name=name
        )
        for req, tag, name in rows
    ]


# ────────────────────────────────────────────────
# Редактирование, удаление, закрепление сообщений
# ────────────────────────────────────────────────


class MessageEditRequest(BaseModel):
    encrypted_content: str
    encrypted_session_keys: Dict[str, str]
    nonce: str


@app.patch("/messages/{message_id}", response_model=Dict[str, Any])
async def edit_message(
        message_id: int,
        body: MessageEditRequest,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)
    result = await db.execute(
        select(Message).where(
            and_(Message.id == message_id, Message.from_id == current_user.id)
        )
    )
    msg = result.scalars().first()
    if not msg:
        raise HTTPException(404, detail="Сообщение не найдено или нет прав")
    edited_at_dt = datetime.now(timezone.utc)
    msg.encrypted_content = body.encrypted_content
    msg.encrypted_session_keys = json.dumps(body.encrypted_session_keys)
    msg.nonce = body.nonce
    msg.edited_at = edited_at_dt
    await db.commit()

    edited_at_str = edited_at_dt.isoformat()

    # Notify via WS
    payload = {
        "type": "message_edited",
        "message_id": message_id,
        "encrypted_content": body.encrypted_content,
        "encrypted_session_keys": body.encrypted_session_keys,
        "nonce": body.nonce,
        "edited_at": edited_at_str,
    }
    if msg.to_id:
        await manager.send_personal_message(msg.to_id, payload)
    await manager.send_personal_message(current_user.id, payload)

    return {
        "status": "edited",
        "edited_at": edited_at_str,
    }


@app.delete("/messages/clear")
async def clear_chat(
        to_tag: str = Query(..., description="Conversation partner tag"),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Delete all messages in the conversation (both sides)."""
    await check_rate(current_user.id)
    result = await db.execute(select(User).where(User.tag_name == to_tag))
    other = result.scalars().first()
    if not other:
        raise HTTPException(404, detail="User not found")
    await db.execute(
        delete(Message).where(
            or_(
                and_(Message.from_id == current_user.id, Message.to_id == other.id),
                and_(Message.from_id == other.id, Message.to_id == current_user.id),
            )
        )
    )
    await db.commit()
    return {"status": "cleared"}


@app.delete("/messages/{message_id}", response_model=Dict[str, str])
async def delete_message(
        message_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)
    result = await db.execute(
        select(Message).where(
            and_(Message.id == message_id, Message.from_id == current_user.id)
        )
    )
    msg = result.scalars().first()
    if not msg:
        raise HTTPException(404, detail="Сообщение не найдено или нет прав")

    msg.is_deleted = True
    await db.commit()

    payload = {"type": "message_deleted", "message_id": message_id}
    if msg.to_id:
        await manager.send_personal_message(msg.to_id, payload)
    await manager.send_personal_message(current_user.id, payload)

    return {"status": "deleted"}


@app.post("/messages/{message_id}/pin", response_model=Dict[str, Any])
async def pin_message(
        message_id: int,
        for_all: bool = Query(True),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)
    result = await db.execute(select(Message).where(Message.id == message_id))
    msg = result.scalars().first()
    if not msg:
        raise HTTPException(404, detail="Сообщение не найдено")

    partner_id = None
    if msg.to_id:
        partner_id = msg.to_id if msg.from_id == current_user.id else msg.from_id

    if for_all:
        if not msg.is_pinned:
            # Считаем сколько уже закреплено в этом чате
            count_q = select(func.count(Message.id)).where(Message.is_pinned == True)
            if partner_id:
                count_q = count_q.where(
                    or_(
                        and_(
                            Message.from_id == current_user.id,
                            Message.to_id == partner_id,
                        ),
                        and_(
                            Message.from_id == partner_id,
                            Message.to_id == current_user.id,
                        ),
                    )
                )
            cnt = (await db.execute(count_q)).scalar() or 0
            if cnt >= 10:
                raise HTTPException(400, detail="Нельзя закрепить более 10 сообщений")
        msg.is_pinned = not msg.is_pinned
        msg.pinned_at = datetime.now(timezone.utc) if msg.is_pinned else None
        await db.commit()

        payload = {
            "type": "message_pinned",
            "message_id": message_id,
            "is_pinned": msg.is_pinned,
            "for_all": True,
        }
        if partner_id:
            await manager.send_personal_message(partner_id, payload)
        await manager.send_personal_message(current_user.id, payload)
        return {"status": "ok", "is_pinned": msg.is_pinned, "for_all": True}
    else:
        # Закрепить только для себя
        existing = await db.execute(
            select(UserPinnedMessage).where(
                and_(
                    UserPinnedMessage.user_id == current_user.id,
                    UserPinnedMessage.message_id == message_id,
                )
            )
        )
        upm = existing.scalars().first()
        if upm:
            await db.delete(upm)
            await db.commit()
            await manager.send_personal_message(
                current_user.id,
                {
                    "type": "message_pinned",
                    "message_id": message_id,
                    "is_pinned": False,
                    "for_all": False,
                },
            )
            return {"status": "ok", "is_pinned": False, "for_all": False}
        else:
            cnt_q = await db.execute(
                select(func.count(UserPinnedMessage.id)).where(
                    UserPinnedMessage.user_id == current_user.id
                )
            )
            if (cnt_q.scalar() or 0) >= 10:
                raise HTTPException(400, detail="Нельзя закрепить более 10 сообщений")
            db.add(UserPinnedMessage(user_id=current_user.id, message_id=message_id))
            await db.commit()
            await manager.send_personal_message(
                current_user.id,
                {
                    "type": "message_pinned",
                    "message_id": message_id,
                    "is_pinned": True,
                    "for_all": False,
                },
            )
            return {"status": "ok", "is_pinned": True, "for_all": False}


@app.get("/messages/pinned/{to_tag}")
async def get_pinned_messages(
        to_tag: str,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Возвращает до 10 закреплённых сообщений в беседе (для всех + только для меня)."""
    await check_rate(current_user.id)
    other_res = await db.execute(select(User).where(User.tag_name == to_tag))
    other = other_res.scalars().first()
    if not other:
        raise HTTPException(404, detail="Пользователь не найден")

    conv_filter = or_(
        and_(Message.from_id == current_user.id, Message.to_id == other.id),
        and_(Message.from_id == other.id, Message.to_id == current_user.id),
    )

    # Для всех
    all_q = await db.execute(
        select(
            Message.id,
            Message.encrypted_content,
            Message.encrypted_session_keys,
            Message.nonce,
            Message.pinned_at,
            User.tag_name.label("from_tag"),
        )
        .join(User, User.id == Message.from_id)
        .where(
            and_(Message.is_pinned == True, Message.is_deleted == False, conv_filter)
        )
        .order_by(Message.pinned_at.asc())
    )
    pinned_all = [
        {
            "id": r.id,
            "encrypted_content": r.encrypted_content,
            "encrypted_session_keys": json.loads(r.encrypted_session_keys),
            "nonce": r.nonce,
            "from_tag": r.from_tag,
            "pinned_at": r.pinned_at.isoformat() if r.pinned_at else "",
            "for_all": True,
        }
        for r in all_q.all()
    ]

    # Только для меня
    me_q = await db.execute(
        select(
            Message.id,
            Message.encrypted_content,
            Message.encrypted_session_keys,
            Message.nonce,
            UserPinnedMessage.pinned_at,
            User.tag_name.label("from_tag"),
        )
        .join(UserPinnedMessage, UserPinnedMessage.message_id == Message.id)
        .join(User, User.id == Message.from_id)
        .where(
            and_(
                UserPinnedMessage.user_id == current_user.id,
                Message.is_deleted == False,
                conv_filter,
            )
        )
        .order_by(UserPinnedMessage.pinned_at.asc())
    )
    me_pinned: Dict[int, Any] = {}
    for r in me_q.all():
        me_pinned[r.id] = {
            "id": r.id,
            "encrypted_content": r.encrypted_content,
            "encrypted_session_keys": json.loads(r.encrypted_session_keys),
            "nonce": r.nonce,
            "from_tag": r.from_tag,
            "pinned_at": r.pinned_at.isoformat() if r.pinned_at else "",
            "for_all": False,
        }

    merged: Dict[int, Any] = {p["id"]: p for p in pinned_all}
    for pid, p in me_pinned.items():
        if pid not in merged:
            merged[pid] = p

    result_list = sorted(merged.values(), key=lambda x: x["pinned_at"])[:10]
    return result_list


@app.post("/messages/{message_id}/react", response_model=Dict[str, Any])
async def react_to_message(
        message_id: int,
        emoji: str = Query(..., max_length=10),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)
    # Check message exists
    msg_check = await db.execute(select(Message.id).where(Message.id == message_id))
    if not msg_check.scalars().first():
        raise HTTPException(404, detail="Сообщение не найдено")

    # Toggle: if reaction exists — remove, else add
    existing = await db.execute(
        select(MessageReaction).where(
            and_(
                MessageReaction.message_id == message_id,
                MessageReaction.user_id == current_user.id,
                MessageReaction.emoji == emoji,
            )
        )
    )
    reaction = existing.scalars().first()
    if reaction:
        await db.delete(reaction)
        action = "removed"
    else:
        db.add(
            MessageReaction(
                message_id=message_id,
                user_id=current_user.id,
                user_tag=current_user.tag_name,
                emoji=emoji,
            )
        )
        action = "added"
    await db.commit()

    # Reload all reactions for this message
    all_r = await db.execute(
        select(MessageReaction).where(MessageReaction.message_id == message_id)
    )
    reactions_map: Dict[str, List[str]] = {}
    for r in all_r.scalars().all():
        reactions_map.setdefault(r.emoji, []).append(r.user_tag)

    payload = {
        "type": "reaction_update",
        "message_id": message_id,
        "reactions": reactions_map,
    }
    msg_row = await db.execute(select(Message).where(Message.id == message_id))
    msg_obj = msg_row.scalars().first()
    if msg_obj and msg_obj.to_id:
        await manager.send_personal_message(msg_obj.to_id, payload)
    await manager.send_personal_message(current_user.id, payload)

    return {"status": action, "reactions": reactions_map}


@app.get("/me", response_model=UserOut)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    return UserOut(
        id=str(current_user.id),
        tag_name=current_user.tag_name,
        name=current_user.name,
        avatar_url=current_user.avatar_url,
    )


@app.patch("/users/me/privacy")
async def update_privacy_settings(
        data: dict = Body(...),  # {"allow_messages_only_from_friends": true/false}
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    if "allow_messages_only_from_friends" in data:
        current_user.allow_messages_only_from_friends = data[
            "allow_messages_only_from_friends"
        ]

    await db.commit()
    await db.refresh(current_user)
    return {"status": "updated"}


@app.patch("/users/me")
async def update_my_profile(
        data: dict = Body(...),  # {"name": "...", "tag_name": "..."}
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)
    if "name" in data:
        name = str(data["name"]).strip()
        if not NAME_REGEX.match(name):
            raise HTTPException(
                status_code=400,
                detail="Имя может содержать только буквы и цифры без пробелов и спецсимволов",
            )
        if contains_bad_words(name):
            raise HTTPException(
                status_code=400, detail="Имя содержит запрещённые слова"
            )
        current_user.name = name

    if "tag_name" in data:
        raw = str(data["tag_name"]).strip()
        if not raw:
            raise HTTPException(status_code=400, detail="Tag обязателен")
        core = raw.lstrip("@")
        if not TAG_CORE_REGEX.match(core):
            raise HTTPException(
                status_code=400,
                detail="Tag может содержать только буквы, цифры и символ _",
            )
        if contains_bad_words(core):
            raise HTTPException(
                status_code=400, detail="Tag содержит запрещённые слова"
            )
        core = core[0].upper() + core[1:]
        normalized_tag = f"@{core}"
        existing = await db.execute(
            select(User).where(
                User.tag_name == normalized_tag, User.id != current_user.id
            )
        )
        if existing.scalars().first():
            raise HTTPException(400, detail="Tag name already taken")
        current_user.tag_name = normalized_tag
    await db.commit()
    await db.refresh(current_user)
    return {"status": "updated"}


@app.post("/users/me/avatars")
async def upload_avatar_file(
        file: UploadFile = File(...),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)

    # Разрешаем только изображения
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400, detail="Можно загружать только изображения"
        )

    # Проверяем размер
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(400, detail="Файл слишком большой")

    # Генерируем уникальное имя
    import os
    import uuid

    filename = f"{uuid.uuid4().hex}_{file.filename}"
    save_path = os.path.join("static/avatars", filename)

    # Сохраняем на диск
    with open(save_path, "wb") as f:
        f.write(contents)

    # Сначала получаем старые аватарки для удаления файлов
    old_avatars_result = await db.execute(
        select(UserAvatar).where(UserAvatar.user_id == current_user.id)
    )
    old_avatars = old_avatars_result.scalars().all()

    # Удаляем старые файлы
    for old_avatar in old_avatars:
        if old_avatar.avatar_url and old_avatar.avatar_url.startswith("/static/avatars/"):
            old_file_path = old_avatar.avatar_url[1:]  # Убираем начальный слэш
            try:
                if os.path.exists(old_file_path):
                    os.remove(old_file_path)
                    print(f"Deleted old avatar file: {old_file_path}")
            except Exception as e:
                print(f"Error deleting old avatar file {old_file_path}: {e}")

    # Удаляем старые записи из БД
    await db.execute(delete(UserAvatar).where(UserAvatar.user_id == current_user.id))

    # Создаём новую запись в БД
    avatar = UserAvatar(
        user_id=current_user.id, avatar_url=f"/static/avatars/{filename}"
    )
    db.add(avatar)

    # Обновляем текущую аватарку пользователя
    current_user.avatar_url = avatar.avatar_url

    await db.commit()
    await db.refresh(avatar)

    # Очищаем осиротевшие файлы аватарок
    await cleanup_orphaned_avatars(db)

    return AvatarOut(
        id=avatar.id,
        avatar_url=avatar.avatar_url,
        created_at=avatar.created_at,
        is_active=avatar.is_active,
    )


@app.delete("/users/me/avatars/{avatar_id}")
async def delete_avatar(
        avatar_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)
    result = await db.execute(
        select(UserAvatar).where(
            and_(UserAvatar.id == avatar_id, UserAvatar.user_id == current_user.id)
        )
    )
    avatar = result.scalars().first()
    if not avatar:
        raise HTTPException(404, detail="Avatar not found")

    # Удаляем файл из папки
    if avatar.avatar_url and avatar.avatar_url.startswith("/static/avatars/"):
        file_path = avatar.avatar_url[1:]  # Убираем начальный слэш
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Deleted avatar file: {file_path}")
        except Exception as e:
            print(f"Error deleting avatar file {file_path}: {e}")

    if current_user.avatar_url == avatar.avatar_url:
        avatars_result = await db.execute(
            select(UserAvatar)
            .where(
                and_(UserAvatar.user_id == current_user.id, UserAvatar.id != avatar_id)
            )
            .limit(1)
        )
        next_avatar = avatars_result.scalars().first()
        current_user.avatar_url = next_avatar.avatar_url if next_avatar else None

    await db.execute(delete(UserAvatar).where(UserAvatar.id == avatar_id))
    await db.commit()

    # Очищаем осиротевшие файлы аватарок
    await cleanup_orphaned_avatars(db)

    return {"status": "deleted"}


@app.patch("/users/me/avatars/{avatar_id}/set-active")
async def set_active_avatar(
        avatar_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await check_rate(current_user.id)
    result = await db.execute(
        select(UserAvatar).where(
            and_(UserAvatar.id == avatar_id, UserAvatar.user_id == current_user.id)
        )
    )
    avatar = result.scalars().first()
    if not avatar:
        raise HTTPException(404, detail="Avatar not found")
    current_user.avatar_url = avatar.avatar_url
    await db.commit()
    return {"status": "updated"}


# ────────────────────────────────────────────────
# Очистка осиротевших аватарок
# ────────────────────────────────────────────────
async def cleanup_orphaned_avatars(db: AsyncSession):
    """Удаляет файлы аватарок, у которых нет записей в БД"""
    try:
        # Получаем все пути к аватаркам из БД
        result = await db.execute(select(UserAvatar.avatar_url))
        db_avatar_urls = set(result.scalars().all())

        # Получаем все файлы в папке аватарок
        if os.path.exists(AVATAR_DIR):
            for filename in os.listdir(AVATAR_DIR):
                file_path = os.path.join(AVATAR_DIR, filename)
                if os.path.isfile(file_path):
                    db_url = f"/static/avatars/{filename}"
                    if db_url not in db_avatar_urls:
                        try:
                            os.remove(file_path)
                            print(f"Cleaned up orphaned avatar: {file_path}")
                        except Exception as e:
                            print(f"Error cleaning up orphaned avatar {file_path}: {e}")
    except Exception as e:
        print(f"Error in cleanup_orphaned_avatars: {e}")


@app.post("/admin/cleanup-avatars")
async def admin_cleanup_avatars(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Административная очистка осиротевших аватарок"""
    # Проверяем, что пользователь - администратор
    if current_user.tag_name != ADMIN_TAG:
        raise HTTPException(403, detail="Access denied")

    await cleanup_orphaned_avatars(db)
    return {"status": "completed", "message": "Orphaned avatars cleaned up"}


# ────────────────────────────────────────────────
# Загрузка медиафайлов для сообщений
# ────────────────────────────────────────────────
@app.post("/messages/upload")
async def upload_message_file(
        file: UploadFile = File(...),
        is_video_note: bool = Query(False, description="Отметить как видеокружок"),
        current_user: User = Depends(get_current_user),
):
    await check_rate(current_user.id)

    content_type = file.content_type or ""

    # Определяем тип вложения
    if content_type.startswith("image/"):
        attachment_type = "image"
        max_size = 10 * 1024 * 1024  # 10 MB
    elif content_type.startswith("video/"):
        attachment_type = "video_note" if is_video_note else "video"
        max_size = 100 * 1024 * 1024  # 100 MB
    elif content_type.startswith("audio/"):
        attachment_type = "audio"
        max_size = 64 * 1024 * 1024  # 64 MB (~1 час при 128 kbps)
    else:
        raise HTTPException(
            status_code=400,
            detail="Недопустимый тип файла. Разрешены: изображения, видео, аудио.",
        )

    contents = await file.read()
    if len(contents) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"Файл слишком большой. Максимум: {max_size // (1024 * 1024)} МБ",
        )

    os.makedirs("static/uploads", exist_ok=True)

    original_name = file.filename or "file"
    ext = os.path.splitext(original_name)[1] or ""
    filename = f"{uuid4().hex}{ext}"
    save_path = os.path.join("static/uploads", filename)

    with open(save_path, "wb") as f:
        f.write(contents)

    return {
        "url": f"/static/uploads/{filename}",
        "type": attachment_type,
        "original_name": original_name,
        "size": len(contents),
    }


# LiveKit токены для видеозвонков
class LiveKitTokenRequest(BaseModel):
    room_name: str
    user_identity: str
    can_publish: bool = True
    can_subscribe: bool = True


@app.post("/api/livekit/token")
async def generate_livekit_token(request: LiveKitTokenRequest):
    try:
        from livekit.api import AccessToken, VideoGrants

        # Настройки LiveKit сервера
        api_key = os.getenv("LIVEKIT_API_KEY", "devkey")
        api_secret = os.getenv("LIVEKIT_API_SECRET", "secret")
        livekit_url = os.getenv("LIVEKIT_URL", "ws://localhost:7880").replace("http://", "ws://").replace("https://",
                                                                                                          "wss://")

        print(
            f"🎬 LiveKit token request: room={request.room_name}, identity={request.user_identity}, can_publish={request.can_publish}, can_subscribe={request.can_subscribe}")

        # Создание токена
        token = AccessToken(api_key, api_secret)
        grants = VideoGrants(
            room=request.room_name,
            room_join=True,
            can_publish=request.can_publish,
            can_subscribe=request.can_subscribe,
        )
        token = token.with_identity(request.user_identity).with_grants(grants)

        jwt_token = token.to_jwt()

        print(f"🎬 LiveKit token generated for {request.user_identity} in room {request.room_name}")

        return {
            "token": jwt_token,
            "url": livekit_url,
            "room_name": request.room_name,
            "identity": request.user_identity
        }

    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="LiveKit SDK не установлен. Установите: pip install livekit-api"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка генерации токена: {str(e)}"
        )


# ────────────────────────────────────────────────
# Импорт чатов из Telegram
# ────────────────────────────────────────────────
class TelegramImportRequestCreate(BaseModel):
    chat_data: List[Dict[str, Any]]  # JSON с данными чата
    user_tag: str  # tag пользователя для импорта


class TelegramMessage(BaseModel):
    id: int
    text: Optional[str] = None
    date: str  # ISO дата
    from_user: Optional[str] = None  # username в Telegram
    to_user: Optional[str] = None  # username в Telegram
    media_type: Optional[str] = None  # photo, video, document, etc.
    media_url: Optional[str] = None


@app.post("/telegram/import")
async def import_telegram_chat(
        import_request: TelegramImportRequestCreate,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Импорт чата из Telegram с шифрованием"""
    await check_rate(current_user.id)

    # Проверяем, что пользователь с указанным tag существует
    target_result = await db.execute(select(User).where(User.tag_name == import_request.user_tag))
    target_user = target_result.scalars().first()

    if not target_user:
        raise HTTPException(404, detail="Пользователь с указанным tag не найден")

    # Проверяем, что пользователи являются друзьями
    if target_user.id != current_user.id:  # Если импорт не для себя
        friend_check = await db.execute(
            select(Friend).where(
                or_(
                    and_(Friend.user_id == current_user.id, Friend.friend_id == target_user.id),
                    and_(Friend.user_id == target_user.id, Friend.friend_id == current_user.id),
                )
            )
        )

        if not friend_check.scalars().first():
            raise HTTPException(
                403,
                detail="Можно импортировать чаты только с пользователями, которые находятся в списке друзей"
            )

    imported_count = 0
    errors = []

    for msg_data in import_request.chat_data:
        try:
            # Валидация данных сообщения
            telegram_msg = TelegramMessage(**msg_data)

            # Проверяем, что сообщение еще не импортировано
            existing_msg = await db.execute(
                select(Message).where(
                    and_(
                        Message.from_id == current_user.id,
                        Message.to_id == target_user.id,
                        Message.timestamp == datetime.fromisoformat(telegram_msg.date.replace('Z', '+00:00'))
                    )
                )
            )

            if existing_msg.scalars().first():
                continue  # Пропускаем уже импортированные сообщения

            # Создаем зашифрованное сообщение (клиент должен предоставить зашифрованные данные)
            # В реальности клиент должен зашифровать сообщение с ключами получателя
            encrypted_content = telegram_msg.text or "[Media]"

            # Создаем сообщение в БД
            message = Message(
                from_id=current_user.id,
                to_id=target_user.id,
                encrypted_content=encrypted_content,  # В реальности это будет зашифрованный контент
                encrypted_session_keys=json.dumps({}),  # Клиент предоставит зашифрованные ключи
                nonce=secrets.token_hex(12),  # В реальности клиент предоставит nonce
                version="v1",
                suspicious=False,
                attachment_url=telegram_msg.media_url,
                attachment_type=telegram_msg.media_type,
                timestamp=datetime.fromisoformat(telegram_msg.date.replace('Z', '+00:00')),
            )

            db.add(message)
            imported_count += 1

        except Exception as e:
            errors.append(f"Ошибка импорта сообщения {msg_data.get('id', 'unknown')}: {str(e)}")
            continue

    await db.commit()

    return {
        "status": "import_completed",
        "imported_messages": imported_count,
        "errors": errors,
        "target_user": import_request.user_tag
    }


@app.get("/telegram/import/status")
async def get_import_status(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Получение статуса импортированных чатов"""
    await check_rate(current_user.id)

    # Получаем количество импортированных сообщений
    imported_count = await db.execute(
        select(func.count(Message.id)).where(Message.from_id == current_user.id)
    )

    # Получаем список друзей для возможности импорта
    friends_result = await db.execute(
        select(User.tag_name).select_from(Friend)
        .join(User, User.id == Friend.friend_id)
        .where(Friend.user_id == current_user.id)
    )

    friend_tags = [row[0] for row in friends_result.all()]

    return {
        "total_imported_messages": imported_count.scalar() or 0,
        "available_for_import": friend_tags,
        "import_instructions": {
            "requirements": [
                "Пользователь должен иметь тот же tag_name, что и в Telegram",
                "Пользователь должен быть в списке друзей",
                "Сообщения должны быть зашифрованы ключами получателя"
            ],
            "format": "JSON с массивом сообщений Telegram",
            "encryption": "E2EE с использованием X25519 ключей"
        }
    }


# ────────────────────────────────────────────────
# Управление устройствами
# ────────────────────────────────────────────────

@app.post("/api/devices/register", response_model=DeviceOut)
async def register_device(
        device_request: DeviceRegisterRequest,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Регистрация нового устройства с созданием уведомления о подтверждении"""
    await check_rate(current_user.id)

    # Проверяем, существует ли уже устройство с таким fingerprint
    existing_device = await db.execute(
        select(Device).where(Device.device_fingerprint == device_request.device_fingerprint)
    )
    if existing_device.scalars().first():
        raise HTTPException(400, detail="Устройство с таким fingerprint уже зарегистрировано")

    # Создаем новое устройство
    confirmation_token = secrets.token_urlsafe(32)
    device = Device(
        user_id=current_user.id,
        device_name=device_request.device_name,
        device_fingerprint=device_request.device_fingerprint,
        public_key_x25519=device_request.public_key_x25519,
        confirmation_token=confirmation_token,
        confirmation_requested_at=datetime.now(timezone.utc),
        is_confirmed=False,
    )

    db.add(device)
    await db.commit()
    await db.refresh(device)

    # Создаем уведомление о подтверждении
    notification = DeviceConfirmationNotification(
        user_id=current_user.id,
        device_id=device.id,
        device_name=device.device_name,
        device_fingerprint=device.device_fingerprint,
        confirmation_token=confirmation_token,
        status="pending",
    )

    db.add(notification)
    await db.commit()

    return DeviceOut(
        id=str(device.id),
        device_name=device.device_name,
        device_fingerprint=device.device_fingerprint,
        public_key_x25519=device.public_key_x25519,
        is_confirmed=device.is_confirmed,
        last_active=device.last_active,
        created_at=device.created_at,
    )


@app.get("/api/devices", response_model=List[DeviceOut])
async def get_user_devices(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Получение списка всех устройств пользователя"""
    await check_rate(current_user.id)

    devices_result = await db.execute(
        select(Device).where(Device.user_id == current_user.id).order_by(Device.created_at.desc())
    )
    devices = devices_result.scalars().all()

    return [
        DeviceOut(
            id=str(device.id),
            device_name=device.device_name,
            device_fingerprint=device.device_fingerprint,
            public_key_x25519=device.public_key_x25519,
            is_confirmed=device.is_confirmed,
            last_active=device.last_active,
            created_at=device.created_at,
        )
        for device in devices
    ]


@app.get("/api/devices/notifications", response_model=List[DeviceConfirmationNotificationOut])
async def get_device_notifications(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Получение уведомлений о подтверждении устройств"""
    await check_rate(current_user.id)

    notifications_result = await db.execute(
        select(DeviceConfirmationNotification)
        .where(DeviceConfirmationNotification.user_id == current_user.id)
        .where(DeviceConfirmationNotification.status == "pending")
        .order_by(DeviceConfirmationNotification.created_at.desc())
    )
    notifications = notifications_result.scalars().all()

    return [
        DeviceConfirmationNotificationOut(
            id=notification.id,
            device_id=str(notification.device_id),
            device_name=notification.device_name,
            device_fingerprint=notification.device_fingerprint,
            confirmation_token=notification.confirmation_token,
            status=notification.status,
            created_at=notification.created_at,
        )
        for notification in notifications
    ]


@app.post("/api/devices/confirm")
async def confirm_device(
        confirmation_request: DeviceConfirmationRequest,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Подтверждение или отклонение нового устройства"""
    await check_rate(current_user.id)

    # Находим уведомление
    notification_result = await db.execute(
        select(DeviceConfirmationNotification)
        .where(DeviceConfirmationNotification.confirmation_token == confirmation_request.confirmation_token)
        .where(DeviceConfirmationNotification.user_id == current_user.id)
        .where(DeviceConfirmationNotification.status == "pending")
    )
    notification = notification_result.scalars().first()

    if not notification:
        raise HTTPException(404, detail="Уведомление не найдено или уже обработано")

    # Находим устройство
    device_result = await db.execute(
        select(Device).where(Device.id == notification.device_id)
    )
    device = device_result.scalars().first()

    if not device:
        raise HTTPException(404, detail="Устройство не найдено")

    if confirmation_request.action == "approve":
        # Подтверждаем устройство
        device.is_confirmed = True
        device.confirmed_at = datetime.now(timezone.utc)
        device.confirmation_token = None
        notification.status = "approved"
        notification.resolved_at = datetime.now(timezone.utc)

        await db.commit()

        # Создаем системное уведомление о подтверждении устройства
        await create_system_notification(
            user_id=current_user.id,
            notification_type="system",
            title="Устройство подтверждено",
            message=f"Устройство '{device.device_name}' успешно подтверждено",
            data=json.dumps({
                "device_id": str(device.id),
                "device_name": device.device_name,
                "device_fingerprint": device.device_fingerprint
            }),
            db=db
        )

        # Отправляем WebSocket уведомление об одобрении
        await manager.send_personal_message(
            current_user.id,
            {
                "type": "device_confirmation_approved",
                "device_id": str(device.id),
                "device_name": device.device_name,
                "device_fingerprint": device.device_fingerprint,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

        return {"status": "approved", "message": "Устройство успешно подтверждено"}

    elif confirmation_request.action == "reject":
        # Отклоняем устройство - удаляем его
        notification.status = "rejected"
        notification.resolved_at = datetime.now(timezone.utc)

        await db.delete(device)
        await db.commit()

        return {"status": "rejected", "message": "Устройство отклонено и удалено"}

    else:
        raise HTTPException(400, detail="Неверное действие. Используйте 'approve' или 'reject'")


@app.post("/import-telegram-html")
async def import_telegram_html(
        chat_id: str = Form(...),
        telegram_name: str = Form(...),
        html_file: UploadFile = File(...),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Импорт чата из HTML файла Telegram"""
    await check_rate(current_user.id)

    # Валидация файла
    if not html_file.filename.endswith('.html'):
        raise HTTPException(400, detail="Только HTML файлы поддерживаются")

    if html_file.size > 10 * 1024 * 1024:  # 10MB
        raise HTTPException(400, detail="Файл слишком большой. Максимальный размер: 10MB")

    # Проверяем участие пользователя в переписке (должны быть друзья)
    friendship_result = await db.execute(
        select(Friend).where(
            and_(
                Friend.user_id == current_user.id,
                Friend.friend_id == uuid.UUID(chat_id)
            )
        )
    )
    friendship = friendship_result.scalars().first()

    if not friendship:
        # Проверяем обратную дружбу
        friendship_result = await db.execute(
            select(Friend).where(
                and_(
                    Friend.user_id == uuid.UUID(chat_id),
                    Friend.friend_id == current_user.id
                )
            )
        )
        friendship = friendship_result.scalars().first()

    if not friendship:
        raise HTTPException(403, detail="Вы можете импортировать чат только с друзьями")

    # Определяем второго участника
    other_user_id = uuid.UUID(chat_id)

    # Сохраняем HTML файл во временную директорию
    temp_dir = "static/tmp/telegram_imports"
    os.makedirs(temp_dir, exist_ok=True)

    file_path = os.path.join(temp_dir, f"{uuid.uuid4()}.html")
    print(f"📁 DEBUG: Saving HTML file to: {file_path}")

    try:
        # Читаем и сохраняем файл
        content = await html_file.read()
        print(f"📁 DEBUG: File size read: {len(content)} bytes")
        with open(file_path, 'wb') as f:
            f.write(content)

        print(f"📁 DEBUG: File saved successfully, exists: {os.path.exists(file_path)}")

        # Создаем запрос на импорт
        import_request = TelegramImportRequest(
            requester_id=current_user.id,
            target_user_id=uuid.UUID(chat_id),  # Здесь передаем ID второго пользователя
            telegram_name=telegram_name,
            status="pending"
        )
        db.add(import_request)
        await db.commit()

        print(f"📁 DEBUG: Import request created with ID: {import_request.id}")
        print(f"📁 DEBUG: File path stored for request: {file_path}")

        # Сохраняем путь к файлу в запросе (нужно добавить поле в модель)
        # Временно сохраняем в временном хранилище
        import_file_paths[str(import_request.id)] = file_path
        print(f"📁 DEBUG: File path stored in temp storage: {import_file_paths.get(str(import_request.id))}")

        # Отправляем WebSocket уведомление второму участнику
        logging.info(f"Sending telegram import request to user: {other_user_id}")

        # Создаем системное уведомление
        await create_system_notification(
            user_id=other_user_id,
            notification_type="active",
            title="Запрос на импорт Telegram",
            message=f"{current_user.name or current_user.tag_name} хочет импортировать чат из Telegram",
            data=json.dumps({
                "import_id": str(import_request.id),
                "requester_name": current_user.name or current_user.tag_name,
                "chat_name": f"Чат с {current_user.tag_name}",
                "chat_id": str(other_user_id)
            }),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            db=db
        )

        logging.info("Telegram import request sent successfully")

        return {
            "requires_confirmation": True,
            "import_id": str(import_request.id),
            "message": "Запрос отправлен на подтверждение второму участнику"
        }

    except Exception as e:
        # Удаляем временный файл при ошибке
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(500, detail=f"Ошибка сохранения файла: {str(e)}")


async def create_system_notification(
        user_id: uuid.UUID,
        notification_type: str,
        title: str,
        message: str,
        data: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        db: AsyncSession = None
):
    """Создание системного уведомления"""
    if db is None:
        from app import get_db
        async for session in get_db():  # <- используем async for
            db = session
            break  # берем первый объект сессии

    notification = SystemNotification(
        user_id=user_id,
        type=notification_type,
        title=title,
        message=message,
        data=data,
        expires_at=expires_at
    )
    db.add(notification)
    await db.commit()

    # Отправляем WebSocket уведомление
    await manager.send_personal_message(
        str(user_id),
        {
            "type": "system_notification",
            "notification": {
                "id": notification.id,
                "type": notification_type,
                "title": title,
                "message": message,
                "data": data,
                "created_at": notification.created_at.isoformat()
            }
        }
    )


@app.post("/import-telegram-html/{import_id}/approve")
async def approve_telegram_import(
        import_id: str,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Подтверждение импорта Telegram"""
    await check_rate(current_user.id)

    print(f"📁 DEBUG: Approving import request {import_id}")
    print(f"📁 DEBUG: Available file paths: {list(import_file_paths.keys())}")

    # Находим запрос на импорт
    import_result = await db.execute(
        select(TelegramImportRequest)
        .where(TelegramImportRequest.id == import_id)
        .where(TelegramImportRequest.status == "pending")
    )
    import_request = import_result.scalars().first()
    if not import_request:
        raise HTTPException(404, detail="Запрос на импорт не найден")

    # Проверяем что текущий пользователь является целевым пользователем
    if import_request.target_user_id != current_user.id:
        raise HTTPException(403, detail="Только целевой пользователь может подтвердить импорт")

    # Обновляем статус запроса
    import_request.status = "approved"
    await db.commit()

    # Получаем путь к файлу из временного хранилища
    file_path = import_file_paths.get(import_id)
    print(f"📁 DEBUG: Retrieved file path for import {import_id}: {file_path}")
    print(f"📁 DEBUG: File exists: {os.path.exists(file_path) if file_path else 'No path'}")

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(404, detail=f"HTML файл не найден: {file_path}")

    # Запускаем импорт в фоне
    import_id_str = str(import_request.id)
    telegram_name = import_request.telegram_name
    target_user_id_str = str(import_request.target_user_id)  # Тот кто подтверждает
    requester_user_id = import_request.requester_id  # Тот кто запрашивал

    print(f"📁 DEBUG: Import approval - requester: {requester_user_id}, target: {target_user_id_str}")

    await process_telegram_import(import_id_str, telegram_name, target_user_id_str, requester_user_id, db, file_path)

    return {"status": "approved", "message": "Импорт начат"}


@app.post("/import-telegram-html/{import_id}/reject")
async def reject_telegram_import(
        import_id: str,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Отклонение импорта Telegram"""
    await check_rate(current_user.id)

    # Находим запрос на импорт
    import_result = await db.execute(
        select(TelegramImportRequest)
        .where(TelegramImportRequest.id == import_id)
        .where(TelegramImportRequest.status == "pending")
    )
    import_request = import_result.scalars().first()
    if not import_request:
        raise HTTPException(404, detail="Запрос на импорт не найден")

    # Проверяем что текущий пользователь является целевым пользователем
    if import_request.target_user_id != current_user.id:
        raise HTTPException(403, detail="Только целевой пользователь может отклонить импорт")

    # Обновляем статус запроса
    import_request.status = "rejected"
    await db.commit()

    # Очищаем путь к файлу из временного хранилища
    if import_id in import_file_paths:
        file_path = import_file_paths.pop(import_id)
        print(f"📁 DEBUG: Removed file path for rejected import {import_id}: {file_path}")
        # Удаляем файл
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"📁 DEBUG: Deleted file: {file_path}")

    # Отправляем уведомление об отклонении
    await manager.send_personal_message(
        str(import_request.requester_id),
        {
            "type": "telegram_import_progress",
            "status": "rejected",
            "error": "Импорт отклонен вторым участником"
        }
    )

    return {"status": "rejected", "message": "Импорт отклонен"}


@app.get("/import-telegram-html/{import_id}/progress")
async def get_telegram_import_progress(
        import_id: str,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Получение прогресса импорта"""
    await check_rate(current_user.id)

    # Находим запрос на импорт
    import_result = await db.execute(
        select(TelegramImportRequest)
        .where(TelegramImportRequest.id == import_id)
    )
    import_request = import_result.scalars().first()
    if not import_request:
        raise HTTPException(404, detail="Запрос на импорт не найден")

    # Проверяем что пользователь участвует в импорте
    if (import_request.requester_id != current_user.id and import_request.target_user_id != current_user.id):
        raise HTTPException(403, detail="Доступ запрещен")

    return TelegramImportProgress(
        import_id=import_id,
        status=import_request.status,
        total=import_request.total_messages or 0,
        processed=import_request.processed_messages or 0,
        percentage=round((import_request.processed_messages or 0) / max(import_request.total_messages or 1, 1) * 100,
                         2),
        imported=import_request.imported_messages,
        chat_id=str(import_request.target_user_id),
        error=import_request.error_message
    )


async def process_telegram_import(
        import_id: str,
        telegram_name: str,
        target_user_id: str,
        user_id: uuid.UUID,
        db: AsyncSession,
        file_path: str
):
    print(f"📁 DEBUG: Starting process_telegram_import with file_path: {file_path}")
    print(f"📁 DEBUG: File exists: {os.path.exists(file_path)}")
    print(f"📁 DEBUG: user_id: {user_id}")
    print(f"📁 DEBUG: target_user_id: {target_user_id}")
    print(f"📁 DEBUG: telegram_name: {telegram_name}")

    import_request = None
    try:
        # === 1. Получаем import request ===
        import_request = (
            await db.execute(
                select(TelegramImportRequest).where(TelegramImportRequest.id == import_id)
            )
        ).scalars().first()

        if not import_request:
            return

        # === 2. Получаем target_user ===
        target_user_uuid = uuid.UUID(target_user_id)
        target_user = (
            await db.execute(
                select(User).where(User.id == target_user_uuid)
            )
        ).scalars().first()

        if not target_user:
            print(f"📁 DEBUG: Target user not found with ID: {target_user_uuid}")
            return

        print(f"📁 DEBUG: Target user found: {target_user.name}")
        other_user_id = target_user.id

        # Проверяем что пользователь не импортирует чат сам с собой
        if user_id == other_user_id:
            print(f"📁 DEBUG: ERROR: User trying to import chat with themselves!")
            import_request.status = "failed"
            import_request.error_message = "Нельзя импортировать чат сам с собой"
            await db.commit()
            return

        print(f"📁 DEBUG: Final user mapping: requester={user_id} -> target={other_user_id}")

        import_request.status = "processing"
        await db.commit()

        # === 3. Используем переданный файл ===
        html_file_path = file_path
        print(f"📁 DEBUG: Using HTML file path: {html_file_path}")
        print(f"📁 DEBUG: File exists: {os.path.exists(html_file_path)}")

        if not os.path.exists(html_file_path):
            import_request.status = "failed"
            import_request.error_message = f"HTML файл не найден: {html_file_path}"
            await db.commit()
            return

        # === 4. Читаем HTML ===
        with open(html_file_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "lxml")

        messages = soup.find_all("div", class_="message")
        total = len(messages)
        print(f"📁 DEBUG: Found {total} messages in HTML file")

        if total == 0:
            print("📁 DEBUG: No messages found in HTML - checking structure...")
            all_divs = soup.find_all("div")
            print(f"📁 DEBUG: Total divs found: {len(all_divs)}")
            classes = set()
            for div in all_divs[:10]:
                if div.get('class'):
                    classes.update(div.get('class'))
            print(f"📁 DEBUG: CSS classes found: {classes}")

        processed = 0
        imported = 0

        import_request.total_messages = total
        await db.commit()

        # === 5. Подготавливаем устройства (ОДИН РАЗ) ===
        sender_devices = (
            await db.execute(select(Device).where(Device.user_id == user_id))
        ).scalars().all()

        recipient_devices = (
            await db.execute(select(Device).where(Device.user_id == other_user_id))
        ).scalars().all()

        # === 6. Обработка сообщений ===
        BATCH_SIZE = 50
        batch_objects = []
        seen_hashes = set()

        print(f"📁 DEBUG: Starting to process {total} messages...")
        print(f"📁 DEBUG: Sender devices: {len(sender_devices)}, Recipient devices: {len(recipient_devices)}")

        # Очищаем старые сообщения с ENCRYPTED_PLACEHOLDER для этой пары пользователей
        old_placeholder_msgs = await db.execute(
            select(Message).where(
                and_(
                    or_(
                        and_(Message.from_id == user_id, Message.to_id == other_user_id),
                        and_(Message.from_id == other_user_id, Message.to_id == user_id)
                    ),
                    Message.encrypted_content == "ENCRYPTED_PLACEHOLDER"
                )
            )
        )
        old_msgs = old_placeholder_msgs.scalars().all()
        if old_msgs:
            print(f"📁 DEBUG: Cleaning up {len(old_msgs)} old placeholder messages")
            for old_msg in old_msgs:
                await db.delete(old_msg)
            await db.commit()
            print(f"📁 DEBUG: Cleaned up old placeholder messages")

        if total == 0:
            print("📁 DEBUG: WARNING - No messages to import!")
            return

        for i, msg_div in enumerate(messages):
            processed += 1

            # === текст ===
            text_div = msg_div.find("div", class_="text")
            if not text_div:
                if processed % 100 == 0:
                    print(f"📁 DEBUG: Processed {processed}/{total} messages, no text found")
                continue

            text = text_div.get_text(strip=True)
            if not text:
                if processed % 100 == 0:
                    print(f"📁 DEBUG: Processed {processed}/{total} messages, empty text")
                continue

            # === дата ===
            date_div = msg_div.find("div", class_="date")
            if not date_div:
                if processed % 100 == 0:
                    print(f"📁 DEBUG: Processed {processed}/{total} messages, no date found")
                continue

            # === автор ===
            from_div = msg_div.find("div", class_="from_name")
            if not from_div:
                # Если нет имени автора, это сообщение от текущего пользователя (свои сообщения в Telegram)
                if processed % 100 == 0:
                    print(f"📁 DEBUG: Processed {processed}/{total} messages, treating as own message (no author)")

                author = "own_message"  # Маркируем как свое сообщение
                sender_id = user_id
                receiver_id = other_user_id
            else:
                author = from_div.get_text(strip=True)
                # === кто отправитель ===
                if author.strip().lower() == telegram_name.strip().lower():
                    sender_id = user_id
                    receiver_id = other_user_id
                else:
                    sender_id = other_user_id
                    receiver_id = user_id

            text = text_div.get_text(" ", strip=True)
            text = " ".join(text.split())

            # Debug лог для первых нескольких успешных сообщений
            if imported <= 3:
                print(f"📁 DEBUG: SUCCESS message #{imported}: author='{author}', text='{text[:50]}...'")
                print(f"📁 DEBUG: Message direction: {sender_id} -> {receiver_id}")

            if not text:
                continue

            # === фильтр мусора ===
            if any(x in text for x in [
                "Not included", "Photo", "Video", "Sticker",
                "GIF", "Incoming", "Outgoing", "Missed"
            ]):
                continue

            # === дата ===
            try:
                date_title = date_div.get("title", "")
                print(f"📁 DEBUG: Raw date title: '{date_title}'")

                # Парсим формат DD.MM.YYYY HH:MM:SS UTC+03:00
                # Пример: '09.03.2026 21:21:43 UTC+03:00'
                if "UTC+03:00" in date_title:
                    # Убираем UTC+03:00 и парсим как локальное время
                    date_part = date_title.replace(" UTC+03:00", "")
                    created_at = datetime.strptime(date_part, "%d.%m.%Y %H:%M:%S")
                    # Конвертируем в UTC+3 timezone
                    created_at = created_at.replace(tzinfo=timezone(timedelta(hours=3)))
                else:
                    # Fallback на старый метод
                    created_at = datetime.fromisoformat(date_title.replace("Z", "+00:00"))

                print(f"📁 DEBUG: Parsed date: {created_at}")
            except Exception as e:
                print(f"📁 DEBUG: Date parse error: {e}")
                created_at = datetime.now(timezone.utc)

            # === дедупликация ===
            hash_key = f"{sender_id}:{created_at}:{text}"
            if hash_key in seen_hashes:
                if imported <= 5:  # Логируем первые дубликаты
                    print(f"📁 DEBUG: DUPLICATE message with hash: {hash_key}")
                continue
            seen_hashes.add(hash_key)

            # Проверяем есть ли уже такое сообщение в БД
            existing_msg = await db.execute(
                select(Message).where(
                    and_(
                        Message.from_id == sender_id,
                        Message.to_id == receiver_id,
                        Message.timestamp == created_at
                    )
                )
            )
            if existing_msg.scalars().first():
                if imported <= 5:  # Логируем первые конфликты с БД
                    print(f"📁 DEBUG: CONFLICT with existing message in DB")
                continue

            # === Генерируем E2EE данные для импортированного сообщения ===
            try:
                # Получаем устройства получателя
                recipient_devices_result = await db.execute(
                    select(Device).where(
                        and_(
                            Device.user_id == receiver_id,
                            Device.is_confirmed == True
                        )
                    )
                )
                recipient_devices = recipient_devices_result.scalars().all()

                # Получаем устройства отправителя
                sender_devices_result = await db.execute(
                    select(Device).where(
                        and_(
                            Device.user_id == sender_id,
                            Device.is_confirmed == True
                        )
                    )
                )
                sender_devices = sender_devices_result.scalars().all()

                all_devices = list(recipient_devices) + list(sender_devices)

                if all_devices:
                    # Генерируем сессионный ключ и IV
                    session_key = os.urandom(32)
                    iv = os.urandom(12)

                    # Шифруем текст AES-GCM
                    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                    aesgcm = AESGCM(session_key)
                    ciphertext = aesgcm.encrypt(iv, text.encode(), None)

                    # Кодируем в base64
                    import base64
                    iv_b64 = base64.b64encode(iv).decode()
                    ciphertext_b64 = base64.b64encode(ciphertext).decode()
                    encrypted_content = f"{iv_b64}.{ciphertext_b64}"

                    # Шифруем сессионный ключ для каждого устройства
                    encrypted_session_keys = {}

                    for device in all_devices:
                        try:
                            print(
                                f"📁 DEBUG: Processing device {device.id}, key length: {len(device.public_key_x25519) if device.public_key_x25519 else 0}")
                            # Импортируем публичный ключ устройства
                            pub_key_data = base64.b64decode(device.public_key_x25519)

                            if len(pub_key_data) == 65:
                                # P-256 ключ (старый формат)
                                print(f"📁 DEBUG: Using P-256 key for device {device.id}")
                                from cryptography.hazmat.primitives.asymmetric import ec
                                from cryptography.hazmat.primitives.kdf.hkdf import HKDF
                                from cryptography.hazmat.primitives import hashes

                                recipient_pub = ec.EllipticCurvePublicKey.from_encoded_point(
                                    ec.SECP256R1(), pub_key_data
                                )

                                # Генерируем временную пару ключей
                                ephemeral_private = ec.generate_private_key(ec.SECP256R1())
                                ephemeral_public = ephemeral_private.private_numbers().public_key

                                # Вычисляем shared secret
                                shared_key = ephemeral_private.exchange(
                                    ec.ECDH(), recipient_pub
                                )

                                # Выводим публичный ключ
                                epk_bytes = ephemeral_public.public_numbers().encode_point()

                                # Derive wrapping key
                                hkdf = HKDF(
                                    algorithm=hashes.SHA256(),
                                    length=32,
                                    salt=None,
                                    info=b'encryption',
                                )
                                wrap_key = hkdf.derive(shared_key)

                                # Шифруем сессионный ключ
                                iv2 = os.urandom(12)
                                aesgcm2 = AESGCM(wrap_key)
                                wrapped_key = aesgcm2.encrypt(iv2, session_key, None)

                                iv2_b64 = base64.b64encode(iv2).decode()
                                epk_b64 = base64.b64encode(epk_bytes).decode()
                                wrapped_b64 = base64.b64encode(wrapped_key).decode()

                                encrypted_session_keys[str(device.id)] = f"{epk_b64}.{iv2_b64}.{wrapped_b64}"
                                print(f"📁 DEBUG: Successfully encrypted for device {device.id}")

                            else:
                                # RSA ключ или другой формат - пропускаем для импорта
                                print(
                                    f"📁 DEBUG: Skipping non-P256 key for device {device.id}, length: {len(pub_key_data)}")
                                continue

                        except Exception as e:
                            print(f"📁 DEBUG: Failed to encrypt for device {device.id}: {e}")
                            continue

                    nonce = base64.b64encode(os.urandom(8)).decode()
                    version = "v1"

                    print(f"📁 DEBUG: Generated E2EE for {len(encrypted_session_keys)} devices")

                else:
                    # Нет устройств - используем заглушку
                    encrypted_content = "imported_message_fallback"
                    encrypted_session_keys = {}
                    nonce = "imported_" + str(uuid.uuid4())[:8]
                    version = "imported"
                    print(f"📁 DEBUG: No devices found, using fallback")

            except Exception as e:
                print(f"📁 DEBUG: E2EE generation failed: {e}")
                # Fallback на заглушку
                encrypted_content = "imported_message_fallback"
                encrypted_session_keys = {}
                nonce = "imported_" + str(uuid.uuid4())[:8]
                version = "imported"

            fernet_key = Fernet(SERVER_ENCRYPTION_KEY)
            plain_content_enc = fernet_key.encrypt(text.encode()).decode()

            # Debug лог перед сохранением
            if imported <= 3:
                print(f"📁 DEBUG: SAVING message #{imported}:")
                print(
                    f"  - encrypted_content type: {type(encrypted_content)}, starts with: {encrypted_content[:50] if len(encrypted_content) > 50 else encrypted_content}")
                print(f"  - encrypted_session_keys: {len(encrypted_session_keys)} devices")
                print(f"  - plain_content_enc length: {len(plain_content_enc)}")
                print(f"  - Original text: '{text}'")
                print(f"  - Encrypted text preview: {plain_content_enc[:50]}...")

                # Тест расшифровки
                try:
                    decrypted = fernet_key.decrypt(plain_content_enc.encode()).decode()
                    print(f"📁 DEBUG: Server decryption test: '{decrypted}'")
                except Exception as e:
                    print(f"📁 DEBUG: Server decryption error: {e}")

            msg = Message(
                from_id=sender_id,
                to_id=receiver_id,
                encrypted_content=encrypted_content,
                encrypted_session_keys=json.dumps(encrypted_session_keys),
                nonce=nonce,
                version=version,
                timestamp=created_at,
                delivered=True,
                delivery_attempted=True,
                is_deleted=False,
                suspicious=False,
                plain_content_enc=plain_content_enc,
            )

            batch_objects.append(msg)
            imported += 1

            # === batch insert ===
            if len(batch_objects) >= BATCH_SIZE:
                print(f"📁 DEBUG: Inserting batch of {len(batch_objects)} messages")
                db.add_all(batch_objects)
                await db.commit()
                print(f"📁 DEBUG: Batch inserted successfully")
                batch_objects.clear()

            # === прогресс ===
            if processed % 200 == 0:
                import_request.processed_messages = processed
                import_request.imported_messages = imported
                await db.commit()

                await manager.send_personal_message(
                    str(user_id),
                    {
                        "type": "telegram_import_progress",
                        "import_id": import_id,
                        "status": "processing",
                        "total": total,
                        "processed": processed,
                        "percentage": round(processed / total * 100, 2),
                        "imported": imported,
                        "chat_id": target_user_id
                    }
                )

        # === финальный batch ===
        if batch_objects:
            print(f"📁 DEBUG: Inserting final batch of {len(batch_objects)} messages")
            db.add_all(batch_objects)
            await db.commit()
            print(f"📁 DEBUG: Final batch inserted successfully")

        print(f"📁 DEBUG: Import summary: processed={processed}, imported={imported}, total={total}")

        # === очистка файла ===
        try:
            os.remove(html_file_path)
            print(f"📁 DEBUG: Deleted HTML file after import: {html_file_path}")
        except Exception as e:
            logging.warning(f"Failed to delete HTML file: {e}")

        if import_id in import_file_paths:
            removed_path = import_file_paths.pop(import_id)
            print(f"📁 DEBUG: Removed file path from storage after import: {removed_path}")

        # === финал ===
        import_request.status = "completed"
        import_request.processed_messages = processed
        import_request.imported_messages = imported
        await db.commit()

        await manager.send_personal_message(
            str(user_id),
            {
                "type": "telegram_import_progress",
                "import_id": import_id,
                "status": "completed",
                "imported": imported,
                "total": total,
                "chat_id": target_user_id
            }
        )

    except Exception as e:
        logging.error(f"IMPORT ERROR: {e}")
        print(f"📁 DEBUG: Import failed with error: {e}")

        if import_request:
            import_request.status = "failed"
            import_request.error_message = str(e)
            await db.commit()

        if import_id in import_file_paths:
            error_file_path = import_file_paths.pop(import_id)
            print(f"📁 DEBUG: Removed file path due to error: {error_file_path}")
            if os.path.exists(error_file_path):
                try:
                    os.remove(error_file_path)
                    print(f"📁 DEBUG: Deleted file due to error: {error_file_path}")
                except Exception:
                    pass

        await manager.send_personal_message(
            str(user_id),
            {
                "type": "telegram_import_progress",
                "import_id": import_id,
                "status": "failed",
                "error": str(e),
                "chat_id": target_user_id
            }
        )


@app.delete("/api/devices/{device_id}")
async def delete_device(
        device_id: str,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Удаление подтвержденного устройства"""
    await check_rate(current_user.id)

    try:
        device_uuid = uuid.UUID(device_id)
    except ValueError:
        raise HTTPException(400, detail="Неверный формат ID устройства")

    # Находим устройство
    device_result = await db.execute(
        select(Device)
        .where(Device.id == device_uuid)
        .where(Device.user_id == current_user.id)
    )
    device = device_result.scalars().first()

    if not device:
        raise HTTPException(404, detail="Устройство не найдено")

    if not device.is_confirmed:
        raise HTTPException(400, detail="Нельзя удалить неподтвержденное устройство")

    await db.delete(device)
    await db.commit()

    return {"status": "deleted", "message": "Устройство успешно удалено"}


@app.get("/api/devices/{device_id}/keys")
async def get_device_keys(
        device_id: str,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Получение зашифрованных ключей для кросс-устройственной синхронизации"""
    await check_rate(current_user.id)

    try:
        device_uuid = uuid.UUID(device_id)
    except ValueError:
        raise HTTPException(400, detail="Неверный формат ID устройства")

    # Находим устройство
    device_result = await db.execute(
        select(Device)
        .where(Device.id == device_uuid)
        .where(Device.user_id == current_user.id)
        .where(Device.is_confirmed == True)
    )
    device = device_result.scalars().first()

    if not device:
        raise HTTPException(404, detail="Подтвержденное устройство не найдено")

    # Получаем все подтвержденные устройства пользователя
    all_devices_result = await db.execute(
        select(Device)
        .where(Device.user_id == current_user.id)
        .where(Device.is_confirmed == True)
        .where(Device.id != device_uuid)
    )
    other_devices = all_devices_result.scalars().all()

    # Формируем ответ с ключами других устройств
    device_keys = []
    for other_device in other_devices:
        if other_device.encrypted_keys:
            device_keys.append({
                "device_id": str(other_device.id),
                "device_name": other_device.device_name,
                "device_fingerprint": other_device.device_fingerprint,
                "public_key_x25519": other_device.public_key_x25519,
                "encrypted_keys": other_device.encrypted_keys,
                "last_active": other_device.last_active,
            })

    return {
        "current_device": {
            "id": str(device.id),
            "device_name": device.device_name,
            "device_fingerprint": device.device_fingerprint,
            "public_key_x25519": device.public_key_x25519,
            "encrypted_keys": device.encrypted_keys,
        },
        "other_devices": device_keys
    }


@app.post("/api/devices/{device_id}/update-keys")
async def update_device_keys(
        device_id: str,
        encrypted_keys: str = Body(...),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """Обновление зашифрованных ключей для кросс-устройственной синхронизации"""
    await check_rate(current_user.id)

    try:
        device_uuid = uuid.UUID(device_id)
    except ValueError:
        raise HTTPException(400, detail="Неверный формат ID устройства")

    # Находим устройство
    device_result = await db.execute(
        select(Device)
        .where(Device.id == device_uuid)
        .where(Device.user_id == current_user.id)
        .where(Device.is_confirmed == True)
    )
    device = device_result.scalars().first()

    if not device:
        raise HTTPException(404, detail="Подтвержденное устройство не найдено")

    # Обновляем зашифрованные ключи
    device.encrypted_keys = encrypted_keys
    device.last_active = datetime.now(timezone.utc)

    await db.commit()

    return {"status": "updated", "message": "Ключи устройства успешно обновлены"}
