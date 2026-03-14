"""Matrix channel adapter for Carapace.

Connects to a Matrix homeserver via matrix-nio (plain-text, no E2EE for now).
Maps one session per room; supports slash commands including /reset.
"""

from __future__ import annotations

from carapace.channels.matrix.approval import PendingApproval as _PendingApproval
from carapace.channels.matrix.approval import PendingDomainApproval as _PendingDomainApproval
from carapace.channels.matrix.channel import MatrixChannel
from carapace.channels.matrix.commands import handle_matrix_slash_command as _handle_matrix_slash_command
from carapace.channels.matrix.formatting import (
    format_approval_request as _format_approval_request,
)
from carapace.channels.matrix.formatting import (
    format_command_result_text as _format_command_result_text,
)
from carapace.channels.matrix.formatting import (
    format_domain_escalation as _format_domain_escalation,
)
from carapace.channels.matrix.formatting import (
    md_to_html as _md_to_html,
)

__all__ = [
    "MatrixChannel",
    "_PendingApproval",
    "_PendingDomainApproval",
    "_format_approval_request",
    "_format_command_result_text",
    "_format_domain_escalation",
    "_handle_matrix_slash_command",
    "_md_to_html",
]
