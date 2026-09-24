"""User profile context provider for retrieval."""

from __future__ import annotations

import inspect
from typing import Any, Dict, Optional


PROFILE_SOURCE = "main.final_main.Profile_main.profile_for_retrieval"


class ProfileProvider:
    def __init__(self, profile_main: Optional[Any] = None):
        self.profile_main = profile_main

    async def get_profile(self, role_id: str) -> Dict[str, Any]:
        try:
            profile_main = self._get_profile_main()
            result = profile_main.profile_for_retrieval(role_id)
            if inspect.isawaitable(result):
                result = await result
            content = "" if result is None else str(result)
            return {
                "available": True,
                "content": content,
                "source": PROFILE_SOURCE,
                "error": "",
            }
        except Exception as exc:
            return {
                "available": False,
                "content": "",
                "source": PROFILE_SOURCE,
                "error": str(exc) or exc.__class__.__name__,
            }

    def _get_profile_main(self) -> Any:
        if self.profile_main is None:
            from main.final_main import Profile_main

            self.profile_main = Profile_main()
        return self.profile_main
