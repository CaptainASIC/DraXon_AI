from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import logging
from sqlalchemy import select, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from .models import RSIMember, RoleHistory, VerificationHistory, IncidentHistory

logger = logging.getLogger('DraXon_AI')

class MemberRepository:
    """Repository for member-related database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_member(self, discord_id: str) -> Optional[RSIMember]:
        """Get member by Discord ID"""
        try:
            result = await self.session.execute(
                select(RSIMember).where(RSIMember.discord_id == discord_id)
            )
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving member {discord_id}: {e}")
            raise
    
    async def get_member_by_handle(self, handle: str) -> Optional[RSIMember]:
        """Get member by RSI handle"""
        try:
            result = await self.session.execute(
                select(RSIMember).where(RSIMember.handle == handle)
            )
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving member by handle {handle}: {e}")
            raise
    
    async def create_or_update_member(self, member_data: Dict[str, Any]) -> RSIMember:
        """Create or update a member record"""
        try:
            discord_id = member_data['discord_id']
            member = await self.get_member(discord_id)
            
            if member:
                # Update existing member
                for key, value in member_data.items():
                    setattr(member, key, value)
            else:
                # Create new member
                member = RSIMember(**member_data)
                self.session.add(member)
            
            await self.session.commit()
            await self.session.refresh(member)
            return member
            
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Error creating/updating member: {e}")
            raise
    
    async def search_members(self, criteria: Dict[str, Any]) -> List[RSIMember]:
        """Search members based on criteria"""
        try:
            query = select(RSIMember)
            
            # Build filter conditions
            conditions = []
            for key, value in criteria.items():
                if hasattr(RSIMember, key):
                    conditions.append(getattr(RSIMember, key) == value)
            
            if conditions:
                query = query.where(and_(*conditions))
            
            result = await self.session.execute(query)
            return result.scalars().all()
            
        except SQLAlchemyError as e:
            logger.error(f"Error searching members: {e}")
            raise

class HistoryRepository:
    """Repository for history-related database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def add_role_history(self, 
                             discord_id: str, 
                             old_rank: str, 
                             new_rank: str, 
                             reason: str) -> RoleHistory:
        """Add role change history"""
        try:
            history = RoleHistory(
                discord_id=discord_id,
                old_rank=old_rank,
                new_rank=new_rank,
                reason=reason,
                timestamp=datetime.utcnow()
            )
            self.session.add(history)
            await self.session.commit()
            await self.session.refresh(history)
            return history
            
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Error adding role history: {e}")
            raise
    
    async def add_verification_history(self,
                                     discord_id: str,
                                     action: str,
                                     status: bool,
                                     details: Dict[str, Any]) -> VerificationHistory:
        """Add verification attempt history"""
        try:
            history = VerificationHistory(
                discord_id=discord_id,
                action=action,
                status=status,
                details=details,
                timestamp=datetime.utcnow()
            )
            self.session.add(history)
            await self.session.commit()
            await self.session.refresh(history)
            return history
            
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Error adding verification history: {e}")
            raise
    
    async def get_role_history(self, discord_id: str, 
                             limit: int = 10) -> List[RoleHistory]:
        """Get role history for a member"""
        try:
            result = await self.session.execute(
                select(RoleHistory)
                .where(RoleHistory.discord_id == discord_id)
                .order_by(RoleHistory.timestamp.desc())
                .limit(limit)
            )
            return result.scalars().all()
            
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving role history: {e}")
            raise
    
    async def get_verification_history(self, discord_id: str, 
                                     limit: int = 10) -> List[VerificationHistory]:
        """Get verification history for a member"""
        try:
            result = await self.session.execute(
                select(VerificationHistory)
                .where(VerificationHistory.discord_id == discord_id)
                .order_by(VerificationHistory.timestamp.desc())
                .limit(limit)
            )
            return result.scalars().all()
            
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving verification history: {e}")
            raise
    
    async def cleanup_old_records(self, days: int = 30) -> int:
        """Clean up old history records"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # Delete old role history
            role_result = await self.session.execute(
                delete(RoleHistory).where(RoleHistory.timestamp < cutoff_date)
            )
            
            # Delete old verification history
            verify_result = await self.session.execute(
                delete(VerificationHistory).where(VerificationHistory.timestamp < cutoff_date)
            )
            
            await self.session.commit()
            return role_result.rowcount + verify_result.rowcount
            
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Error cleaning up old records: {e}")
            raise

class IncidentRepository:
    """Repository for incident-related database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def add_incident(self, incident_data: Dict[str, Any]) -> IncidentHistory:
        """Add new incident to history"""
        try:
            incident = IncidentHistory(**incident_data)
            self.session.add(incident)
            await self.session.commit()
            await self.session.refresh(incident)
            return incident
            
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Error adding incident: {e}")
            raise
    
    async def get_incident(self, guid: str) -> Optional[IncidentHistory]:
        """Get incident by GUID"""
        try:
            result = await self.session.execute(
                select(IncidentHistory).where(IncidentHistory.guid == guid)
            )
            return result.scalar_one_or_none()
            
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving incident {guid}: {e}")
            raise
    
    async def get_recent_incidents(self, limit: int = 10) -> List[IncidentHistory]:
        """Get recent incidents"""
        try:
            result = await self.session.execute(
                select(IncidentHistory)
                .order_by(IncidentHistory.timestamp.desc())
                .limit(limit)
            )
            return result.scalars().all()
            
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving recent incidents: {e}")
            raise
    
    async def cleanup_old_incidents(self, days: int = 90) -> int:
        """Clean up old incidents"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            result = await self.session.execute(
                delete(IncidentHistory).where(IncidentHistory.timestamp < cutoff_date)
            )
            
            await self.session.commit()
            return result.rowcount
            
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Error cleaning up old incidents: {e}")
            raise
