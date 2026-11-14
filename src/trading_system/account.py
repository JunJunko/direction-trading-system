"""Human phase strategy, annual contraction and profit-backed incremental allocation."""
from datetime import datetime
import math


class AutomaticPolicy:
    """Causal drawdown contraction; no discretionary stage or profit expansion."""
    def __init__(self,config):
        if set(config)-{'drawdown_step','contraction','max_steps'}:
            raise ValueError('Unknown automatic-policy fields')
        self.step=config.get('drawdown_step',.03)
        self.contraction=config.get('contraction',.75)
        self.max_steps=config.get('max_steps',3)
        if (not 0<self.step<1 or not 0<self.contraction<=1
                or type(self.max_steps) is not int or not 1<=self.max_steps<=10):
            raise ValueError('Invalid automatic risk contraction')
        self.peak=0;self.steps=0

    def observe(self,date,equity):
        self.peak=max(self.peak,equity)
        self.steps=max(self.steps,min(self.max_steps,int((1-equity/self.peak+1e-12)/self.step)))
        return dict(stage_id='automatic',allow_entries=True,contraction_steps=self.steps,
                    win_expansion=False,allow_same_level=False,allow_cycle_upgrade=False,
                    multiplier=self.contraction**self.steps)

    def limits(self,base):
        result=dict(base)
        for key in ('risk_per_trade','max_portfolio_risk','max_position_weight','max_gross_weight'):
            result[key]*=self.contraction**self.steps
        return result


class PhasePolicy:
    def __init__(self,config):
        allowed={'stages','safety_cushion','normal_fraction','probe_gross_limit','volatility_budget','symbol_groups'}
        if set(config)-allowed:
            raise ValueError('Unknown account-policy fields')
        self.p=dict(safety_cushion=.10,normal_fraction=.8,probe_gross_limit=.10,volatility_budget=.002)
        self.p.update(config)
        groups=config.get('symbol_groups',{})
        if not isinstance(groups,dict) or any(not isinstance(k,str) or not isinstance(v,str) or not v for k,v in groups.items()):
            raise ValueError('symbol_groups must map symbols to reviewed groups')
        for key in ('safety_cushion','normal_fraction','probe_gross_limit','volatility_budget'):
            v=self.p[key]
            if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) or not 0<v<=1:
                raise ValueError(f'Invalid {key}')
        if self.p['normal_fraction']*1.25>1:
            raise ValueError('Win expansion must fit within unchanged hard risk limits')
        self.stages=list(config.get('stages',[]))
        stage_fields={'id','known_at','effective_from','expires','market_state','system_matched',
                      'gross_limit','allow_win_expansion','allow_cycle_upgrade','allow_same_level','reason'}
        for row in self.stages:
            if set(row)-stage_fields or not {'id','known_at','effective_from','expires','market_state','system_matched','gross_limit','reason'}<=set(row):
                raise ValueError('Stage needs dated, documented market/system evidence')
            for key in ('known_at','effective_from','expires'):
                datetime.strptime(row[key],'%Y%m%d')
            if not row['known_at']<row['effective_from']<=row['expires']:
                raise ValueError('Stage must become effective after its recorded observation')
            if row['market_state'] not in ('uptrend','bottom_confirmed','uncertain','downtrend','halt'):
                raise ValueError('Invalid market state')
            if not row['id'] or not isinstance(row['reason'],str) or not row['reason'].strip():
                raise ValueError('Stage id and rationale required')
            for key in ('system_matched','allow_win_expansion','allow_cycle_upgrade','allow_same_level'):
                if key in row and type(row[key]) is not bool:
                    raise ValueError(f'{key} must be boolean')
            limit=row['gross_limit']
            if isinstance(limit,bool) or not isinstance(limit,(float,int)) or not math.isfinite(limit) or not 0<=limit<=1:
                raise ValueError('Invalid stage gross limit')
        if len({r['id'] for r in self.stages})!=len(self.stages):
            raise ValueError('Stage IDs must be unique')
        self.stages.sort(key=lambda r:(r['effective_from'],r['known_at'],r['id']))
        if len({r['effective_from'] for r in self.stages})!=len(self.stages):
            raise ValueError('Stage effective dates must be unambiguous')
        self.year=None
        self.year_start=None
        self.steps=0
        self.year_steps=0
        self.previous_equity=None
        self.context={}

    def observe(self,date,equity):
        if self.year!=date[:4]:
            self.year=date[:4]
            self.year_start=equity
            self.year_steps=self.steps
        decline=max(0,1-equity/self.year_start)
        self.steps=max(self.steps,min(3,self.year_steps+int((decline+1e-12)/.03)))
        self.previous_equity=equity
        eligible=[s for s in self.stages if s['known_at']<date and s['effective_from']<=date]
        stage=eligible[-1] if eligible else None
        if stage and date>stage['expires']:
            stage=None
        matched=bool(stage and stage['system_matched'])
        allow=matched and stage['market_state'] not in ('downtrend','halt')
        annual_gain=equity/self.year_start-1
        expansion=bool(allow and not self.steps and stage.get('allow_win_expansion')
                       and annual_gain>=self.p['safety_cushion'])
        multiplier=self.p['normal_fraction']*(.75**self.steps)*(1.25 if expansion else 1)
        self.context=dict(stage_id=stage['id'] if stage else None,allow_entries=allow,
                          market_state=stage['market_state'] if stage else 'unreviewed',
                          stage_reason=stage['reason'] if stage else 'missing_current_human_stage',
                          contraction_steps=self.steps,win_expansion=expansion,multiplier=multiplier,
                          gross_limit=stage['gross_limit'] if stage else 0,
                          allow_cycle_upgrade=bool(allow and stage.get('allow_cycle_upgrade') and not self.steps),
                          allow_same_level=bool(expansion and stage.get('allow_same_level')))
        return self.context

    def multiplier(self,equity,peak):
        return self.context.get('multiplier',self.p['normal_fraction'])

    def limits(self,base,equity,positions,marks):
        p=dict(base)
        mult=self.multiplier(equity,equity)
        p['risk_per_trade']*=mult
        p['max_portfolio_risk']*=mult
        p['max_position_weight']*=mult
        p['max_gross_weight']=min(base['max_gross_weight']*mult,self.context['gross_limit'])
        # Existing positions must pay for expansion with real marked profit, net of
        # their original entry fee. Merely emitting many new signals cannot expand.
        protected=any((marks[s]-x.entry)*x.quantity-x.entry_fee>x.initial_risk
                      for s,x in positions.items())
        if not protected:
            p['max_gross_weight']=min(p['max_gross_weight'],self.p['probe_gross_limit']*mult)
        # RiskManager validates nonzero caps separately. Closed entry gates are
        # handled before sizing, not represented by an invalid zero-weight manager.
        p['max_position_weight']=min(p['max_position_weight'],p['max_gross_weight'])
        return p
