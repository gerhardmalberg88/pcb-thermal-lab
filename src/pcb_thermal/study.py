"""Numerical acceptance checks across independently completed thermal runs."""
import csv
import json
import os
from pathlib import Path
import numpy as np
from .common import WorkflowError


def write_study_report(root, section, records, status, acceptance=None, detail=None):
    """Keep a readable index beside native runs, including partial studies."""
    root=Path(root)
    rows=[]
    for record in records:
        s=record['summary'];resource=s.get('resources') or {}
        rows.append({'case':record['case'],'h_w_m2k':s['h_w_m2k'],
                     'resistor_heat_w':s['resistor_heat_w'],
                     'maximum_temperature_c':s['maximum_temperature_c'],
                     'board_maximum_c':s['board_maximum_c'],
                     'heat_balance_relative_error':s['maximum_heat_balance_relative_error'],
                     'solver_wall_seconds':resource.get('wall_seconds'),
                     'solver_peak_rss_bytes':resource.get('peak_process_tree_rss_bytes_sampled'),
                     'report':os.path.relpath(Path(record['path'])/'postprocess/report.md',root)})
    if rows:
        with (root/f'study-{section}.csv').open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
    text=[f'# Balancing-resistor study: {section}','',f'Status: **{status}**. Completed runs: {len(rows)}.','',
          'These are resistor-only predictions. Ambient, material, solder and plating assumptions are listed in each run report. Mesh/domain convergence and hardware correlation remain separate from heat-balance verification.','',
          '| Case | h W/m²K | Resistor heat W | Maximum °C | Board maximum °C | Heat residual % |',
          '|---|---:|---:|---:|---:|---:|']
    if detail and detail.get('status') == 'unconverged':
        text[4:4] = ['**Detailed-region validation failed. These completed solves remain provisional; execution completion does not establish model convergence.**', '']
    for r in rows:
        text.append(f'| [{r["case"]}]({r["report"]}) | {r["h_w_m2k"]:g} | {r["resistor_heat_w"]:.6f} | {r["maximum_temperature_c"]:.3f} | {r["board_maximum_c"]:.3f} | {100*r["heat_balance_relative_error"]:.3g} |')
    if acceptance:
        text+=['','## Numerical comparisons','']
        for name,check in acceptance.items():
            text.append(f'- [{name}]({name}-convergence.json): {"PASS" if check["pass"] else "UNCONVERGED"}; last-pair maximum change {check["maximum_change_c"]:.6g} °C. Production-baseline checks are included where applicable.')
    detail_note = 'Provisional until full domain validation and hardware correlation'
    if detail and detail.get('status') in ('pass', 'unconverged'):
        check = detail['comparison']
        verdict = 'PASS (limited check only)' if check['pass'] else 'UNCONVERGED'
        text += ['', f'## Detailed-region comparison: {verdict}', '',
                 f'10 versus 20 mm at automatic h=10: maximum local hotspot change **{check["maximum_change_c"]:.6f} °C** '
                 f'(**{100*check["relative_to_temperature_rise"]:.3f}%** of reference peak rise). '
                 'Acceptance requires both <1 °C and <2%. Full 30 mm/crop validation and hardware correlation are not established by this limited check.', '',
                 '[Detailed comparison data](limited-detail-comparison.json)', '']
        if not check['pass']:
            detail_note = f'PROVISIONAL: detail check failed — {check["maximum_change_c"]:.3f} °C / {100*check["relative_to_temperature_rise"]:.2f}% local change'
    if section=='steady' and len(rows)>=2:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
        for schedule in ('automatic','odd','even'):
            selected=sorted((r for r in rows if r['case'].startswith(schedule+'-h')),key=lambda r:r['h_w_m2k'])
            if not selected:continue
            for ax,key in zip(axes,('maximum_temperature_c','board_maximum_c')):
                ax.plot([r['h_w_m2k'] for r in selected],[r[key] for r in selected],marker='o',label=schedule)
                ax.set_xlabel('Convection coefficient (W/m²K)');ax.set_ylabel('Temperature (°C)');ax.grid(alpha=.25)
        axes[0].set_title('Maximum modeled temperature');axes[1].set_title('Maximum PCB temperature')
        axes[1].legend();fig.suptitle('Balancing-resistor heating: completed convection cases\n'+detail_note,fontsize=11)
        fig.savefig(root/'steady-convection.png',dpi=160);plt.close(fig)
        text+=['','![Convection sensitivity](steady-convection.png)','']
    text+=['',f'[CSV table](study-{section}.csv) · [Progress and provenance](study-{section}.json)','']
    (root/f'study-{section}.md').write_text('\n'.join(text))


def compare_runs(left, right):
    """Compare extrema and, for transients, every common history time.

    Use the finer run's peak temperature rise as the relative-error scale.
    Comparing only the final cooled frame would miss warm-up/phase errors.
    """
    left, right = Path(left), Path(right)
    summaries = [json.loads((p/'postprocess/summary.json').read_text()) for p in (left, right)]
    a, b = summaries
    if a['analysis'] != b['analysis'] or a['ambient_c'] != b['ambient_c']:
        raise WorkflowError('Convergence runs must have matching analysis and ambient')
    rise = b['maximum_temperature_c'] - b['ambient_c']
    if rise <= 0:
        raise WorkflowError('Convergence requires a positive reference temperature rise')
    changes = {key: abs(a[key]-b[key]) for key in ('maximum_temperature_c','board_maximum_c')}
    ar = {r['reference']: r for r in a['resistors']}
    br = {r['reference']: r for r in b['resistors']}
    if ar.keys() != br.keys():
        raise WorkflowError('Convergence runs have different heater selections')
    changes.update({ref: abs(ar[ref]['maximum_c']-br[ref]['maximum_c']) for ref in ar})
    history = None
    if a['analysis'] == 'transient':
        x, y = [np.genfromtxt(p/'postprocess/history.csv',delimiter=',',names=True) for p in (left,right)]
        tx, ty = np.atleast_1d(x['time_s']), np.atleast_1d(y['time_s'])
        if np.any(np.diff(tx)<=0) or np.any(np.diff(ty)<=0) or not np.isclose(tx[-1],ty[-1]):
            raise WorkflowError('Transient convergence histories have incompatible time ranges')
        index = np.searchsorted(ty,tx)
        if np.any(index>=len(ty)) or not np.allclose(ty[index],tx,rtol=0,atol=1e-8):
            raise WorkflowError('Fine transient history does not include every coarse time')
        columns = [name for name in x.dtype.names if name.endswith(('_min_k','_max_k','_mean_k'))]
        if not columns or not all(name in y.dtype.names for name in columns):
            raise WorkflowError('Missing temperature history columns')
        history = {name: float(np.max(np.abs(np.atleast_1d(x[name])-np.atleast_1d(y[name])[index]))) for name in columns}
    error = max(list(changes.values()) + (list(history.values()) if history else []))
    balance = all(s['heat_balance_pass'] for s in summaries)
    return {'runs':[str(left),str(right)],'hotspot_changes_c':changes,
            'common_time_history_changes_c':history,'maximum_change_c':error,
            'reference_peak_rise_c':rise,'relative_to_temperature_rise':error/rise,
            'heat_balance_pass':balance,'pass':bool(error<1 and error/rise<.02 and balance),
            'criterion':'Every reported hotspot and common-time temperature differs by <1 C AND <2% of reference peak rise; both heat balances pass'}
