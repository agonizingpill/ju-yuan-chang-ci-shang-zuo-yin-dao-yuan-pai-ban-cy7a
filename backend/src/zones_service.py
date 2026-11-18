from datetime import datetime,timezone
from fastapi import HTTPException
from sqlalchemy import select
from .models import Production,Performance,CrewCall
from .staff_models import CrewAssignment
from .debrief_models import ShowDebrief
from .zone_models import EntranceZone,ZonePost,ZoneClosurePlan
from .incident_models import HouseIncident
from .staff_service import locked,call_context
from .services import pack,audit

def production_lock(s,id):return locked(s,Production,id)
def performance_context(s,id):
    p=s.get(Performance,id)
    if not p:raise HTTPException(404,'演出场次不存在')
    c=s.scalar(select(CrewCall).where(CrewCall.performance_id==id))
    if not c:raise HTTPException(409,'请先确认本场点名')
    return call_context(s,c.id)
def mutable(s,id):
    if s.scalar(select(ShowDebrief.id).where(ShowDebrief.performance_id==id)):raise HTTPException(409,'已填写散场交接，本场岗位与现场事件登记冻结')
def create(s,d,u):
    prod=production_lock(s,d.production_id)
    if s.scalar(select(ShowDebrief.id).join(Performance,Performance.id==ShowDebrief.performance_id).where(Performance.production_id==prod.id,ShowDebrief.state=='draft')):raise HTTPException(409,'该剧目有待归档交接，暂不能增加分区')
    zones=s.scalars(select(EntranceZone).where(EntranceZone.production_id==prod.id)).all()
    if sum(x.capacity for x in zones)+d.capacity>prod.seats:raise HTTPException(409,'入口分区容量合计超过剧目座位')
    x=EntranceZone(**d.model_dump());s.add(x);s.flush();audit(s,u,'配置入口分区 '+d.code);return pack(x)
def post_view(s,x):
    a=s.get(CrewAssignment,x.assignment_id);c=s.get(CrewCall,a.crew_call_id);p=s.get(Performance,c.performance_id);z=s.get(EntranceZone,x.zone_id)
    return pack(x)|{'staff_name':a.staff_name,'performance_id':p.id,'production_id':p.production_id,'date':p.date.isoformat(),'zone_code':z.code}
def post(s,d,u):
    a=s.get(CrewAssignment,d.assignment_id)
    if not a:raise HTTPException(404,'实名班表不存在')
    c,p,prod=performance_context(s,s.get(CrewCall,a.crew_call_id).performance_id);production_lock(s,prod.id);mutable(s,p.id);a=locked(s,CrewAssignment,d.assignment_id);z=locked(s,EntranceZone,d.zone_id)
    if not a.checked_in:raise HTTPException(409,'只有实名已到岗人员才可安排入口岗位')
    if z.production_id!=p.production_id or not z.active:raise HTTPException(409,'分区不属于本剧目或未启用')
    plan=active_plan(s,p.id)
    if plan and plan.zone_id==z.id:raise HTTPException(409,'该入口本场已临时封闭，不能继续安排岗位')
    if s.scalar(select(ZonePost.id).where(ZonePost.assignment_id==a.id)):raise HTTPException(409,'该人员本场已有入口岗位，不得重复')
    x=ZonePost(**d.model_dump());s.add(x);s.flush();audit(s,u,f'入口岗位 {a.staff_code}→{z.code}');return post_view(s,x)
def open_zones(s,production_id):
    return s.scalars(select(EntranceZone).where(EntranceZone.production_id==production_id,EntranceZone.active==True).order_by(EntranceZone.id)).all()
def active_plan(s,performance_id):
    return s.scalar(select(ZoneClosurePlan).where(ZoneClosurePlan.performance_id==performance_id,ZoneClosurePlan.state=='active').order_by(ZoneClosurePlan.id.desc()))
def coverage(s,performance_id):
    p=s.get(Performance,performance_id);production_lock(s,p.production_id)
    plan=active_plan(s,p.id)
    zones=[z for z in open_zones(s,p.production_id) if not plan or z.id!=plan.zone_id]
    if not zones:raise HTTPException(409,'新交接须先配置启用入口分区并安排实名岗位')
    rows=s.execute(select(ZonePost.zone_id,CrewAssignment.id).join(CrewAssignment,CrewAssignment.id==ZonePost.assignment_id).join(CrewCall,CrewCall.id==CrewAssignment.crew_call_id).where(CrewCall.performance_id==p.id,CrewAssignment.checked_in==True)).all()
    if plan and any(zone==plan.zone_id for zone,_ in rows):raise HTTPException(409,'已封闭入口仍留有实名岗位，请核对封闭方案')
    for z in zones:
        if sum(zone==z.id for zone,_ in rows)<z.required_staff:raise HTTPException(409,f'入口{z.code}岗位不足，至少需{z.required_staff}名实名到岗人员')

