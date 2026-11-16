"""ApplyPilot CLI — the main entry point."""

from __future__ import annotations

import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from applypilot import __version__

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

app = typer.Typer(
    name="applypilot",
    help="AI-powered end-to-end job application pipeline.",
    no_args_is_help=True,
)
console = Console()
log = logging.getLogger(__name__)

# Valid pipeline stages (in execution order)
VALID_STAGES = ("discover", "enrich", "score", "tailor", "cover", "pdf")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bootstrap() -> None:
    """Common setup: load env, create dirs, init DB."""
    from applypilot.config import load_env, ensure_dirs
    from applypilot.database import init_db

    load_env()
    ensure_dirs()
    init_db()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold]applypilot[/bold] {__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """ApplyPilot — AI-powered end-to-end job application pipeline."""


@app.command()
def init() -> None:
    """Run the first-time setup wizard (profile, resume, search config)."""
    from applypilot.wizard.init import run_wizard

    run_wizard()


@app.command()
def run(
    stages: Optional[list[str]] = typer.Argument(
        None,
        help=(
            "Pipeline stages to run. "
            f"Valid: {', '.join(VALID_STAGES)}, all. "
            "Defaults to 'all' if omitted."
        ),
    ),
    min_score: int = typer.Option(7, "--min-score", help="Minimum fit score for tailor/cover stages."),
    workers: int = typer.Option(4, "--workers", "-w", help="Parallel threads for discovery/enrichment stages."),
    stream: bool = typer.Option(False, "--stream", help="Run stages concurrently (streaming mode)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview stages without executing."),
    validation: str = typer.Option(
        "normal",
        "--validation",
        help=(
            "Validation strictness for tailor/cover stages. "
            "strict: banned words = errors, judge must pass. "
            "normal: banned words = warnings only (default, recommended for Gemini free tier). "
            "lenient: banned words ignored, LLM judge skipped (fastest, fewest API calls)."
        ),
    ),
) -> None:
    """Run pipeline stages: discover, enrich, score, tailor, cover, pdf."""
    _bootstrap()

    from applypilot.pipeline import run_pipeline

    stage_list = stages if stages else ["all"]

    # Validate stage names
    for s in stage_list:
        if s != "all" and s not in VALID_STAGES:
            console.print(
                f"[red]Unknown stage:[/red] '{s}'. "
                f"Valid stages: {', '.join(VALID_STAGES)}, all"
            )
            raise typer.Exit(code=1)

    # Gate AI stages behind Tier 2
    llm_stages = {"score", "tailor", "cover"}
    if any(s in stage_list for s in llm_stages) or "all" in stage_list:
        from applypilot.config import check_tier
        check_tier(2, "AI scoring/tailoring")

    # Validate the --validation flag value
    valid_modes = ("strict", "normal", "lenient")
    if validation not in valid_modes:
        console.print(
            f"[red]Invalid --validation value:[/red] '{validation}'. "
            f"Choose from: {', '.join(valid_modes)}"
        )
        raise typer.Exit(code=1)

    result = run_pipeline(
        stages=stage_list,
        min_score=min_score,
        dry_run=dry_run,
        stream=stream,
        workers=workers,
        validation_mode=validation,
    )

    if result.get("errors"):
        raise typer.Exit(code=1)


@app.command()
def apply(
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max applications to submit."),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of parallel browser workers."),
    min_score: int = typer.Option(7, "--min-score", help="Minimum fit score for job selection."),
    model: str = typer.Option("haiku", "--model", "-m", help="Claude model name."),
    continuous: bool = typer.Option(False, "--continuous", "-c", help="Run forever, polling for new jobs."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview actions without submitting."),
    headless: bool = typer.Option(False, "--headless", help="Run browsers in headless mode."),
    url: Optional[str] = typer.Option(None, "--url", help="Apply to a specific job URL."),
    gen: bool = typer.Option(False, "--gen", help="Generate prompt file for manual debugging instead of running."),
    mark_applied: Optional[str] = typer.Option(None, "--mark-applied", help="Manually mark a job URL as applied."),
    mark_failed: Optional[str] = typer.Option(None, "--mark-failed", help="Manually mark a job URL as failed (provide URL)."),
    fail_reason: Optional[str] = typer.Option(None, "--fail-reason", help="Reason for --mark-failed."),
    reset_failed: bool = typer.Option(False, "--reset-failed", help="Reset all failed jobs for retry."),
) -> None:
    """Launch auto-apply to submit job applications."""
    _bootstrap()

    from applypilot.config import check_tier, PROFILE_PATH as _profile_path
    from applypilot.database import get_connection

    # --- Utility modes (no Chrome/Claude needed) ---

    if mark_applied:
        from applypilot.apply.launcher import mark_job
        mark_job(mark_applied, "applied")
        console.print(f"[green]Marked as applied:[/green] {mark_applied}")
        return

    if mark_failed:
        from applypilot.apply.launcher import mark_job
        mark_job(mark_failed, "failed", reason=fail_reason)
        console.print(f"[yellow]Marked as failed:[/yellow] {mark_failed} ({fail_reason or 'manual'})")
        return

    if reset_failed:
        from applypilot.apply.launcher import reset_failed as do_reset
        count = do_reset()
        console.print(f"[green]Reset {count} failed job(s) for retry.[/green]")
        return

    # --- Full apply mode ---

    # Check: Profile exists
    if not _profile_path.exists():
        console.print(
            "[red]Profile not found.[/red]\n"
            "Run [bold]applypilot init[/bold] to create your profile first."
        )
        raise typer.Exit(code=1)

    from applypilot.apply.assistant import auto_apply_batch, launch_application_assistant

    effective_limit = limit if limit is not None else (0 if continuous else 5)

    console.print("\n[bold green]⚡ Launching Autonomous Auto-Apply Engine (Playwright + Brave)[/bold green]")
    console.print(f"  Limit:      {'unlimited' if continuous else effective_limit}")
    console.print(f"  Min Score:  {min_score}")
    console.print(f"  Headless:   {headless}")
    console.print(f"  Auto-Submit:{not dry_run}")
    if url:
        console.print(f"  Target:     {url}")
    console.print()

    if url:
        res = launch_application_assistant(url, headed=not headless, auto_submit=not dry_run, is_batch=False)
        console.print(f"[bold cyan]Result:[/bold cyan] {res}")
    else:
        res = auto_apply_batch(limit=effective_limit, min_score=min_score, headed=not headless, auto_submit=not dry_run)
        console.print(f"[bold green]Batch complete:[/bold green] Attempted {res.get('total_attempted', 0)}, Submitted {res.get('submitted_count', 0)}")


@app.command()
def status() -> None:
    """Show pipeline statistics from the database."""
    _bootstrap()

    from applypilot.database import get_stats

    stats = get_stats()

    console.print("\n[bold]ApplyPilot Pipeline Status[/bold]\n")

    # Summary table
    summary = Table(title="Pipeline Overview", show_header=True, header_style="bold cyan")
    summary.add_column("Metric", style="bold")
    summary.add_column("Count", justify="right")

    summary.add_row("Total jobs discovered", str(stats["total"]))
    summary.add_row("With full description", str(stats["with_description"]))
    summary.add_row("Pending enrichment", str(stats["pending_detail"]))
    summary.add_row("Enrichment errors", str(stats["detail_errors"]))
    summary.add_row("Scored by LLM", str(stats["scored"]))
    summary.add_row("Pending scoring", str(stats["unscored"]))
    summary.add_row("Tailored resumes", str(stats["tailored"]))
    summary.add_row("Pending tailoring (7+)", str(stats["untailored_eligible"]))
    summary.add_row("Cover letters", str(stats["with_cover_letter"]))
    summary.add_row("Ready to apply", str(stats["ready_to_apply"]))
    summary.add_row("Applied", str(stats["applied"]))
    summary.add_row("Apply errors", str(stats["apply_errors"]))

    console.print(summary)

    # Score distribution
    if stats["score_distribution"]:
        dist_table = Table(title="\nScore Distribution", show_header=True, header_style="bold yellow")
        dist_table.add_column("Score", justify="center")
        dist_table.add_column("Count", justify="right")
        dist_table.add_column("Bar")

        max_count = max(count for _, count in stats["score_distribution"]) or 1
        for score, count in stats["score_distribution"]:
            bar_len = int(count / max_count * 30)
            if score >= 7:
                color = "green"
            elif score >= 5:
                color = "yellow"
            else:
                color = "red"
            bar = f"[{color}]{'=' * bar_len}[/{color}]"
            dist_table.add_row(str(score), str(count), bar)

        console.print(dist_table)

    # By site
    if stats["by_site"]:
        site_table = Table(title="\nJobs by Source", show_header=True, header_style="bold magenta")
        site_table.add_column("Site")
        site_table.add_column("Count", justify="right")

        for site, count in stats["by_site"]:
            site_table.add_row(site or "Unknown", str(count))

        console.print(site_table)

    console.print()


@app.command()
def dashboard(
    port: int = typer.Option(8765, "--port", "-p", help="Port for the dashboard server"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not auto-open browser"),
) -> None:
    """Generate and open the HTML dashboard in your browser."""
    _bootstrap()

    from applypilot.dashboard.server import start_dashboard_server

    start_dashboard_server(port=port, open_browser=not no_browser)


@app.command("ui")
def ui_cmd(
    port: int = typer.Option(8765, "--port", "-p", help="Port for the dashboard server"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not auto-open browser"),
) -> None:
    """Shortcut for `applypilot dashboard`."""
    dashboard(port=port, no_browser=no_browser)


@app.command("assistant")
def assistant_cmd(
    target: str = typer.Argument("1", help="Job rank (e.g. '1' for top match), company keyword, rowid, or URL [default: 1]"),
    headed: bool = typer.Option(True, "--headed/--headless", help="Run browser in visible headed mode"),
) -> None:
    """Launch Phase 3 Human-in-the-Loop 1-Click Application Assistant (Review Mode)."""
    _bootstrap()
    from applypilot.apply.assistant import launch_application_assistant
    console.print(f"[bold green]Launching Application Assistant for job {target}...[/bold green]")
    res = launch_application_assistant(target, headed=headed, auto_submit=False)
    console.print(f"[bold cyan]Assistant finished: {res}[/bold cyan]")


@app.command("auto-apply")
def auto_apply_cmd(
    target: str = typer.Argument("1", help="Job rank, keyword, rowid, URL, or 'batch' for multiple"),
    limit: int = typer.Option(5, "--limit", "-l", help="Number of jobs to process if target is 'batch'"),
    min_score: int = typer.Option(7, "--min-score", "-s", help="Minimum fit score threshold"),
    auto_submit: bool = typer.Option(True, "--auto-submit/--review", help="Submit automatically vs pause for review"),
    headed: bool = typer.Option(True, "--headed/--headless", help="Run browser in visible headed mode"),
) -> None:
    """Autonomous Auto-Apply (Kanistus Workflow: Autofill, screening Qs, resume upload, autonomous submission)."""
    _bootstrap()
    from applypilot.apply.assistant import launch_application_assistant, auto_apply_batch
    if str(target).lower() in ("batch", "all", "queue"):
        console.print(f"[bold green]Starting Autonomous Auto-Apply batch (Limit: {limit}, Min Score: {min_score}, Auto-Submit: {auto_submit})...[/bold green]")
        res = auto_apply_batch(limit=limit, min_score=min_score, headed=headed, auto_submit=auto_submit)
        console.print(f"[bold cyan]Batch finished: {res}[/bold cyan]")
    else:
        console.print(f"[bold green]Launching Autonomous Auto-Apply for job '{target}' (Auto-Submit: {auto_submit})...[/bold green]")
        res = launch_application_assistant(target, headed=headed, auto_submit=auto_submit)
        console.print(f"[bold cyan]Application finished: {res}[/bold cyan]")


@app.command("whatsapp")
def whatsapp_cmd(
    timeout: int = typer.Option(45, "--timeout", "-t", help="Timeout in seconds to wait for WhatsApp Web login"),
    headless: bool = typer.Option(False, "--headless", help="Run browser in headless background mode"),
) -> None:
    """Connect to WhatsApp Web via Brave to monitor specified channels for hiring referrals."""
    _bootstrap()
    from applypilot.discovery.whatsapp import scrape_live_whatsapp_web
    console.print("[bold green]Starting WhatsApp Web channel monitor in Brave...[/bold green]")
    count = scrape_live_whatsapp_web(wait_timeout_sec=timeout, headless=headless)
    console.print(f"[bold cyan]WhatsApp sync complete! Ingested {count} new opportunities.[/bold cyan]")


@app.command("telegram")
def telegram_cmd() -> None:
    """Scrape public Telegram tech and SDE community channels for new job leads."""
    _bootstrap()
    from applypilot.discovery.telegram import run_discovery
    console.print("[bold green]Starting Telegram tech channels discovery...[/bold green]")
    count = run_discovery()
    console.print(f"[bold cyan]Telegram sync complete! Ingested {count} new opportunities.[/bold cyan]")


@app.command("kadegree")
def kadegree_cmd() -> None:
    """Sync openings from KaDegree (Kannada Referral Community) directly into ApplyPilot."""
    _bootstrap()
    from applypilot.discovery.kadegree import sync_kadegree_jobs
    console.print("[bold green]Connecting to KaDegree Referral Community via Brave session...[/bold green]")
    res = sync_kadegree_jobs()
    if res.get("status") == "ok":
        console.print(
            f"[bold cyan]KaDegree sync complete! Ingested {res.get('new_stored')} new jobs "
            f"({res.get('relevant_matches')} relevant matches, {res.get('total_fetched')} fetched).[/bold cyan]"
        )
    else:
        console.print(f"[bold red]KaDegree sync failed: {res.get('message')}[/bold red]")


@app.command("poll")
def poll_cmd(
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run browser in headless background mode"),
    loop: bool = typer.Option(False, "--loop", "-l", help="Run continuously in background daemon loop"),
    interval: float = typer.Option(12.0, "--interval", "-i", help="Interval in hours between polling cycles (default: 12h for twice daily)"),
) -> None:
    """Poll WhatsApp Web, Telegram channels, and Gmail for fresh referral leads and recruiter responses."""
    _bootstrap()
    from applypilot.automation.poller import execute_polling_cycle, run_poller_loop

    if loop:
        console.print(f"[bold green]Starting daemon poller loop every {interval} hours (twice a day)...[/bold green]")
        run_poller_loop(interval_hours=interval, headless=headless)
    else:
        console.print("[bold green]Executing community referral & response polling cycle...[/bold green]")
        res = execute_polling_cycle(headless=headless)
        console.print(
            f"[bold cyan]Cycle complete! Ingested {res['whatsapp_jobs_new']} from WhatsApp, "
            f"{res['telegram_jobs_new']} from Telegram, and {res['gmail_responses_new']} from Gmail.[/bold cyan]"
        )


@app.command("inbox")
def inbox_cmd(
    sync: bool = typer.Option(False, "--sync", "-s", help="Fetch latest updates from Gmail first"),
) -> None:
    """View application responses and feedback from companies (Interviews, Tests, Rejections)."""
    _bootstrap()
    from applypilot.enrichment.email_tracker import get_cached_responses, sync_gmail_job_responses

    if sync:
        console.print("[bold cyan]Scanning Gmail inbox for new job application updates...[/bold cyan]")
        try:
            sync_gmail_job_responses()
        except Exception as e:
            console.print(f"[yellow]Gmail live sync skipped: {e}[/yellow]")

    responses = get_cached_responses()
    if not responses:
        console.print("[yellow]No application responses recorded yet. Run with --sync or check back later.[/yellow]")
        return

    table = Table(title="📬 Application Responses & Recruiter Replies (Gmail)", show_lines=True)
    table.add_column("Company", style="bold white", width=22)
    table.add_column("Role", style="cyan", width=24)
    table.add_column("Sentiment", style="bold", width=16)
    table.add_column("Status / Next Step", style="bold magenta", width=34)
    table.add_column("Date", style="dim", width=18)
    table.add_column("Action / Assessment Link", style="green")

    for r in responses:
        sent = r.get("sentiment", "neutral")
        if sent == "positive":
            sent_str = "[bold green]🟢 POSITIVE[/bold green]"
        elif sent == "negative":
            sent_str = "[bold red]🔴 NOT SELECTED[/bold red]"
        else:
            sent_str = "[bold yellow]🟡 ACKNOWLEDGED[/bold yellow]"

        act = r.get("action_url") or "-"

        table.add_row(
            r.get("company", "Employer"),
            r.get("role_title", "Software Engineer"),
            sent_str,
            r.get("status", "Under Review"),
            str(r.get("received_date", ""))[:16],
            act
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Recruiter Email Drafter (Gmail CLI Integration)
# ---------------------------------------------------------------------------

@app.command("draft")
def draft_cmd(
    rowid: int = typer.Argument(..., help="Job rowid to create a Gmail draft for"),
    email: str = typer.Option(None, "--email", "-e", help="Override recruiter email address"),
) -> None:
    """Create a recruiter cold email draft in Gmail with attached tailored resume."""
    _bootstrap()
    from applypilot.networking.gmail_drafter import draft_for_job
    console.print(f"[bold cyan]Creating Gmail draft for job rowid {rowid}...[/bold cyan]")
    res = draft_for_job(rowid, custom_recipient=email)
    if res.get("status") == "ok":
        console.print(f"[bold green]✓ Gmail draft created successfully![/bold green] (ID: {res.get('draft_id')})")
        console.print(f"   Recipient: [bold white]{res.get('to')}[/bold white]")
        console.print(f"   Subject:   [bold white]{res.get('subject')}[/bold white]")
        console.print(f"   Attached:  [bold yellow]{res.get('attachment')}[/bold yellow]")
        console.print(f"   Review at: [link=https://mail.google.com/mail/u/0/#drafts]https://mail.google.com/mail/u/0/#drafts[/link]")
    else:
        console.print(f"[bold red]✗ Failed: {res.get('message')}[/bold red]")


# ---------------------------------------------------------------------------
# LinkedIn Network & Post Automation
# ---------------------------------------------------------------------------

linkedin_app = typer.Typer(name="linkedin", help="LinkedIn automation, hiring posts, and connection finder.")
app.add_typer(linkedin_app, name="linkedin")


@linkedin_app.command("status")
def linkedin_status_cmd() -> None:
    """Check LinkedIn login status."""
    _bootstrap()
    from applypilot.networking.linkedin import is_linkedin_authenticated
    if is_linkedin_authenticated():
        console.print("[bold green]✓ LinkedIn session is ACTIVE and authenticated.[/bold green]")
    else:
        console.print("[bold yellow]! LinkedIn is not logged in yet. Run 'applypilot linkedin login' to authenticate.[/bold yellow]")


@linkedin_app.command("login")
def linkedin_login_cmd(
    timeout: int = typer.Option(75, "--timeout", "-t", help="Timeout in seconds for login")
) -> None:
    """Launch Brave browser to log in to LinkedIn and save session cookies."""
    _bootstrap()
    from applypilot.networking.linkedin import login_to_linkedin
    console.print("[bold cyan]Launching Brave for LinkedIn login...[/bold cyan]")
    res = login_to_linkedin(timeout_sec=timeout, headed=True)
    if res.get("status") == "authenticated":
        console.print(f"[bold green]✓ {res.get('message')}[/bold green]")
    else:
        console.print(f"[bold red]✗ {res.get('message')}[/bold red]")


@linkedin_app.command("posts")
def linkedin_posts_cmd(
    query: str = typer.Argument('backend engineer AND ("hiring" OR "requirement")', help="Search query for LinkedIn posts"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max number of posts to fetch"),
) -> None:
    """Search LinkedIn for hiring posts matching query."""
    _bootstrap()
    from applypilot.networking.linkedin import search_linkedin_posts
    console.print(f"[bold cyan]Searching LinkedIn posts for: '{query}'...[/bold cyan]")
    posts = search_linkedin_posts(keywords=query, max_results=limit, save_to_db=True)
    if not posts or "error" in posts[0]:
        err = posts[0].get("error", "No posts found") if posts else "No posts found"
        console.print(f"[yellow]{err}[/yellow]")
        return

    table = Table(title=f"💼 LinkedIn Hiring Posts: {query}", show_lines=True)
    table.add_column("Author", style="bold white", width=20)
    table.add_column("Headline", style="cyan", width=25)
    table.add_column("Snippet / Text", style="dim", width=45)
    table.add_column("Recruiter Email", style="bold green", width=22)

    for p in posts:
        table.add_row(
            p.get("author", "Member"),
            p.get("headline", "")[:40],
            p.get("post_text", "")[:120] + "...",
            p.get("recruiter_email") or "-"
        )
    console.print(table)


@linkedin_app.command("dm")
def linkedin_dm_cmd(
    profile_url: str = typer.Argument(..., help="LinkedIn profile URL of the connection/recruiter"),
    company: str = typer.Option("", "--company", "-c", help="Company name"),
    role: str = typer.Option("Backend Engineer", "--role", "-r", help="Target role title"),
    name: str = typer.Option("", "--name", "-n", help="Connection first name"),
    template: str = typer.Option("referral", "--template", "-t", help="Template type ('referral' or 'alumni')"),
) -> None:
    """Launch Brave, navigate to connection profile, and auto-type personalized referral DM."""
    _bootstrap()
    from applypilot.networking.linkedin import compose_referral_dm
    console.print(f"[bold cyan]Launching Brave & composing referral DM for:[/bold cyan] {profile_url}")
    res = compose_referral_dm(
        profile_url=profile_url,
        company=company,
        role_title=role,
        name=name,
        template_type=template,
        headed=True
    )
    if res.get("status") == "ok":
        console.print(f"[bold green]✓ {res.get('message')}[/bold green]")
    else:
        console.print(f"[bold red]✗ {res.get('message')}[/bold red]")


# ---------------------------------------------------------------------------
# Recruiter Email Drafter (Gmail CLI Integration)
# ---------------------------------------------------------------------------

@app.command("draft")
def draft_cmd(
    rowid: int = typer.Argument(..., help="Job rowid to create a Gmail draft for"),
    email: str = typer.Option(None, "--email", "-e", help="Override recruiter email address"),
) -> None:
    """Create a recruiter cold email draft in Gmail with attached tailored resume."""
    _bootstrap()
    from applypilot.networking.gmail_drafter import draft_for_job
    console.print(f"[bold cyan]Creating Gmail draft for job rowid {rowid}...[/bold cyan]")
    res = draft_for_job(rowid, custom_recipient=email)
    if res.get("status") == "ok":
        console.print(f"[bold green]✓ Gmail draft created successfully![/bold green] (ID: {res.get('draft_id')})")
        console.print(f"   Recipient: [bold white]{res.get('to')}[/bold white]")
        console.print(f"   Subject:   [bold white]{res.get('subject')}[/bold white]")
        console.print(f"   Attached:  [bold yellow]{res.get('attachment')}[/bold yellow]")
        console.print(f"   Review at: [link=https://mail.google.com/mail/u/0/#drafts]https://mail.google.com/mail/u/0/#drafts[/link]")
    else:
        console.print(f"[bold red]✗ Failed: {res.get('message')}[/bold red]")


@linkedin_app.command("network")
def linkedin_network_cmd(
    company: str = typer.Argument(..., help="Target company name (e.g. PhonePe, Stripe, Meesho)"),
    school: str = typer.Option("RV College of Engineering", "--school", "-s", help="Alumni school name"),
    role: str = typer.Option("backend", "--role", "-r", help="Engineering role keyword"),
    limit: int = typer.Option(8, "--limit", "-n", help="Max results"),
) -> None:
    """Find alumni and engineering connections at a target company."""
    _bootstrap()
    from applypilot.networking.linkedin import search_linkedin_connections
    console.print(f"[bold cyan]Finding {school} alumni & connections at {company}...[/bold cyan]")
    people = search_linkedin_connections(company=company, role=role, school=school, max_results=limit)
    if not people or "error" in people[0]:
        err = people[0].get("error", "No connections found") if people else "No connections found"
        console.print(f"[yellow]{err}[/yellow]")
        return

    table = Table(title=f"🎓 {school} Alumni & Connections @ {company}", show_lines=True)
    table.add_column("Name", style="bold white", width=22)
    table.add_column("Headline / Role", style="cyan", width=35)
    table.add_column("Location", style="dim", width=18)
    table.add_column("Profile Link", style="green")

    for person in people:
        table.add_row(
            person.get("name", "Member"),
            person.get("headline", "")[:45],
            person.get("location", "India"),
            person.get("profile_url", "-")
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Recruiter Email Drafter (Gmail CLI Integration)
# ---------------------------------------------------------------------------

@app.command("draft")
def draft_cmd(
    rowid: int = typer.Argument(..., help="Job rowid to create a Gmail draft for"),
    email: str = typer.Option(None, "--email", "-e", help="Override recruiter email address"),
) -> None:
    """Create a recruiter cold email draft in Gmail with attached tailored resume."""
    _bootstrap()
    from applypilot.networking.gmail_drafter import draft_for_job
    console.print(f"[bold cyan]Creating Gmail draft for job rowid {rowid}...[/bold cyan]")
    res = draft_for_job(rowid, custom_recipient=email)
    if res.get("status") == "ok":
        console.print(f"[bold green]✓ Gmail draft created successfully![/bold green] (ID: {res.get('draft_id')})")
        console.print(f"   Recipient: [bold white]{res.get('to')}[/bold white]")
        console.print(f"   Subject:   [bold white]{res.get('subject')}[/bold white]")
        console.print(f"   Attached:  [bold yellow]{res.get('attachment')}[/bold yellow]")
        console.print(f"   Review at: [link=https://mail.google.com/mail/u/0/#drafts]https://mail.google.com/mail/u/0/#drafts[/link]")
    else:
        console.print(f"[bold red]✗ Failed: {res.get('message')}[/bold red]")


@app.command()
def doctor() -> None:
    """Check your setup and diagnose missing requirements."""
    import shutil
    from applypilot.config import (
        load_env, PROFILE_PATH, RESUME_PATH, RESUME_PDF_PATH,
        SEARCH_CONFIG_PATH, ENV_PATH, get_chrome_path,
    )

    load_env()

    ok_mark = "[green]OK[/green]"
    fail_mark = "[red]MISSING[/red]"
    warn_mark = "[yellow]WARN[/yellow]"

    results: list[tuple[str, str, str]] = []  # (check, status, note)

    # --- Tier 1 checks ---
    # Profile
    if PROFILE_PATH.exists():
        results.append(("profile.json", ok_mark, str(PROFILE_PATH)))
    else:
        results.append(("profile.json", fail_mark, "Run 'applypilot init' to create"))

    # Resume
    if RESUME_PATH.exists():
        results.append(("resume.txt", ok_mark, str(RESUME_PATH)))
    elif RESUME_PDF_PATH.exists():
        results.append(("resume.txt", warn_mark, "Only PDF found — plain-text needed for AI stages"))
    else:
        results.append(("resume.txt", fail_mark, "Run 'applypilot init' to add your resume"))

    # Search config
    if SEARCH_CONFIG_PATH.exists():
        results.append(("searches.yaml", ok_mark, str(SEARCH_CONFIG_PATH)))
    else:
        results.append(("searches.yaml", warn_mark, "Will use example config — run 'applypilot init'"))

    # jobspy (discovery dep installed separately)
    try:
        import jobspy  # noqa: F401
        results.append(("python-jobspy", ok_mark, "Job board scraping available"))
    except ImportError:
        results.append(("python-jobspy", warn_mark,
                        "pip install --no-deps python-jobspy && pip install pydantic tls-client requests markdownify regex"))

    # --- Tier 2 checks ---
    import os
    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_local = bool(os.environ.get("LLM_URL"))
    if has_gemini:
        model = os.environ.get("LLM_MODEL", "gemini-2.0-flash")
        results.append(("LLM API key", ok_mark, f"Gemini ({model})"))
    elif has_openai:
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        results.append(("LLM API key", ok_mark, f"OpenAI ({model})"))
    elif has_local:
        results.append(("LLM API key", ok_mark, f"Local: {os.environ.get('LLM_URL')}"))
    else:
        results.append(("LLM API key", fail_mark,
                        "Set GEMINI_API_KEY in ~/.applypilot/.env (run 'applypilot init')"))

    # --- Tier 3 checks ---
    # Claude Code CLI
    claude_bin = shutil.which("claude")
    if claude_bin:
        results.append(("Claude Code CLI", ok_mark, claude_bin))
    else:
        results.append(("Claude Code CLI", fail_mark,
                        "Install from https://claude.ai/code (needed for auto-apply)"))

    # Chrome
    try:
        chrome_path = get_chrome_path()
        results.append(("Chrome/Chromium", ok_mark, chrome_path))
    except FileNotFoundError:
        results.append(("Chrome/Chromium", fail_mark,
                        "Install Chrome or set CHROME_PATH env var (needed for auto-apply)"))

    # Node.js / npx (for Playwright MCP)
    npx_bin = shutil.which("npx")
    if npx_bin:
        results.append(("Node.js (npx)", ok_mark, npx_bin))
    else:
        results.append(("Node.js (npx)", fail_mark,
                        "Install Node.js 18+ from nodejs.org (needed for auto-apply)"))

    # CapSolver (optional)
    capsolver = os.environ.get("CAPSOLVER_API_KEY")
    if capsolver:
        results.append(("CapSolver API key", ok_mark, "CAPTCHA solving enabled"))
    else:
        results.append(("CapSolver API key", "[dim]optional[/dim]",
                        "Set CAPSOLVER_API_KEY in .env for CAPTCHA solving"))

    # --- Render results ---
    console.print()
    console.print("[bold]ApplyPilot Doctor[/bold]\n")

    col_w = max(len(r[0]) for r in results) + 2
    for check, status, note in results:
        pad = " " * (col_w - len(check))
        console.print(f"  {check}{pad}{status}  [dim]{note}[/dim]")

    console.print()

    # Tier summary
    from applypilot.config import get_tier, TIER_LABELS
    tier = get_tier()
    console.print(f"[bold]Current tier: Tier {tier} — {TIER_LABELS[tier]}[/bold]")

    if tier == 1:
        console.print("[dim]  → Tier 2 unlocks: scoring, tailoring, cover letters (needs LLM API key)[/dim]")
        console.print("[dim]  → Tier 3 unlocks: auto-apply (needs Claude Code CLI + Chrome + Node.js)[/dim]")
    elif tier == 2:
        console.print("[dim]  → Tier 3 unlocks: auto-apply (needs Claude Code CLI + Chrome + Node.js)[/dim]")

    console.print()



@app.command()
def export(
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Custom CSV output path.")
) -> None:
    """Export scored opportunities to a CSV spreadsheet."""
    _bootstrap()
    from applypilot.export.csv_export import export_opportunities_csv
    out_path = export_opportunities_csv(output)
    console.print(f"[green]Successfully exported opportunities to:[/green] {out_path}")


@app.command("naukri-update")
def naukri_update(
    resume: Optional[str] = typer.Option(None, "--resume", "-r", help="Path to resume PDF file to upload."),
    headed: bool = typer.Option(False, "--headed", help="Run browser in visible headed mode."),
    login: bool = typer.Option(False, "--login", help="Open Brave to log in to Naukri and save session."),
) -> None:
    """Re-upload resume on Naukri to update profile freshness and boost recruiter ranking."""
    _bootstrap()
    from applypilot.automation.naukri_updater import login_interactive, update_naukri_resume

    if login:
        console.print("[cyan]Opening Brave browser for Naukri authentication...[/cyan]")
        res = login_interactive()
        if res.get("status") == "success":
            console.print(f"[green]✓ {res.get('message')}[/green]")
        else:
            console.print(f"[yellow]! {res.get('message')}[/yellow]")
        return

    console.print("[cyan]Initiating Naukri profile resume update...[/cyan]")
    res = update_naukri_resume(resume_path=resume, headed=headed)
    if res.get("status") == "success":
        console.print(f"[bold green]✓ SUCCESS:[/bold green] {res.get('message')}")
    elif res.get("status") == "auth_required":
        console.print(f"[yellow]! AUTH REQUIRED:[/yellow] {res.get('message')}")
        console.print("[dim]Run `applypilot naukri-update --login` to sign in once.[/dim]")
    else:
        console.print(f"[bold red]✗ ERROR:[/bold red] {res.get('message')}")


@app.command("naukri-schedule")
def naukri_schedule(
    time_str: str = typer.Option("09:00", "--time", "-t", help="Daily execution time (HH:mm, default 09:00 AM)."),
    status: bool = typer.Option(False, "--status", "-s", help="Check Windows Task Scheduler status."),
    uninstall: bool = typer.Option(False, "--uninstall", "-u", help="Remove scheduled task from Windows."),
) -> None:
    """Manage daily 9:00 AM Naukri resume refresher in Windows Task Scheduler."""
    _bootstrap()
    from applypilot.automation.naukri_updater import (
        get_last_update_status,
        get_windows_task_status,
        register_windows_task,
        unregister_windows_task,
    )

    if uninstall:
        res = unregister_windows_task()
        console.print(f"[yellow]{res.get('message')}[/yellow]")
        return

    if status:
        task_info = get_windows_task_status()
        last_log = get_last_update_status()
        console.print("\n[bold]ApplyPilot Naukri Scheduled Task Status[/bold]")
        console.print(f"  Registered: {task_info.get('registered')}")
        if task_info.get("registered"):
            console.print(f"  Task Name:  {task_info.get('task_name')}")
            console.print(f"  State:      {task_info.get('state')}")
            console.print(f"  Next Run:   {task_info.get('next_run')}")
            console.print(f"  Last Run:   {task_info.get('last_run')}")
        console.print("\n[bold]Last Update Attempt:[/bold]")
        console.print(f"  Status:     {last_log.get('status')}")
        console.print(f"  Timestamp:  {last_log.get('last_updated_at')}")
        console.print(f"  Message:    {last_log.get('message')}\n")
        return

    res = register_windows_task(task_time=time_str)
    if res.get("status") == "success":
        console.print(f"[bold green]✓ SUCCESS:[/bold green] {res.get('message')}")
        console.print("[dim]Configured with 'Start When Available' — will trigger upon wake-up if missed.[/dim]")
    else:
        console.print(f"[bold red]✗ FAILED:[/bold red] {res.get('message')}")



@app.command("analyze")
def analyze_cmd(
    refresh: bool = typer.Option(False, "--refresh", "-r", help="Force fresh live Gemini strategic re-analysis."),
) -> None:
    """Run Gemini Strategic Diagnostic Job on 30-day funnel & time spent."""
    _bootstrap()
    from applypilot.analytics.activity import get_funnel_and_activity_metrics
    from applypilot.analytics.gemini_advisor import run_gemini_strategic_analysis

    console.print("[bold cyan]⚡ ApplyPilot Career Intelligence & Conversion Diagnostics[/bold cyan]")
    
    metrics = get_funnel_and_activity_metrics()
    act = metrics["activity"]
    f = metrics["funnel"]

    # Funnel Table
    table = Table(title="30-Day Conversion & Time-Saver Metrics", border_style="cyan")
    table.add_column("Metric", style="bold white")
    table.add_column("Value", style="bold green")
    table.add_column("Benchmark / Context", style="dim")

    table.add_row("Today's Active Search Time", f"{act['today_active_minutes']} mins", "Daily logged browsing/applying")
    table.add_row("Weekly Search Time", f"{act['weekly_active_hours']} hrs", "Last 7 days active usage")
    table.add_row("Time per Application", f"{act['avg_mins_per_app']} mins", f"vs {act['manual_mins_per_app']} mins manual (7.3x faster)")
    table.add_row("Heavy Time Saved (30d)", f"{act['hours_saved_30d']} hours", "JIT LaTeX tailoring + Brave autofill")
    table.add_row("Fully Applied (ATS submitted)", str(f["fully_applied"]), "Verified submissions")
    table.add_row("Half Applied (In progress / autofill)", str(f["half_applied"]), "Forms started, awaiting manual review")
    table.add_row("Approved in Queue", str(f["approved_pending"]), "Ready to apply")
    table.add_row("Return Responses Received", str(f["responses_received"]), f"{f['response_rate_pct']}% response rate")
    table.add_row("Active Online Assessments (OAs)", str(f["active_oas"]), "Coding tests with deadlines")
    table.add_row("Interview Calls / Technical Rounds", str(f["interview_calls"]), f"{f['interview_call_rate_pct']}% interview conversion rate")

    console.print(table)
    console.print("[cyan]Consulting Gemini AI Career Strategist...[/cyan]")
    rep = run_gemini_strategic_analysis(force_refresh=refresh)

    console.print(f"[bold green]Health Score: {rep.get('health_score')}/100[/bold green] — [bold white]{rep.get('verdict_title')}[/bold white]")
    console.print(f"[dim]{rep.get('executive_summary')}[/dim]")

    # Resume Gaps
    console.print("[bold yellow]1. Resume Efficiency Audit:[/bold yellow]")
    for g in rep.get("resume_efficiency", {}).get("missing_keywords_or_gaps", []):
        console.print(f"  [red]✗[/red] Gap: {g}")
    console.print("  [green]High-Impact Bullet Upgrades:[/green]")
    for b in rep.get("resume_efficiency", {}).get("high_impact_bullet_recommendations", []):
        console.print(f"    • [dim italic]{b}[/dim italic]")

    # Role Fit
    console.print("[bold yellow]2. Role & Seniority Fit Evaluation:[/bold yellow]")
    for s in rep.get("role_targeting_fit", {}).get("sweet_spot_roles", []):
        console.print(f"  [green]✓ Sweet Spot:[/green] {s}")
    for w in rep.get("role_targeting_fit", {}).get("out_of_reach_or_wasteful_roles", []):
        console.print(f"  [red]✗ Skip / Out of Reach:[/red] {w}")

    # Velocity Playbook
    console.print("[bold yellow]3. Velocity Playbook (Fast-Track Interview Selections):[/bold yellow]")
    for p in rep.get("fast_track_interview_playbook", []):
        console.print(f"  [cyan]• {p.get('action')}[/cyan] ({p.get('priority')}): {p.get('why_it_works')} -> [green]+{p.get('expected_time_saved_or_gain')}[/green]")
    console.print("")


@app.command("calendar-block")
def calendar_block_cmd() -> None:
    """Scan uncompleted OAs and block dedicated focus slots on Google Calendar."""
    _bootstrap()
    from applypilot.calendar.scheduler import block_all_pending_oas
    console.print("[cyan]Scanning uncompleted Online Assessments (OAs)...[/cyan]")
    res = block_all_pending_oas()
    console.print(f"[green]✓ Successfully processed {res.get('blocked_count')} online assessments![/green]")
    for a in res.get("assessments", []):
        console.print(f"  • [bold white]{a.get('company')}[/bold white] (Due: {a.get('due_date')}) -> [cyan]{a.get('event_link')}[/cyan]")


@app.command("gsheet-sync")
def gsheet_sync_cmd() -> None:
    """Synchronize pipeline, interview calls, and funnel metrics to Central Google Sheet."""
    _bootstrap()
    from applypilot.export.gsheets_sync import sync_to_google_sheets
    console.print("[cyan]Synchronizing pipeline to Central Google Sheet / Mobile CSV...[/cyan]")
    res = sync_to_google_sheets()
    console.print(f"[bold green]✓ Sync completed successfully![/bold green]")
    console.print(f"  • Synced Jobs: {res.get('synced_jobs')}")
    console.print(f"  • Synced Responses: {res.get('synced_responses')}")
    console.print(f"  • Synced Calls: {res.get('synced_calls')}")
    console.print(f"  • Mobile View URL: [cyan]{res.get('spreadsheet_url')}[/cyan]")


@app.command("call-log")
def call_log_cmd(
    company: str = typer.Option(..., "--company", "-c", help="Company name (e.g. PhonePe, Razorpay)"),
    role: str = typer.Option("SDE Backend Engineer", "--role", "-r", help="Role title"),
    call_type: str = typer.Option("technical_interview", "--type", "-t", help="Type: phone_screen, technical_interview, oa, offer, rejection"),
    recruiter: str = typer.Option("", "--recruiter", help="Recruiter name"),
    contact: str = typer.Option("", "--contact", help="Phone or email of recruiter"),
    scheduled: str = typer.Option("", "--scheduled", help="Scheduled date/time e.g. 'Tomorrow 3 PM'"),
    notes: str = typer.Option("", "--notes", help="Discussion notes (CTC, questions, notice period)"),
    url: str = typer.Option("", "--url", help="Meeting link or test link"),
) -> None:
    """Log an incoming recruiter call or interview screening with optional calendar sync and phone alert."""
    _bootstrap()
    from applypilot.enrichment.call_logger import log_recruiter_call
    console.print(f"[cyan]Logging recruiter outreach for {company}...[/cyan]")
    res = log_recruiter_call({
        "company": company,
        "role_title": role,
        "call_type": call_type,
        "recruiter_name": recruiter,
        "recruiter_contact": contact,
        "scheduled_at": scheduled,
        "notes": notes,
        "action_url": url,
        "auto_calendar": bool(scheduled)
    })
    console.print(f"[bold green]✓ Call logged successfully (ID: {res.get('call_id')})![/bold green]")
    console.print(f"  • Company:  {res.get('company')}")
    console.print(f"  • Category: {res.get('category')}")
    if res.get("calendar"):
        console.print(f"  • Calendar: [cyan]{res['calendar'].get('event_link')}[/cyan]")


@app.command("cheatsheet")
def cheatsheet_cmd(
    company: str = typer.Argument(..., help="Company name (e.g. Razorpay, PhonePe, Target, Stripe, Zepto)"),
    role: str = typer.Option("SDE Backend Engineer", "--role", "-r", help="Target role title"),
) -> None:
    """Generate high-yield technical and HR interview cheat sheet tailored to Deepak's Meesho experience."""
    _bootstrap()
    from applypilot.enrichment.interview_cheatsheet import generate_company_cheatsheet
    console.print(f"[cyan]Synthesizing technical interview cheat-sheet for {company}...[/cyan]")
    sheet = generate_company_cheatsheet(company, role)

    console.print(f"\n[bold green]=== Interview Strategy Cheat-Sheet: {sheet.get('company')} ===[/bold green]")
    console.print(f"[dim]Source: {sheet.get('source')} | Role: {sheet.get('role_title')}[/dim]")
    console.print(f"[bold white]Domain:[/bold white] {sheet.get('domain')}")
    console.print(f"[bold white]Known Tech Stack:[/bold white] {sheet.get('primary_stack')}\n")

    console.print("[bold yellow]1. Engineering & Scale Challenges:[/bold yellow]")
    for ec in sheet.get("engineering_challenges", []):
        console.print(f"  • {ec}")

    console.print("\n[bold yellow]2. Must-Know System Design & Concurrency Topics:[/bold yellow]")
    for topic in sheet.get("must_know_topics", []):
        console.print(f"  • [bold cyan]{topic}[/bold cyan]")

    console.print("\n[bold yellow]3. Deepak's Meesho Silver-Bullet Answer:[/bold yellow]")
    console.print(f"  [dim italic]{sheet.get('meesho_story_alignment')}[/dim italic]")

    console.print("\n[bold yellow]4. HR & Negotiation Tactics:[/bold yellow]")
    hr = sheet.get("hr_tactics", {})
    console.print(f"  • [bold white]Why {company}?[/bold white] {hr.get('why_leaving')}")
    console.print(f"  • [bold white]Target CTC:[/bold white] {hr.get('target_ctc')}")
    console.print(f"  • [bold white]Notice Period:[/bold white] {hr.get('notice_period')}")

    console.print("\n[bold yellow]5. Sharp Reverse-Interview Questions to Ask:[/bold yellow]")
    for q in sheet.get("questions_to_ask", []):
        console.print(f"  • \"{q}\"")
    console.print("")


@app.command("alert-test")
def alert_test_cmd() -> None:
    """Test all instant alert channels (Telegram, WhatsApp CallMeBot, Windows Desktop Toast)."""
    _bootstrap()
    from applypilot.notifications.alerts import dispatch_alert, get_alert_config
    cfg = get_alert_config()
    console.print("[cyan]Testing ApplyPilot Instant Notification Channels...[/cyan]")
    console.print(f"  • Telegram Configured: {'[green]Yes[/green]' if cfg['telegram_token'] and cfg['telegram_chat_id'] else '[yellow]No (Add TELEGRAM_BOT_TOKEN & CHAT_ID in .env)[/yellow]'}")
    console.print(f"  • WhatsApp Configured: {'[green]Yes[/green]' if cfg['whatsapp_phone'] and cfg['whatsapp_apikey'] else '[yellow]No (Add CALLMEBOT_PHONE & APIKEY in .env)[/yellow]'}")
    console.print(f"  • Windows Toast:       [green]Active[/green]")

    res = dispatch_alert(
        title="ApplyPilot Mobile Alert Test",
        body="Instant notification channel operational. You will receive real-time pings for OAs and interviews.",
        url="http://localhost:8765"
    )
    console.print(f"[bold green]✓ Broadcast Test Complete![/bold green]")
    console.print(f"  • Telegram: {res['telegram']['status']}")
    console.print(f"  • WhatsApp: {res['whatsapp']['status']}")
    console.print(f"  • Windows Desktop Toast: {'Delivered' if res['windows_toast'] else 'Failed'}\n")


@app.command("tailor-link")
def tailor_link_cmd(
    url: str = typer.Argument(..., help="Job posting link/URL to read and tailor for"),
    jd: Optional[str] = typer.Option("", "--jd", help="Optional manual JD text if page is behind login"),
) -> None:
    """Read a job posting URL, tailor resume & cover letter, and generate referral outreach messages."""
    _bootstrap()
    from applypilot.apply.quick_tailor import process_job_link

    console.print(f"[bold cyan]🔍 Fetching and analyzing job posting from URL:[/bold cyan] {url}")
    res = process_job_link(url, manual_jd=jd)

    if res.get("status") != "ok":
        console.print(f"[bold red]✗ Failed to process link:[/bold red] {res.get('message')}")
        raise typer.Exit(1)

    comp = res.get("company", "Company")
    title = res.get("title", "Software Engineer")
    loc = res.get("location", "N/A")
    outreach = res.get("outreach", {})

    console.print(f"\n[bold green]✓ Successfully Extracted & Tailored for {comp}![/bold green]")
    console.print(f"  • [bold white]Role:[/bold white] {title}")
    console.print(f"  • [bold white]Location:[/bold white] {loc}")
    if res.get("pdf_resume_path"):
        console.print(f"  • [bold white]Tailored Resume PDF:[/bold white] [cyan]{res['pdf_resume_path']}[/cyan]")
    if res.get("pdf_cover_path"):
        console.print(f"  • [bold white]Cover Letter PDF:[/bold white] [cyan]{res['pdf_cover_path']}[/cyan]")

    console.print("\n[bold yellow]Targeted LinkedIn Network Searches:[/bold yellow]")
    console.print(f"  • 1st-Degree Friends: {outreach.get('first_degree_url')}")
    console.print(f"  • 2nd-Degree Mutuals: {outreach.get('second_degree_url')}")
    console.print(f"  • RVCE Alumni:        {outreach.get('alumni_search_url')}")
    console.print(f"  • Recruiters:         {outreach.get('recruiter_search_url')}")

    console.print("\n[bold yellow]Customized Referral Message (1st-Degree / Colleague):[/bold yellow]")
    console.print(f"[dim]{outreach.get('first_degree_message')}[/dim]")

    console.print("\n[bold yellow]Customized Referral Message (RVCE Alumni):[/bold yellow]")
    console.print(f"[dim]{outreach.get('alumni_message')}[/dim]")
    console.print("")


if __name__ == "__main__":


    app()
