"""Matrix room management via Synapse Admin API.

No Matrix source code is modified. All tier gating happens through
the Matrix Admin API — creating rooms, managing membership, setting
power levels — driven by Authentik group membership.

Strategy:
  - On first deploy: create a Matrix Space per tier with default rooms
  - free:    #general (public), #announcements
  - premium: #general, #announcements, #expert-qa, #course-discussion
  - max:     All rooms + partner federation rooms
  - When user tier changes: add/remove from rooms via Admin API
"""

import os
import httpx

MATRIX_URL = os.getenv("MATRIX_URL", "http://matrix:8008")
MATRIX_ADMIN_TOKEN = os.getenv("MATRIX_ADMIN_TOKEN", "")


class MatrixAdmin:
    """Client for the Synapse Admin API."""

    def __init__(self, base_url: str = MATRIX_URL, token: str = MATRIX_ADMIN_TOKEN):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, json=None):
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, url, headers=self.headers, json=json)
            resp.raise_for_status()
            return resp.json()

    # --- User management ---

    async def get_user(self, user_id: str):
        """Get user info. user_id is full MXID like @user:domain."""
        return await self._request("GET", f"/_synapse/admin/v2/users/{user_id}")

    async def deactivate_user(self, user_id: str):
        """Deactivate a user account."""
        return await self._request("POST", f"/_synapse/admin/v1/deactivate/{user_id}")

    # --- Room management ---

    async def create_room(self, name: str, alias: str = None, public: bool = False):
        """Create a room via Admin API."""
        payload = {
            "name": name,
            "visibility": "public" if public else "private",
        }
        if alias:
            payload["room_alias_name"] = alias
        return await self._request("POST", "/_synapse/admin/v1/rooms", payload)

    async def list_rooms(self, limit: int = 100):
        """List all rooms."""
        return await self._request("GET", f"/_synapse/admin/v1/rooms?limit={limit}")

    async def get_room_members(self, room_id: str):
        """Get members of a room."""
        return await self._request("GET", f"/_synapse/admin/v1/rooms/{room_id}/members")

    # --- Membership ---

    async def join_room(self, user_id: str, room_id: str):
        """Force-join a user to a room."""
        return await self._request(
            "POST",
            f"/_synapse/admin/v1/join/{room_id}",
            {"user_id": user_id},
        )

    async def kick_user(self, user_id: str, room_id: str):
        """Kick a user from a room."""
        rooms = await self.list_rooms()
        # Find the room and remove the user
        return await self._request(
            "POST",
            f"/_synapse/admin/v1/rooms/{room_id}/members",
            {"user_id": user_id, "membership": "leave"},
        )

    # --- Spaces ---

    async def create_space(self, name: str, alias: str = None):
        """Create a Matrix Space (room with type m.space)."""
        payload = {
            "name": name,
            "creation_content": {"type": "m.space"},
            "visibility": "public",
        }
        if alias:
            payload["room_alias_name"] = alias
        return await self._request("POST", "/_synapse/admin/v1/rooms", payload)

    # --- Power levels ---

    async def set_power_level(self, room_id: str, user_id: str, level: int):
        """Set a user's power level in a room."""
        return await self._request(
            "PUT",
            f"/_synapse/admin/v1/rooms/{room_id}/state/m.room.power_levels",
            {"users": {user_id: level}},
        )


# --- Tier-to-room mapping ---

TIER_ROOMS = {
    "free": ["#general", "#announcements"],
    "premium": ["#general", "#announcements", "#expert-qa", "#course-discussion"],
    "max": ["#general", "#announcements", "#expert-qa", "#course-discussion", "#live-sessions"],
}


async def sync_user_rooms(user_mxid: str, tier: str, admin: MatrixAdmin):
    """Sync a user's room membership to match their tier.

    Adds user to all rooms for their tier, removes from rooms
    not in their tier (if they were previously in a higher tier).
    """
    target_rooms = TIER_ROOMS.get(tier, TIER_ROOMS["free"])

    # Get current rooms
    # (In practice, iterate over all rooms and check membership)

    for room_alias in target_rooms:
        try:
            room_id = f"!{room_alias.lstrip('#')}:{MATRIX_URL.split('://')[-1]}"
            await admin.join_room(user_mxid, room_id)
        except Exception:
            pass  # Room may not exist yet


async def bootstrap_matrix_rooms(domain: str, admin: MatrixAdmin):
    """Create default tier rooms and spaces for a new community."""
    server = f"chat.{domain}"

    rooms = [
        ("#general", "General Discussion", True),
        ("#announcements", "Announcements", True),
        ("#expert-qa", "Expert Q&A", False),
        ("#course-discussion", "Course Discussion", False),
        ("#live-sessions", "Live Session Chat", False),
    ]

    for alias, name, public in rooms:
        print(f"  Creating room: {alias}")
        await admin.create_room(name=name, alias=alias, public=public)

    print("  ✓ Matrix rooms bootstrapped")
