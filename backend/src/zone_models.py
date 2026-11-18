from sqlalchemy import String,Integer,Boolean,Text,JSON,ForeignKey,UniqueConstraint,CheckConstraint
from sqlalchemy.orm import Mapped,mapped_column
from .db import Base
class EntranceZone(Base):
    __tablename__='entrance_zones'
    __table_args__=(UniqueConstraint('production_id','code'),CheckConstraint('capacity > 0 AND required_staff > 0'))
    id:Mapped[int]=mapped_column(primary_key=True)
    production_id:Mapped[int]=mapped_column(ForeignKey('productions.id'))
    code:Mapped[str]=mapped_column(String(40))
    capacity:Mapped[int]=mapped_column(Integer)
    required_staff:Mapped[int]=mapped_column(Integer)
    active:Mapped[bool]=mapped_column(Boolean,default=True)
class ZonePost(Base):
    __tablename__='zone_posts'
    id:Mapped[int]=mapped_column(primary_key=True)
    assignment_id:Mapped[int]=mapped_column(ForeignKey('crew_assignments.id'),unique=True)
    zone_id:Mapped[int]=mapped_column(ForeignKey('entrance_zones.id'))
class ZoneClosurePlan(Base):
    __tablename__='zone_closure_plans'
    __table_args__=(CheckConstraint("state in ('pending','active','rejected')"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    performance_id:Mapped[int]=mapped_column(ForeignKey('performances.id'))
    zone_id:Mapped[int]=mapped_column(ForeignKey('entrance_zones.id'))
    reason:Mapped[str]=mapped_column(Text,default='')
    moves:Mapped[list]=mapped_column(JSON,default=list)
    snapshot:Mapped[dict]=mapped_column(JSON,default=dict)
    forecast_snapshot:Mapped[int|None]=mapped_column(Integer,nullable=True)
    open_capacity_after:Mapped[int]=mapped_column(Integer,default=0)
    state:Mapped[str]=mapped_column(String(20),default='pending')
    rejection_reason:Mapped[str]=mapped_column(Text,default='')
    planned_by:Mapped[str]=mapped_column(String(100))
    planned_at:Mapped[str]=mapped_column(String(40))
    activated_by:Mapped[str|None]=mapped_column(String(100),nullable=True)
    activated_at:Mapped[str|None]=mapped_column(String(40),nullable=True)
