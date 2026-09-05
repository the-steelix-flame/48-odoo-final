from django.contrib import admin

from apps.negotiation.models import (
    NegotiationMessage,
    NegotiationRequest,
    NegotiationThread,
    PortalToken,
)

admin.site.register([PortalToken, NegotiationThread, NegotiationMessage, NegotiationRequest])
