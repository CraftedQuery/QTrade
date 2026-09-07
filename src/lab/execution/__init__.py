"""Paper execution and deterministic risk (Release 0.3).

Proposals come from the 0.2 baseline sleeves. The risk engine has final
authority. The only broker path is Alpaca **paper**. Unattended sessions
refuse to start while risk limits are still provisional.
"""

from lab.execution.session import PaperSession, ProvisionalLimitsError, UnreconciledError

__all__ = ["PaperSession", "ProvisionalLimitsError", "UnreconciledError"]
