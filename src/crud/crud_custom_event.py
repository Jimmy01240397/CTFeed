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
