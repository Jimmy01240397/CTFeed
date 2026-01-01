from typing import Optional, List
import logging

from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy

from src.database.model import CustomEvent

logger = logging.getLogger("database")

# create
async def create_custom_event(
    db: AsyncSession,
    title: str,
    category_id: int
) -> int:
    try:
        db.add(CustomEvent(category_id=category_id, title=title))
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"failed to write database : {str(e)}")
        return 0
    return 1


# read
async def read_custom_event(
    db: AsyncSession,
    category_id: Optional[List[int]] = None,
) -> List[CustomEvent]:
    try:
        query = sqlalchemy.select(CustomEvent)
        if category_id is not None:
            query = query.where(CustomEvent.category_id.in_(category_id))
        result = await db.execute(query)
        return result.scalars().all()
    except Exception as e:
        logger.error(f"failed to read database : {str(e)}")
        return []

async def update_custom_event(
    db:AsyncSession,
    category_id: int,
    title:Optional[str]=None,
    private:Optional[bool]=None,
) -> Optional[CustomEvent]:
    try:
        # find
        query = sqlalchemy.select(CustomEvent).where(CustomEvent.category_id == category_id)
        event = (await db.execute(query)).scalar_one_or_none()
        if event is None:
            return None
        
        # update
        if not(title is None):
            event.title = title
                
        if not(private is None):
            event.is_private = private
        
        # commit
        await db.commit()
        await db.refresh(event)
        return event
    except Exception as e:
        await db.rollback()
        logger.error(f"failed to update database : {str(e)}")
        return None


# delete
async def delete_custom_event(
    db: AsyncSession,
    category_id: List[int],
) -> int:
    try:
        stmt = sqlalchemy.delete(CustomEvent).where(CustomEvent.category_id.in_(category_id))
        await db.execute(stmt)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"failed to write database : {str(e)}")
        return 0
    return 1
