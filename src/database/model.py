from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, CheckConstraint
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class BaseEvent(Base):
    __abstract__ = True
    __tablename__ = 'base_events'

    title = Column(String, unique=True, nullable=False)
    is_private = Column(Boolean, nullable=False, default=False)

    # id
    event_id = Column(Integer, primary_key=True, index=True, nullable=False, unique=True, autoincrement=True)
    category_id = Column(Integer, nullable=True, unique=True, default=None)

    @property
    def event_type(self) -> str:
        return "base"


class Event(BaseEvent):
    __tablename__ = 'events'
    
    # event info
    start = Column(Integer, nullable=False)
    finish = Column(Integer, nullable=False)

    @property
    def event_type(self) -> str:
        return "event"
    

class CustomEvent(BaseEvent):
    __tablename__ = 'custom_events'
    
    @property
    def event_type(self) -> str:
        return "custom"