def _post_rows(s,performance_id):
    return s.execute(select(ZonePost.id,ZonePost.assignment_id,ZonePost.zone_id,CrewAssignment.checked_in).join(CrewAssignment,CrewAssignment.id==ZonePost.assignment_id).join(CrewCall,CrewCall.id==CrewAssignment.crew_call_id).where(CrewCall.performance_id==performance_id)).all()
def _snapshot(s,p,zones,cid):
    posts=sorted([[x.id,x.assignment_id,x.zone_id,bool(x.checked_in)] for x in _post_rows(s,p.id)])
    return {'expected_posts':posts,'zones':sorted([[z.id,z.capacity,z.required_staff,bool(z.active)] for z in zones]),'incidents':sorted(s.scalars(select(HouseIncident.id).where(HouseIncident.performance_id==p.id))),'forecast':p.forecast,'call_id':cid}
def plan_view(s,x):
    p=s.get(Performance,x.performance_id)
    return pack(x)|{'zone_code':s.get(EntranceZone,x.zone_id).code if s.get(EntranceZone,x.zone_id) else None,'performance_date':p.date.isoformat() if p else None}

def plan_create(s,d,u):
    c,p,prod=performance_context(s,d.performance_id);production_lock(s,prod.id);z=locked(s,EntranceZone,d.zone_id)
    if z.production_id!=prod.id or not z.active:raise HTTPException(409,'封闭分区不属于本剧目或未启用')
    if s.scalar(select(ShowDebrief.id).where(ShowDebrief.performance_id==p.id)):raise HTTPException(409,'本场已有散场交接，不能制定封闭方案')
    if s.scalar(select(ZoneClosurePlan.id).where(ZoneClosurePlan.performance_id==p.id,ZoneClosurePlan.state.in_(('pending','active')))):raise HTTPException(409,'本场已有待生效或已生效的封闭方案')
    zones=s.scalars(select(EntranceZone).where(EntranceZone.production_id==prod.id).order_by(EntranceZone.id)).all()
    targets=[x for x in zones if x.active and x.id!=z.id]
    if not targets:raise HTTPException(409,'封闭后没有其他启用入口可迁入岗位')
    if p.forecast is None:raise HTTPException(409,'缺少本场上座预测，不能制定封闭方案')
    open_capacity=sum(x.capacity for x in targets)
    if open_capacity<p.forecast:raise HTTPException(409,f'封闭后开放容量{open_capacity}人，不足本场预测{p.forecast}人')
    posts=_post_rows(s,p.id)
    counts={x.id:0 for x in targets}
    for x in posts:
        if x.checked_in and x.zone_id in counts:counts[x.zone_id]+=1
    affected=sorted([x for x in posts if x.zone_id==z.id],key=lambda x:x.assignment_id)
    remaining=list(affected);moves=[]
    for target in targets:
        need=max(0,target.required_staff-counts[target.id])
        while need and remaining:
            row=remaining.pop(0);counts[target.id]+=1;need-=1
            moves.append({'assignment_id':row.assignment_id,'from_zone_id':z.id,'to_zone_id':target.id})
    while remaining:
        target=min(targets,key=lambda x:(counts[x.id],x.id));row=remaining.pop(0);counts[target.id]+=1
        moves.append({'assignment_id':row.assignment_id,'from_zone_id':z.id,'to_zone_id':target.id})
    for target in targets:
        if counts[target.id]<target.required_staff:raise HTTPException(409,f'迁后入口{target.code}岗位不足，至少需{target.required_staff}名实名到岗人员')
    staff={x.assignment_id:(x.assignment_id,s.get(CrewAssignment,x.assignment_id).staff_code,s.get(CrewAssignment,x.assignment_id).staff_name) for x in affected}
    for m in moves:
        m['staff_code'],m['staff_name']=staff[m['assignment_id']][1],staff[m['assignment_id']][2]
    now=datetime.now(timezone.utc).isoformat()
    x=ZoneClosurePlan(performance_id=p.id,zone_id=z.id,reason=d.reason.strip(),moves=moves,snapshot=_snapshot(s,p,zones,c.id),forecast_snapshot=p.forecast,open_capacity_after=open_capacity,state='pending',planned_by=u.email,planned_at=now)
    s.add(x);s.flush();audit(s,u,f'制定封闭方案 #{x.id} 场次#{p.id} 入口{z.code}');return plan_view(s,x)

