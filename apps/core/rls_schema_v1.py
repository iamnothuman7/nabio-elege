"""Versioned RLS migration builder. Keep v1 stable; evolve policies in migrations.

Identity/routing tables are deliberately outside this campaign data boundary.
RLS is defense in depth, not a replacement for permissions or per-case ACLs.
"""

CONTROL_PLANE = frozenset(
    {
        "campaigns.tenant",
        "campaigns.campaign",
        "campaigns.permission",
        "campaigns.role",
        "campaigns.membership",
        "core.inboxevent",
        "workspace.securityprofile",
        "workspace.loginguard",
    }
)
APP_LABELS = {"campaigns", "core", "forms", "finance", "operations", "workspace"}


def scope_models(registry):
    models = {
        model._meta.label_lower: model
        for model in registry.get_models()
        if model._meta.app_label in APP_LABELS
        and not model._meta.abstract
        and not model._meta.auto_created
    }
    scoped = {
        label: model for label, model in models.items() if label not in CONTROL_PLANE
    }
    return scoped


def policy_plan(registry, connection):
    quote = connection.ops.quote_name
    models = scope_models(registry)
    campaign = "NULLIF(current_setting('nabio.campaign_id', true), '')::uuid"
    tenant = "NULLIF(current_setting('nabio.tenant_id', true), '')::uuid"
    actor = "NULLIF(current_setting('nabio.actor_id', true), '')::bigint"
    plan = {}
    for label, model in sorted(models.items()):
        table = quote(model._meta.db_table)
        fields = {field.name: field for field in model._meta.fields}
        if "campaign" in fields and "tenant" in fields:
            predicate = f"(campaign_id = {campaign} AND tenant_id = {tenant})"
        elif "tenant" in fields:
            predicate = f"tenant_id = {tenant}"
        elif "campaign" in fields:
            predicate = f"campaign_id = {campaign}"
        else:
            parents = []
            for field in fields.values():
                related = getattr(field, "related_model", None)
                if (
                    related is None
                    or related._meta.label_lower not in models
                    or related is model
                ):
                    continue
                parent = quote(related._meta.db_table)
                pk = quote(related._meta.pk.column)
                column = f"{table}.{quote(field.column)}"
                check = f"EXISTS (SELECT 1 FROM {parent} AS parent WHERE parent.{pk} = {column})"
                if field.null:
                    check = f"({column} IS NULL OR {check})"
                parents.append(check)
            if not parents:
                raise ValueError(
                    f"Modelo sem política de isolamento explícita: {label}"
                )
            predicate = " AND ".join(parents)
        statements = [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        ]
        if label == "core.auditevent":
            # Authentication events have no campaign. Only their actor can read
            # them. Anonymous authentication auditing may INSERT, never read all.
            own_global = (
                f"(campaign_id IS NULL AND tenant_id IS NULL AND actor_id = {actor})"
            )
            statements.extend(
                [
                    f"CREATE POLICY nabio_read ON {table} FOR SELECT USING ({predicate} OR {own_global})",
                    f"CREATE POLICY nabio_append ON {table} FOR INSERT WITH CHECK ({predicate} OR (campaign_id IS NULL AND tenant_id IS NULL))",
                ]
            )
        else:
            statements.append(
                f"CREATE POLICY nabio_scope ON {table} USING ({predicate}) WITH CHECK ({predicate})"
            )
        if label == "forms.sourcelink":
            statements.append(
                f"CREATE POLICY nabio_public_route ON {table} FOR SELECT USING (revoked_at IS NULL AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) AND public_code = NULLIF(current_setting('nabio.public_code', true), ''))"
            )
        if label == "workspace.invitation":
            statements.append(
                f"CREATE POLICY nabio_invitation_route ON {table} FOR SELECT USING (accepted_at IS NULL AND revoked_at IS NULL AND expires_at > CURRENT_TIMESTAMP AND token_hash = NULLIF(current_setting('nabio.invitation_hash', true), ''))"
            )
        plan[model._meta.db_table] = statements
    return plan


def install(registry, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for statements in policy_plan(registry, schema_editor.connection).values():
        for statement in statements:
            schema_editor.execute(statement)
