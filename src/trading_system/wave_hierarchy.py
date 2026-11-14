"""Causal wave ownership; scale comparisons are explicit research conventions."""
from .structure import SwingCache,area,correction_measure,n_structure,Swing


def correction_level(duration,drop,reference_duration,reference_drop):
    if duration<reference_duration and drop<reference_drop:return 'internal'
    if duration>=reference_duration and drop>=reference_drop:return 'core'
    return 'unresolved'


class WaveHierarchy:
    def __init__(self,left=2,right=2):
        self.left,self.right=left,right
        self.swings=SwingCache(left,right)
        self.count=0;self.core=None;self.seed=None;self.reference=None
        self.restore=None;self.rhythm_start=None;self.ended_at=None;self.retired=set();self.ledger={}
        self.origin=None;self.events=[];self.phase='waiting';self.last_ambiguity=-1

    def _id(self,bars,core):
        return ':'.join(bars[core[k]].date for k in ('a','b','c'))

    def _emit(self,bars,event,**details):
        self.events.append(dict(event=event,structure_known_at=bars[-1].date,**details))

    def _candidate(self,bars,a,b,c,confirmed):
        # A later higher trough cannot replace the actual floor of an earlier
        # decline to manufacture a longer/slower correction.
        if min(x.low for x in bars[b+1:c+1])<bars[c].low:return None
        points=[Swing('low',a,a,bars[a].low),Swing('high',b,b,bars[b].high),
                Swing('low',c,confirmed,bars[c].low)]
        return n_structure(bars,points=points)[0]

    def _accept(self,bars,core,parent,relation):
        identity=self._id(bars,core)
        if identity in self.retired:return False
        if self.core:self._end(bars,'replaced_by_core')
        core=dict(core,owner_id=identity,parent_owner=parent,relation=relation)
        self.core=core;self.seed=core['c'];self.reference=dict(core)
        self.restore=core['c'];self.rhythm_start=core['c'];self.phase='recovering'
        self.ledger[identity]=dict(owner_id=identity,parent_owner=parent,relation=relation,
            a=bars[core['a']].date,b=bars[core['b']].date,c=bars[core['c']].date,
            accepted_at=bars[-1].date,state='active')
        self._emit(bars,'wave_core_accepted',owner_id=identity,parent_owner=parent,relation=relation,
                   core_a=bars[core['a']].date,core_b=bars[core['b']].date,core_c=bars[core['c']].date)
        return True

    def _end(self,bars,reason):
        if not self.core:return
        identity=self.core['owner_id'];self.retired.add(identity)
        self.ledger[identity].update(state='ended',ended_at=bars[-1].date,end_reason=reason)
        for record in self.ledger.values():
            if record.get('parent_owner')==identity and record.get('state')=='observed':
                record.update(state='parent_ended',ended_at=bars[-1].date)
        self._emit(bars,'wave_core_ended',owner_id=identity,reason=reason)
        self.core=None;self.ended_at=len(bars)-1;self.phase='waiting'
        if reason in ('floor_broken','order_unknown'):
            self.seed=None;self.reference=None;self.restore=None

    def _classify_low(self,bars,low):
        if self.seed is not None and low.index>self.seed:
            start=self.seed
            peak=max(range(start,low.index),key=lambda i:(bars[i].high,i))
            if min(x.low for x in bars[peak+1:low.index+1])<low.price:
                if self.core and self.restore is not None and self.restore<low.index:
                    start=self.restore
                    peak=max(range(start,low.index),key=lambda i:(bars[i].high,i))
                else:peak=low.index
            if peak==low.index:return
            measured=correction_measure(bars,peak,low.index)
            if not measured:return
            ref=self.reference;drop=bars[ref['b']].high-bars[ref['c']].low
            level=correction_level(measured['duration'],measured['range'],ref['correction_duration'],drop)
            child_id=':'.join((bars[start].date,bars[peak].date,bars[low.index].date))
            self._emit(bars,'wave_correction_classified',owner_id=ref['owner_id'],child_id=child_id,
                level=level,peak_date=bars[peak].date,trough_date=bars[low.index].date,
                duration=measured['duration'],drop=measured['range'],
                reference_duration=ref['correction_duration'],reference_drop=drop)
            if level=='internal' and self.core:
                self.rhythm_start=self.restore;self.restore=low.index;self.phase='recovering'
                self.ledger[child_id+'@'+ref['owner_id']]=dict(owner_id=child_id,parent_owner=ref['owner_id'],
                    relation='internal',accepted_at=bars[-1].date,state='observed',
                    a=bars[start].date,b=bars[peak].date,c=bars[low.index].date)
            elif level=='core':
                core=self._candidate(bars,start,peak,low.index,low.confirmed)
                if core and start>self.last_ambiguity:
                    self._accept(bars,core,ref['owner_id'],'same_level_successor')
                else:self.phase='unresolved'
            else:self.phase='unresolved'

    def _step(self,bars):
        points=self.swings.get(bars);now=len(bars)-1
        if self.origin and bars[-1].date<self.origin:return
        for region in self.swings.ambiguous:
            if region['confirmed']!=now or (self.origin and bars[region['index']].date<self.origin):continue
            self.last_ambiguity=max(self.last_ambiguity,region['index'])
            self._emit(bars,'wave_order_unknown',region_date=bars[region['index']].date,
                       confirmed_at=bars[-1].date,high=region['high'],low=region['low'])
            self._end(bars,'order_unknown')
        if self.core:
            c=self.core['c'];target=bars[c].low+bars[self.core['b']].high-bars[self.core['a']].low
            if bars[-1].low<bars[c].low:self._end(bars,'floor_broken')
            elif bars[-1].high>=target:self._end(bars,'projection_consumed')
        for low in [p for p in points if p.kind=='low' and p.confirmed==now]:
            if self.origin and bars[low.index].date<self.origin:continue
            self._classify_low(bars,low)
            if self.core is None:
                for i in range(len(points)-2):
                    a,b,c=points[i:i+3]
                    if c.index!=low.index or (a.kind,b.kind,c.kind)!=('low','high','low'):continue
                    boundary=max(self.last_ambiguity,self.ended_at if self.ended_at is not None else -1)
                    if a.index<=boundary or (self.origin and bars[a.index].date<self.origin):continue
                    core=self._candidate(bars,a.index,b.index,c.index,c.confirmed)
                    if core:self._accept(bars,core,None,'independent')
        if self.seed is not None:
            peak=max(range(self.seed,len(bars)),key=lambda i:(bars[i].high,i))
            if peak<len(bars)-1:
                low=min(range(peak+1,len(bars)),key=lambda i:(bars[i].low,-i))
                measured=correction_measure(bars,peak,low)
                ref=self.reference;drop=bars[ref['b']].high-bars[ref['c']].low
                if measured:
                    level=correction_level(now-peak,measured['range'],ref['correction_duration'],drop)
                    if now-peak>ref['correction_duration']+self.right:self._end(bars,'adjustment_timeout')
                    elif self.core and level=='unresolved':self.phase='unresolved'
            elif self.core and self.phase!='child_failed_waiting_for_new_floor':self.phase='recovering'
        if self.core and self.restore is not None:
            if bars[-1].low<bars[self.restore].low:
                self.phase='child_failed_waiting_for_new_floor'
                for record in self.ledger.values():
                    if (record.get('parent_owner')==self.core['owner_id'] and record.get('c')==bars[self.restore].date
                            and record.get('state')=='observed'):
                        record.update(state='failed',failed_at=bars[-1].date)
                        self._emit(bars,'wave_child_failed',owner_id=record['owner_id'],parent_owner=self.core['owner_id'])
            elif (bars[-1].close>bars[self.restore].high
                  and self.phase not in ('unresolved','child_failed_waiting_for_new_floor')):self.phase='active'

    def get(self,bars,origin_date=None):
        if len(bars)<self.count or origin_date!=self.origin:
            self.__init__(self.left,self.right);self.origin=origin_date
        self.events=[]
        for end in range(self.count+1,len(bars)+1):self._step(bars[:end])
        self.count=len(bars)
        if not self.core or self.phase!='active':return None,'wave_'+self.phase,list(self.events)
        core=dict(self.core)
        core.update(impulse=bars[core['b']].high-bars[core['a']].low,
                    correction_area=area(bars,core['b'],core['c']),correction_low=bars[core['c']].low,
                    target=bars[core['c']].low+bars[core['b']].high-bars[core['a']].low,
                    rhythm_floor_date=bars[self.restore].date,
                    rhythm_start_date=bars[self.rhythm_start].date,
                    rhythm_owner=':'.join((core['owner_id'],bars[self.restore].date)),
                    accepted_at=self.ledger[core['owner_id']]['accepted_at'])
        return core,'qualified',list(self.events)
