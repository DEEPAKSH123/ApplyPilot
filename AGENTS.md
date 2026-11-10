# Instructions & Guidelines for Agents Working on ApplyPilot

Refer to `../MEMORY.md` for the complete operational history and candidate persona.

## Critical Invariants for Developers & AI Agents:

1. **Browser Navigation:**
   * When opening URLs from the web dashboard, ALWAYS invoke `window.open(url, '_blank')` in the frontend click handler.
   * Do NOT rely solely on Python spawning `brave.exe` or background OS subprocesses to open tabs—Windows Focus Stealing Prevention will block foreground switching when Brave is already open.
   * Use native JavaScript `navigator.clipboard.writeText(...)` for copying files or notes to clipboard with zero latency.

2. **User Profiles:**
   * Do not configure automated scripts to use isolated, empty browser profiles (`data/brave_profile`) for human workflows.
   * Deepak's personal credentials and session cookies are located in his standard Brave profile (`%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data`).

3. **URL Sanitization:**
   * Verify all URLs start with `http://` or `https://`.
   * Never permit `"None"`, `"http://none/"`, or dead links to enter `applypilot.db` or `opportunities.csv`.

4. **Autonomy Constraint:**
   * NEVER instruct the user to open a terminal or run commands.
   * Perform all setup, migrations, database queries, and background daemon monitoring autonomously.
