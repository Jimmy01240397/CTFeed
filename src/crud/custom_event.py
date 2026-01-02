from typing import Optional, List
import logging

from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy

from src.database.model import CustomEvent

logger = logging.getLogger("database")

# create
async def create_event(
    db: AsyncSession,
    title: str,
    category_id: int
) -> CustomEvent:
    data = CustomEvent(category_id=category_id, title=title)
    try:
        db.add(data)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"failed to write database : {str(e)}")
        return None
    return data


# read
async def read_event(
    db: AsyncSession,
    event_id:Optional[List[int]]=None,
    category_id:Optional[List[int]]=None,
    title:Optional[List[str]]=None,
) -> List[CustomEvent]:
    try:
        query = sqlalchemy.select(CustomEvent)
        
        if not (event_id is None):
            query = query.where(CustomEvent.event_id.in_(event_id))
        
        if not (category_id is None):
            query = query.where(CustomEvent.category_id.in_(category_id))

        if not(title is None):
            query = query.where(CustomEvent.title.in_(title))
            
        result = await db.execute(query)
        return result.scalars().all()
    except Exception as e:
        logger.error(f"failed to read database : {str(e)}")
        return []

async def update_event(
    db:AsyncSession,
    event_id:int,
    category_id:Optional[List[int]]=None,
    title:Optional[str]=None,
    private:Optional[bool]=None,
) -> Optional[CustomEvent]:
    try:
        # find
        query = sqlalchemy.select(CustomEvent).where(CustomEvent.event_id == event_id)
        event = (await db.execute(query)).scalar_one_or_none()
        if event is None:
            return None
        
        # update
        if not (category_id is None):
            event.category_id = category_id

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
async def delete_event(
    db: AsyncSession,
    event_id: List[int],
) -> int:
    try:
        stmt = sqlalchemy.delete(CustomEvent).where(CustomEvent.event_id.in_(event_id))
        await db.execute(stmt)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"failed to write database : {str(e)}")
        return 0
    return 1
