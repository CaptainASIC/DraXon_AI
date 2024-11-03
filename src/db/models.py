from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

class TimestampMixin:
    """Mixin for adding timestamp columns"""
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class RSIMember(Base, TimestampMixin):
    """RSI Member information"""
    __tablename__ = 'rsi_members'
    
    discord_id = Column(String, primary_key=True)
    handle = Column(String, unique=True, index=True)
    sid = Column(String, index=True)
    display_name = Column(String)
    enlisted = Column(DateTime(timezone=True))
    org_status = Column(String)
    org_rank = Column(String)
    org_stars = Column(Integer, default=0)
    verified = Column(Boolean, default=False)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    raw_data = Column(JSONB)
    
    # Relationships
    role_history = relationship("RoleHistory", back_populates="member", cascade="all, delete-orphan")
    verification_history = relationship("VerificationHistory", back_populates="member", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        """Convert member to dictionary"""
        return {
            'discord_id': self.discord_id,
            'handle': self.handle,
            'sid': self.sid,
            'display_name': self.display_name,
            'enlisted': self.enlisted.isoformat() if self.enlisted else None,
            'org_status': self.org_status,
            'org_rank': self.org_rank,
            'org_stars': self.org_stars,
            'verified': self.verified,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
            'raw_data': self.raw_data
        }

class RoleHistory(Base, TimestampMixin):
    """Role change history"""
    __tablename__ = 'role_history'
    
    id = Column(Integer, primary_key=True)
    discord_id = Column(String, ForeignKey('rsi_members.discord_id', ondelete='CASCADE'))
    old_rank = Column(String)
    new_rank = Column(String)
    reason = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship
    member = relationship("RSIMember", back_populates="role_history")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert role history to dictionary"""
        return {
            'id': self.id,
            'discord_id': self.discord_id,
            'old_rank': self.old_rank,
            'new_rank': self.new_rank,
            'reason': self.reason,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }

class VerificationHistory(Base, TimestampMixin):
    """Verification attempt history"""
    __tablename__ = 'verification_history'
    
    id = Column(Integer, primary_key=True)
    discord_id = Column(String, ForeignKey('rsi_members.discord_id', ondelete='CASCADE'))
    action = Column(String)  # 'create', 'update', 'verify', etc.
    status = Column(Boolean)
    details = Column(JSONB)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship
    member = relationship("RSIMember", back_populates="verification_history")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert verification history to dictionary"""
        return {
            'id': self.id,
            'discord_id': self.discord_id,
            'action': self.action,
            'status': self.status,
            'details': self.details,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }

class IncidentHistory(Base, TimestampMixin):
    """RSI Incident history"""
    __tablename__ = 'incident_history'
    
    guid = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    status = Column(String)
    components = Column(JSONB)
    link = Column(String)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert incident to dictionary"""
        return {
            'guid': self.guid,
            'title': self.title,
            'description': self.description,
            'status': self.status,
            'components': self.components,
            'link': self.link,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }

# Indices and constraints will be created by Alembic migrations
