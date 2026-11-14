"""Apply the identical excursion and expectancy audit to IHS accounts."""
import diagnose_w_expectancy as audit

if __name__=='__main__':
    audit.OUT=audit.ROOT/'runs/20261110-ihs-expectancy-diagnosis'
    audit.CASES={
        label:audit.ROOT/'runs/20261110-quality-entry'/f'IHS_{rule}_cost{cost}'
        for label,rule,cost in [('baseline','baseline',1),('no_gap_up','no_gap_up',1),
                               ('baseline_cost2','baseline',2),('no_gap_up_cost2','no_gap_up',2)]}
    audit.main()
