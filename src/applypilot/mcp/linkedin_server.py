"""LinkedIn MCP Server for ApplyPilot & Antigravity.

Exposes tools to:
- Check LinkedIn authentication status.
- Trigger interactive login via Brave browser.
- Search hiring posts and discover recruiter emails.
- Search RVCE alumni and connections at target companies.
- Open profiles and posts directly in active Brave browser.
"""

import os
import subprocess
import webbrowser
from typing import Any

from mcp.server.mcpserver import MCPServer

from applypilot.networking.linkedin import (
    is_linkedin_authenticated,
    login_to_linkedin,
    search_linkedin_posts,
    search_linkedin_connections
)

mcp = MCPServer(
    name="applypilot-linkedin",
    version="1.0.0",
    description="LinkedIn automation server for finding hiring posts, alumni referrals, and recruiter leads."
)

BRAVE_EXE = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"


@mcp.tool(
    name="linkedin_status",
    description="Check whether Deepak is currently logged into LinkedIn with saved session cookies."
)
def linkedin_status() -> dict[str, Any]:
    """Check LinkedIn login status."""
    auth = is_linkedin_authenticated()
    return {
        "authenticated": auth,
        "message": "LinkedIn session active and ready!" if auth else "Not logged in. Use linkedin_login to connect."
    }


@mcp.tool(
    name="linkedin_login",
    description="Launch Brave browser for Deepak to log in to LinkedIn and securely save session cookies."
)
def linkedin_login_tool(timeout_seconds: int = 75) -> dict[str, Any]:
    """Launch interactive browser to log in to LinkedIn."""
    return login_to_linkedin(timeout_sec=timeout_seconds, headed=True)


@mcp.tool(
    name="linkedin_search_posts",
    description="Search LinkedIn for live recruiter hiring posts, extracting text, author info, and recruiter email addresses."
)
def linkedin_search_posts_tool(
    keywords: str = 'backend engineer AND ("hiring" OR "requirement")',
    max_results: int = 10,
    save_to_leads_db: bool = True
) -> list[dict[str, Any]]:
    """Search hiring posts on LinkedIn."""
    return search_linkedin_posts(keywords=keywords, max_results=max_results, save_to_db=save_to_leads_db)


@mcp.tool(
    name="linkedin_search_connections",
    description="Search LinkedIn for RVCE alumni, engineering managers, or connections at a target company (e.g. PhonePe, Stripe, Swiggy)."
)
def linkedin_search_connections_tool(
    company: str,
    role: str = "backend",
    school: str = "RV College of Engineering",
    max_results: int = 10
) -> list[dict[str, Any]]:
    """Search people and alumni on LinkedIn."""
    return search_linkedin_connections(company=company, role=role, school=school, max_results=max_results)


@mcp.tool(
    name="linkedin_open_in_brave",
    description="Open any LinkedIn profile, job post, or search URL directly in Deepak's active Brave browser."
)
def linkedin_open_in_brave_tool(url: str) -> dict[str, Any]:
    """Open URL in active Brave browser."""
    if not url or not (str(url).startswith("http://") or str(url).startswith("https://")):
        return {"status": "error", "message": "Invalid URL provided"}
    try:
        if os.path.exists(BRAVE_EXE):
            subprocess.Popen([BRAVE_EXE, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif hasattr(os, "startfile"):
            os.startfile(url)
        else:
            webbrowser.open(url)
        return {"status": "opened", "url": url}
    except Exception as e:
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    mcp.run()
