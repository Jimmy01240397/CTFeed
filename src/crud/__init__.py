from src.database.model import BaseEvent, Event, CustomEvent
from src.database.database import get_db
import src.crud.event as event
import src.crud.custom_event as custom_event
from typing import List, Optional

async def read_event(
    event_id:Optional[List[int]]=None,
    category_id:Optional[List[int]]=None,
    title:Optional[List[str]]=None,
) -> List[Event]:
    return await event.read_event(
        event_id=event_id,
        category_id=category_id,
        title=title,
    ) + await custom_event.read_event(
        event_id=event_id,
        category_id=category_id,
        title=title,
    )

async def read_all_event(filter:bool=False) -> List[BaseEvent]:
    async with get_db() as session:
        known_events:List[Event] = await event.read_event(session)
        custom_events:List[CustomEvent] = await custom_event.read_event(session)
    if filter:
        filtered_events:List[Event] = []
        for e in known_events:
            if getattr(e, "category_id", None) and e.category_id is not None:
                filtered_events.append(e)
        known_events = filtered_events
    return known_events + custom_events


