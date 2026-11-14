"""Use the verified trade/chart audit for all standard-cost combined arms."""
import audit_candidate_policy as audit
audit.RUN=audit.ROOT/'runs/20261109-qualified-candidates-verified'
audit.OUT=audit.RUN/'chart-audit'
audit.POLICIES=list(audit.load(audit.RUN/'protocol.json')['configs'])
audit.main()
