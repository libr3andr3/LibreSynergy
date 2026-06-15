"""Tier management — sync user tiers with Authentik groups."""

from api.auth import authentik


# Group UUIDs — set during Authentik bootstrap, stored here for runtime
GROUP_UUIDS = {
    "free": None,
    "premium": None,
    "max": None,
}


async def set_user_tier(user_sub: str, tier: str):
    """Set a user's tier by managing their Authentik group membership.

    Args:
        user_sub: The Authentik user UUID (sub claim).
        tier: One of 'free', 'premium', 'max'.
    """
    if tier not in GROUP_UUIDS:
        raise ValueError(f"Unknown tier: {tier}")

    # Ensure we have group UUIDs
    for t in GROUP_UUIDS:
        if GROUP_UUIDS[t] is None:
            group = await authentik.get_group_by_name(t)
            if group:
                GROUP_UUIDS[t] = group["pk"]

    # Remove user from all tier groups
    for t, gid in GROUP_UUIDS.items():
        if gid and t != tier:
            try:
                await authentik.remove_user_from_group(user_sub, gid)
            except Exception:
                pass  # User may not be in that group

    # Add user to the target tier group
    target_gid = GROUP_UUIDS[tier]
    if target_gid:
        await authentik.add_user_to_group(user_sub, target_gid)


async def get_user_tier(user_sub: str) -> str:
    """Get a user's current tier from Authentik groups."""
    groups = await authentik.get_user_groups(user_sub)
    group_names = [g.get("name", "") for g in groups]

    for tier in ["max", "premium", "free"]:
        if tier in group_names:
            return tier

    return "free"


def set_group_uuids(uuids: dict):
    """Update the cached group UUIDs (called after Authentik bootstrap)."""
    GROUP_UUIDS.update(uuids)