def _lock_plan(s,id):
    x=s.scalar(select(ZoneClosurePlan).where(ZoneClosurePlan.id==id).with_for_update().execution_options(populate_existing=True))
    if not x:raise HTTPException(404,'封闭方案不存在')
    return x

def _reject(s,x,reason,u):
    x.state='rejected';x.rejection_reason=reason;audit(s,u,f'封闭方案拒绝 #{x.id}：{reason}');s.commit();raise HTTPException(409,reason)

def plan_activate(s,id,u):
    preview=s.get(ZoneClosurePlan,id)
    if not preview:raise HTTPException(404,'封闭方案不存在')
    p=s.get(Performance,preview.performance_id)
    if not p:raise HTTPException(404,'演出场次不存在')
    production_lock(s,p.production_id);x=_lock_plan(s,id)
    if x.state=='active':return plan_view(s,x)
    if x.state=='rejected':raise HTTPException(409,f'方案已拒绝：{x.rejection_reason}')
    if x.state!='pending':raise HTTPException(409,'方案状态不允许生效')
    if s.scalar(select(ZoneClosurePlan.id).where(ZoneClosurePlan.performance_id==p.id,ZoneClosurePlan.state=='active',ZoneClosurePlan.id!=x.id)):_reject(s,x,'本场已有生效的封闭方案，方案过期，请重新制定',u)
    snap=x.snapshot or {}
    c=s.scalar(select(CrewCall).where(CrewCall.performance_id==p.id))
    if not c or c.status!='confirmed' or p.status!='crew_confirmed' or c.id!=snap.get('call_id'):_reject(s,x,'原点名或场次状态已失效，方案过期，请重新制定',u)
    if s.scalar(select(ShowDebrief.id).where(ShowDebrief.performance_id==p.id)):_reject(s,x,'本场已有散场交接，封闭方案不能生效',u)
    zones=s.scalars(select(EntranceZone).where(EntranceZone.production_id==p.production_id).order_by(EntranceZone.id)).all()
    if sorted([[z.id,z.capacity,z.required_staff,bool(z.active)] for z in zones])!=snap.get('zones'):_reject(s,x,'方案待生效期间入口分区配置已变更，方案过期，请重新制定',u)
    posts=sorted([[r.id,r.assignment_id,r.zone_id,bool(r.checked_in)] for r in _post_rows(s,p.id)])
    if posts!=snap.get('expected_posts'):_reject(s,x,'方案待生效期间岗位安排已变更，方案过期，请重新制定',u)
    if sorted(s.scalars(select(HouseIncident.id).where(HouseIncident.performance_id==p.id)))!=snap.get('incidents'):_reject(s,x,'方案待生效期间现场事件已补报，方案过期，请重新制定',u)
    if p.forecast!=snap.get('forecast'):_reject(s,x,'方案待生效期间上座预测已变更，方案过期，请重新制定',u)
    targets=[z for z in zones if z.active and z.id!=x.zone_id]
    if sum(z.capacity for z in targets)<p.forecast:_reject(s,x,'封闭后开放容量不足本场预测人数，方案过期，请重新制定',u)
    counts={z.id:0 for z in targets}
    for r in posts:
        if r[3] and r[2] in counts:counts[r[2]]+=1
    affected={r[1] for r in posts if r[2]==x.zone_id}
    if affected!={m['assignment_id'] for m in x.moves}:_reject(s,x,'封闭方案岗位快照不一致，方案过期，请重新制定',u)
    for m in x.moves:
        if m['to_zone_id'] not in counts or m['from_zone_id']!=x.zone_id:_reject(s,x,'封闭方案迁岗目标已失效，方案过期，请重新制定',u)
        counts[m['to_zone_id']]+=1
    for z in targets:
        if counts[z.id]<z.required_staff:_reject(s,x,f'迁后入口{z.code}岗位不足，至少需{z.required_staff}名实名到岗人员',u)
    rows=[]
    for m in x.moves:
        row=s.scalar(select(ZonePost).where(ZonePost.assignment_id==m['assignment_id'],ZonePost.zone_id==m['from_zone_id']).with_for_update())
        if not row:_reject(s,x,'封闭方案岗位快照不一致，方案过期，请重新制定',u)
        rows.append((row,m['to_zone_id']))
    for row,to_zone_id in rows:row.zone_id=to_zone_id
    x.state='active';x.activated_by=u.email;x.activated_at=datetime.now(timezone.utc).isoformat();audit(s,u,f'经理确认封闭方案生效 #{x.id} 场次#{p.id}');return plan_view(s,x)
