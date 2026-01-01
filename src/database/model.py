from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, CheckConstraint
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Event(Base):
    __tablename__ = 'events'
    
    # id
    event_id = Column(Integer, primary_key=True, index=True, nullable=False, unique=True, autoincrement=False)

    # event info
    title = Column(String, nullable=False)
    start = Column(Integer, nullable=False)
    finish = Column(Integer, nullable=False)
    
    # discord
    category_id = Column(Integer, nullable=True, unique=True, default=None)

    is_private = Column(Boolean, nullable=False, default=False)
    

class CustomEvent(Base):
    __tablename__ = 'custom_events'
    
    # discord
    category_id = Column(Integer, primary_key=True, index=True, nullable=False, unique=True, autoincrement=False)

    title = Column(String, nullable=False)

    is_private = Column(Boolean, nullable=False, default=False)