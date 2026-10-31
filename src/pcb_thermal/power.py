"""Electrical accounting for nonadjacent BQ79616 balancing channels."""
import re
import math
from .common import WorkflowError

def derive(board, case):
    cfg=case['sources']; components={x['ref']:x for x in board['components']}
    selected={}
    for ref in cfg['refs']:
        if ref not in components:raise WorkflowError(f'Heat-source reference not found: {ref}')
        c=components[ref]
        if c.get('dnp'):raise WorkflowError(f'Heat-source reference is DNP: {ref}')
        selected[ref]=c
    if cfg.get('kind','balancing')=='watts':
        powers={ref:float(cfg['watts'][ref]) for ref in selected}
        if any(not math.isfinite(p) or p<0 for p in powers.values()) or sum(powers.values())<=0:
            raise WorkflowError('Heater powers must be finite and nonnegative, with positive total input')
        return {'schema':1,'kind':'watts','resistors':{r:{'odd_w':p,'even_w':p,'average_w':p} for r,p in powers.items()},'total_w':sum(powers.values()),'switch_loss_w':0.0}
    nodes={}
    for ref,c in selected.items():
        cb=[]; tap=[]
        for pad in c['pads']:
            match=re.search(r'(?:^|/)CB(\d+)$',pad['net'])
            if match: cb.append(int(match[1]))
            else:tap.append(pad['net'])
        if len(cb)!=1 or len(tap)!=1 or cb[0] in nodes:
            raise WorkflowError(f'{ref} must join exactly one unique CB node to a cell tap')
        n=cb[0]; expected=('GND' if n==0 else '+BATT' if n==16 else '/balance/cell'+str(n))
        if tap[0]!=expected:raise WorkflowError(f'{ref}: CB{n} connects to {tap[0]}, expected {expected}')
        if not re.match(r'^20(?:R|\s|$)',c['value']):raise WorkflowError(f'{ref} is not the expected 20-ohm balancing resistor')
        nodes[n]=ref
    if set(nodes)!=set(range(17)):raise WorkflowError('The supplied BQ79616 case requires CB0 through CB16')
    r=float(cfg['resistance_ohm']);rf=float(cfg['switch_resistance_ohm']);v=float(cfg['cell_voltage_v'])
    current=v/(2*r+rf); p=current*current*r
    result={ref:{'cb_node':n,'odd_w':0.0,'even_w':0.0} for n,ref in nodes.items()}
    channels=[]
    for channel in range(1,17):
        phase='odd' if channel%2 else 'even'
        for n in (channel-1,channel):result[nodes[n]][phase+'_w']+=p
        channels.append({'channel':channel,'phase':phase,'refs':[nodes[channel-1],nodes[channel]],'current_a':current,'resistor_power_w':2*p,'switch_power_w':current*current*rf,'cell_power_w':v*current})
    schedule=cfg.get('schedule','automatic')
    for x in result.values(): x['average_w']=(x['odd_w']+x['even_w'])/2 if schedule=='automatic' else x[schedule+'_w']
    return {'schema':1,'kind':'balancing','schedule':schedule,'phase_s':cfg['phase_s'],
            'cell_voltage_v':v,'resistance_ohm':r,'switch_resistance_ohm':rf,
            'resistors':result,'channels':channels,'total_w':sum(x['average_w'] for x in result.values()),
            'switch_loss_w':8*current*current*rf,'assumption':'Constant 4.2 V cells; datasheet minimum switch resistance; no diagnostic/thermal pauses; only external resistor losses heat the FEM model.'}

def at_time(power,ref,t,on_s):
    if t>=on_s:return 0.0
    x=power['resistors'][ref]
    if power.get('schedule')=='automatic':return x['odd_w'] if int(t/power['phase_s'])%2==0 else x['even_w']
    return x['average_w']
