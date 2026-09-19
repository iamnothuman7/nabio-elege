from django.contrib import admin

from .models import Campaign, CampaignPhaseEvent, Membership, Permission, Role, Tenant


admin.site.register([Tenant, Campaign, Permission, Role, Membership, CampaignPhaseEvent])
