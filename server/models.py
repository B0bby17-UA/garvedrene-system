import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from database import Base


def generate_uuid():
    return uuid.uuid4().hex[:12]


class User(Base):
    __tablename__ = "users"

    id = Column(String(12), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    characters = relationship("Character", back_populates="user", cascade="all, delete-orphan")
    campaigns_as_master = relationship("Campaign", back_populates="master", cascade="all, delete-orphan")


class Character(Base):
    __tablename__ = "characters"

    id = Column(String(12), primary_key=True, default=generate_uuid)
    user_id = Column(String(12), ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    level = Column(Integer, default=1)
    classe = Column(String(50), default="Bruxo")
    data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    user = relationship("User", back_populates="characters")
    campaign_links = relationship("CampaignCharacter", back_populates="character", cascade="all, delete-orphan")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(String(12), primary_key=True, default=generate_uuid)
    name = Column(String(200), nullable=False)
    invite_code = Column(String(20), unique=True, index=True, default=generate_uuid)
    master_id = Column(String(12), ForeignKey("users.id"), nullable=False)
    npcs = Column(JSON, default=dict)  # {npc_id: {name, icone, data, ...}}
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    master = relationship("User", back_populates="campaigns_as_master")
    character_links = relationship("CampaignCharacter", back_populates="campaign", cascade="all, delete-orphan")
    messages = relationship("ChatMessage", back_populates="campaign", cascade="all, delete-orphan")


class CampaignCharacter(Base):
    __tablename__ = "campaign_characters"

    id = Column(String(12), primary_key=True, default=generate_uuid)
    campaign_id = Column(String(12), ForeignKey("campaigns.id"), nullable=False)
    character_id = Column(String(12), ForeignKey("characters.id"), nullable=False)
    campaign_data = Column(JSON, default=dict)
    joined_at = Column(DateTime, default=datetime.now(timezone.utc))

    campaign = relationship("Campaign", back_populates="character_links")
    character = relationship("Character", back_populates="campaign_links")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String(12), primary_key=True, default=generate_uuid)
    campaign_id = Column(String(12), ForeignKey("campaigns.id"), nullable=False)
    user_id = Column(String(12), ForeignKey("users.id"), nullable=True)
    character_id = Column(String(12), ForeignKey("characters.id"), nullable=True)
    author_name = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    message_type = Column(String(20), default="chat")  # chat, roll, system, tell
    target_user_id = Column(String(12), nullable=True)  # for /tell (only target sees)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    campaign = relationship("Campaign", back_populates="messages")
