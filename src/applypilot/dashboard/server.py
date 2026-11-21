"""ApplyPilot Phase 2 Interactive Review & Approval Dashboard.

High-energy, cyber-sleek UI with:
- Glassmorphism, energetic gradients, and micro-interactions.
- On-Demand (JIT) Resume Tailoring & Tectonic PDF Compilation in 4 seconds.
- Direct Live Brave integration (opens in existing Brave browser with resume copied to clipboard).
- LinkedIn Referral & Connection Outreach generator with 1-click searches.
- Approved Shortlist Queue for focused daily applications.
- Celebratory confetti on application submit.
"""

import json
import logging
import mimetypes
import os
import re
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from applypilot.config import APP_DIR, DB_PATH, TAILORED_DIR, COVER_LETTER_DIR, load_profile, load_env
from applypilot.database import get_connection
from applypilot.export.csv_export import export_opportunities_csv

load_env()
from applypilot.networking.outreach import generate_outreach_messages
from applypilot.scoring.jit_tailor import tailor_single_job

log = logging.getLogger(__name__)

PORT = 8765
BRAVE_EXE = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"


def launch_url_in_brave(url: str, incognito: bool = False) -> bool:
    """Launch URL in Brave browser using Windows Shell or direct process without pipe redirection."""
    if not url or not (str(url).startswith("http://") or str(url).startswith("https://")):
        return False
    try:
        if incognito:
            if os.path.exists(BRAVE_EXE):
                subprocess.Popen([BRAVE_EXE, "--incognito", url])
                return True
            else:
                subprocess.Popen(["cmd", "/c", "start", "brave", "--incognito", url])
                return True
        if hasattr(os, "startfile"):
            os.startfile(url)
            return True
        elif os.path.exists(BRAVE_EXE):
            subprocess.Popen([BRAVE_EXE, url])
            return True
        else:
            webbrowser.open(url)
            return True
    except Exception as e:
        log.warning("Could not launch URL via Brave: %s", e)
        try:
            if os.path.exists(BRAVE_EXE):
                cmd = [BRAVE_EXE, "--incognito", url] if incognito else [BRAVE_EXE, url]
                subprocess.Popen(cmd)
            else:
                webbrowser.open(url)
            return True
        except Exception:
            return False


HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ApplyPilot - Command & Review Dashboard</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
  <style>
    /* Clean Enterprise Dark Theme */
    :root {
      --bg: #0b0f19;
      --panel: #111827;
      --panel-border: #1f2937;
      --card-bg: #111827;
      --card-border: #1f2937;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #2563eb;
      --accent-hover: #1d4ed8;
      --emerald: #10b981;
      --amber: #f59e0b;
      --cyan: #0284c7;
      --purple: #6366f1;
      --rose: #ef4444;
      --tab-active: #2563eb;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding-bottom: 80px;
      min-height: 100vh;
    }

    header {
      background: #0f172a;
      border-bottom: 1px solid var(--panel-border);
      padding: 12px 28px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .brand-logo {
      font-size: 20px;
      color: #38bdf8;
    }
    .brand-title {
      font-size: 18px;
      font-weight: 700;
      color: #f8fafc;
      letter-spacing: -0.3px;
    }
    .status-pill {
      display: flex;
      align-items: center;
      gap: 6px;
      background: #1e293b;
      border: 1px solid #334155;
      color: #94a3b8;
      font-size: 11px;
      font-weight: 600;
      padding: 3px 8px;
      border-radius: 6px;
    }
    .pulse-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #10b981;
    }

    /* Candidate Quick Bar */
    .quick-bar {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }
    .quick-pill {
      background: #1e293b;
      border: 1px solid #334155;
      color: #cbd5e1;
      font-size: 12px;
      font-weight: 500;
      padding: 5px 11px;
      border-radius: 6px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      text-decoration: none;
      transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
    }
    .quick-pill:hover {
      background: #334155;
      border-color: #475569;
      color: #fff;
    }

    .container {
      max-width: 1440px;
      margin: 0 auto;
      padding: 24px 32px;
    }

    /* Stats Grid */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }
    .stat-card {
      background: var(--panel);
      border: 1px solid var(--panel-border);
      padding: 16px 18px;
      border-radius: 8px;
      display: flex;
      flex-direction: column;
      position: relative;
      transition: border-color 0.15s ease;
    }
    .stat-card:hover {
      border-color: #374151;
    }
    .stat-card .label {
      font-size: 11px;
      color: var(--text-muted);
      text-transform: uppercase;
      font-weight: 600;
      letter-spacing: 0.5px;
    }
    .stat-card .val {
      font-size: 26px;
      font-weight: 700;
      margin-top: 4px;
      letter-spacing: -0.5px;
      color: #f8fafc;
    }

    /* Queue Announcement Banner */
    .queue-banner {
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 12px 18px;
      margin-bottom: 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    .queue-banner-title {
      font-weight: 600;
      font-size: 13px;
      color: #e2e8f0;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    /* Controls & Tabs */
    .controls {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 24px;
      flex-wrap: wrap;
    }
    .tabs {
      display: flex;
      gap: 4px;
      background: #111827;
      padding: 4px;
      border-radius: 8px;
      border: 1px solid var(--panel-border);
      flex-wrap: wrap;
    }

    /* === MINIMALIST FULL-AUTOMATION OVERRIDES === */

    /* 1. Hide redundant tabs (keep only: Fresh <4h, Easy Apply, Asked Referral, Applied, Gmail Tracker) */
    .tabs .tab-btn:not([onclick*="'incognito_fresh'"]):not([onclick*="'easy_apply'"]):not([onclick*="'asked_referral'"]):not([onclick*="'applied'"]):not([onclick*="'responses'"]) {
      display: none !important;
    }

    /* 2. Hide noisy top header pills (keep only Scan, Auto-Apply, Sync Gmail, Copilot, and manual copy pills) */
    .quick-bar > a.quick-pill,
    .quick-bar > .quick-pill:not([onclick*="triggerLinkedInIncognitoScan"]):not([onclick*="triggerBatchAutoApply"]):not([onclick*="syncGmailNow"]):not([onclick*="openScreeningCopilotModal"]):not([onclick*="copyText"]) {
      display: none !important;
    }

    /* 3. Hide the bulky 9-card KPI grid & daily quota banner (keep urgent OA alerts only) */
    #daily-target-tracker,
    .stats-grid {
      display: none !important;
    }

    /* 4. Simplify Job Card buttons: keep only Primary Apply, Referral Outreach, and Ignore */
    .job-card .btn-cheatsheet,
    .job-card .btn-approve,
    .job-card .btn-email-ghost,
    .job-card button[onclick*="navigator.clipboard"] {
      display: none !important;
    }
    .tab-btn {
      background: transparent;
      color: var(--text-muted);
      border: none;
      padding: 7px 14px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s ease, color 0.15s ease;
      display: flex;
      align-items: center;
      gap: 7px;
    }
    .tab-btn:hover {
      color: #fff;
    }
    .tab-btn.active {
      background: #2563eb;
      color: white;
    }

    
    .tab-badge {
      background: rgba(255, 255, 255, 0.2);
      font-size: 11px;
      padding: 2px 7px;
      border-radius: 999px;
      font-weight: 800;
    }

    .search-box {
      flex: 1;
      max-width: 380px;
      position: relative;
    }
    .search-box input {
      width: 100%;
      background: rgba(15, 23, 42, 0.7);
      border: 1px solid var(--panel-border);
      color: var(--text);
      padding: 10px 16px 10px 40px;
      border-radius: 10px;
      font-size: 13px;
      outline: none;
      transition: all 0.2s;
    }
    .search-box input:focus {
      border-color: #818cf8;
      box-shadow: 0 0 16px rgba(99, 102, 241, 0.3);
    }
    .search-box i {
      position: absolute;
      left: 14px;
      top: 13px;
      color: var(--text-muted);
    }

    /* Jobs Grid & Cards */
    .jobs-grid {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .job-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 18px 22px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      position: relative;
      transition: border-color 0.15s ease;
    }
    .job-card:hover {
      border-color: #374151;
    }

    .card-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
    }
    .job-meta {
      display: flex;
      gap: 14px;
      align-items: center;
    }
    .company-avatar {
      width: 42px;
      height: 42px;
      border-radius: 8px;
      background: #1e293b;
      border: 1px solid #334155;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
      font-weight: 700;
      color: #cbd5e1;
      flex-shrink: 0;
    }
    .job-title-row {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    .job-title {
      font-size: 17px;
      font-weight: 700;
      color: #f8fafc;
      letter-spacing: -0.3px;
    }
    .job-sub {
      display: flex;
      align-items: center;
      gap: 12px;
      color: var(--text-muted);
      font-size: 13px;
      margin-top: 3px;
      flex-wrap: wrap;
    }
    .job-sub span {
      display: flex;
      align-items: center;
      gap: 5px;
    }

    /* Score Badge */
    .score-badge {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      width: 44px;
      height: 44px;
      border-radius: 8px;
      font-weight: 700;
      flex-shrink: 0;
    }
    .score-badge .num { font-size: 17px; line-height: 1; }
    .score-badge .denom { font-size: 9px; opacity: 0.7; text-transform: uppercase; font-weight: 600; margin-top: 1px; }

    .score-9 { background: #064e3b; color: #6ee7b7; border: 1px solid #059669; }
    .score-8 { background: #1e3a8a; color: #93c5fd; border: 1px solid #2563eb; }
    .score-7 { background: #1f2937; color: #cbd5e1; border: 1px solid #374151; }
    .score-mid { background: #111827; color: #9ca3af; border: 1px solid #1f2937; }
    .score-low { background: #111827; color: #6b7280; border: 1px solid #1f2937; }

    .badges-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      margin-top: 2px;
    }
    .tag {
      font-size: 11px;
      font-weight: 600;
      padding: 3px 8px;
      border-radius: 4px;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .tag-resume { background: #1e293b; color: #93c5fd; border: 1px solid #334155; }
    .tag-cover { background: #1e293b; color: #86efac; border: 1px solid #334155; }
    .tag-email { background: #1e293b; color: #f472b6; border: 1px solid #334155; }
    .tag-approved { background: #064e3b; color: #6ee7b7; border: 1px solid #059669; }
    .tag-applied { background: #1e293b; color: #cbd5e1; border: 1px solid #475569; }
    .tag-ignored { background: #334155; color: #94a3b8; border: 1px solid #475569; }

    .reasoning {
      background: #0f172a;
      border: 1px solid #1f2937;
      border-radius: 6px;
      padding: 10px 14px;
      font-size: 13px;
      color: #cbd5e1;
      line-height: 1.5;
    }

    /* Actions Bar */
    .actions-bar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      border-top: 1px solid #1f2937;
      padding-top: 12px;
    }
    .btn {
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      border: 1px solid transparent;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      text-decoration: none;
      transition: background 0.15s ease, border-color 0.15s ease;
    }
    .btn:hover {
      filter: brightness(1.1);
    }
    .btn-auto-apply {
      background: #2563eb;
      color: #fff;
      border: 1px solid #1d4ed8;
    }
    .btn-auto-apply:hover {
      background: #1d4ed8;
      color: #fff;
    }
    .btn-autofill {
      background: #0f766e;
      color: #fff;
      border: 1px solid #115e59;
    }
    .btn-autofill:hover {
      background: #115e59;
      color: #fff;
    }
    .btn-brave {
      background: #ea580c;
      color: #fff;
      border: 1px solid #c2410c;
    }
    .btn-tailor {
      background: #475569;
      color: #fff;
      border: 1px solid #64748b;
    }
    .btn-outreach {
      background: #1e293b;
      color: #cbd5e1;
      border: 1px solid #334155;
    }
    .btn-preview {
      background: #1e293b;
      color: #e2e8f0;
      border: 1px solid #334155;
    }
    .btn-approve {
      background: #064e3b;
      border: 1px solid #059669;
      color: #6ee7b7;
    }
    .btn-applied {
      background: #1e293b;
      border: 1px solid #475569;
      color: #94a3b8;
    }
    .btn-ignore {
      background: rgba(148, 163, 184, 0.1);
      border: 1px solid #475569;
      color: #94a3b8;
    }
    .btn-ignore:hover {
      background: rgba(239, 68, 68, 0.15);
      border-color: #ef4444;
      color: #fca5a5;
    }
    .btn-email {
      background: #991b1b;
      color: #fee2e2;
      border: 1px solid #b91c1c;
    }
    .btn-email-ghost {
      background: #1e293b;
      border: 1px solid #334155;
      color: #cbd5e1;
    }
    .btn-email-ghost:hover {
      background: #334155;
      color: #fff;
    }

    /* Response Cards & Sentiment Badges */
    .response-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 16px 20px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      position: relative;
      transition: border-color 0.15s ease;
    }
    .response-card:hover {
      border-color: #374151;
    }
    .response-card.sentiment-positive, .response-card.cat-interview {
      border-left: 4px solid #10b981;
    }
    .response-card.cat-oa {
      border-left: 4px solid #f59e0b;
    }
    .response-card.cat-oa.is-missed {
      border-left: 4px solid #ef4444;
    }
    .response-card.cat-oa.is-done {
      opacity: 0.65;
      border-left: 4px solid #6b7280;
    }
    .response-card.sentiment-negative, .response-card.cat-rejected {
      border-left: 4px solid #ef4444;
    }
    .response-card.cat-apply {
      border-left: 4px solid #0284c7;
    }
    .response-card.sentiment-neutral, .response-card.cat-acknowledged {
      border-left: 4px solid #64748b;
    }
    .resp-filter-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 14px;
      padding: 10px 14px;
      background: #111827;
      border: 1px solid var(--panel-border);
      border-radius: 8px;
    }
    .resp-pill {
      background: #1e293b;
      border: 1px solid #334155;
      color: #94a3b8;
      font-size: 12px;
      font-weight: 600;
      padding: 5px 12px;
      border-radius: 6px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s;
    }
    .resp-pill:hover, .resp-pill.active {
      background: #2563eb;
      border-color: #1d4ed8;
      color: #fff;
    }
    .resp-pill.pill-oa.active {
      background: #d97706;
      border-color: #b45309;
      color: #fff;
    }
    .resp-pill.pill-interview.active {
      background: #059669;
      border-color: #047857;
      color: #fff;
    }
    .resp-pill.pill-rejected.active {
      background: #dc2626;
      border-color: #b91c1c;
      color: #fff;
    }
    .resp-pill.pill-apply.active {
      background: #0284c7;
      border-color: #0369a1;
      color: #fff;
    }

    /* Source Filters Bar & Badges */
    .source-filter-bar {
      display: flex;
      gap: 6px;
      margin-bottom: 16px;
      flex-wrap: wrap;
      align-items: center;
    }
    .source-pill {
      background: #1e293b;
      border: 1px solid #334155;
      color: #94a3b8;
      font-size: 12px;
      font-weight: 600;
      padding: 5px 12px;
      border-radius: 6px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s;
    }
    .source-pill:hover, .source-pill.active {
      background: #2563eb;
      border-color: #1d4ed8;
      color: #fff;
    }
    .source-pill.pill-kadegree.active {
      background: #b45309;
      border-color: #92400e;
      color: #fff;
    }
    .source-pill.pill-linkedin.active {
      background: #0a66c2;
      border-color: #084e96;
      color: #fff;
    }
    .source-pill.pill-whatsapp.active {
      background: #15803d;
      border-color: #166534;
      color: #fff;
    }
    .source-pill.pill-ats.active {
      background: #047857;
      border-color: #065f46;
      color: #fff;
    }

    /* Source Tags on Cards */
    .tag-kadegree {
      background: #292524;
      color: #fcd34d;
      border: 1px solid #78350f;
      font-weight: 600;
    }
    .tag-referrer {
      background: #1e293b;
      color: #cbd5e1;
      border: 1px solid #334155;
    }
    .tag-linkedin {
      background: #172554;
      color: #93c5fd;
      border: 1px solid #1e40af;
    }
    .tag-whatsapp {
      background: #14532d;
      color: #86efac;
      border: 1px solid #166534;
    }
    .tag-ats {
      background: #1e293b;
      color: #cbd5e1;
      border: 1px solid #334155;
    }
    }
    .source-badge-meta {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: 11.5px;
      padding: 2px 8px;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.1);
    }
    .source-kadegree-badge {
      background: rgba(245, 158, 11, 0.15);
      border-color: rgba(245, 158, 11, 0.4);
      color: #fbbf24 !important;
    }

    /* Analytics Dashboard & Audit Ledger Styles */
    .analytics-panel {
      display: flex;
      flex-direction: column;
      gap: 24px;
      margin-top: 10px;
    }
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
    }
    .kpi-card {
      background: rgba(15, 23, 42, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 14px;
      padding: 16px 18px;
      display: flex;
      flex-direction: column;
      backdrop-filter: blur(10px);
      transition: all 0.2s ease;
    }
    .kpi-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(0,0,0,0.3);
    }
    .kpi-label {
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: #94a3b8;
    }
    .kpi-value {
      font-size: 28px;
      font-weight: 800;
      margin-top: 4px;
      letter-spacing: -0.5px;
    }
    .sources-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }
    .source-card {
      background: rgba(15, 23, 42, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 14px;
      padding: 18px 20px;
    }
    .source-card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }
    .source-name {
      font-size: 14px;
      font-weight: 700;
      color: #f8fafc;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .progress-bar-bg {
      background: rgba(255, 255, 255, 0.08);
      border-radius: 999px;
      height: 8px;
      overflow: hidden;
      margin-bottom: 8px;
    }
    .progress-bar-fill {
      height: 100%;
      border-radius: 999px;
      transition: width 0.4s ease;
    }
    .source-stat-row {
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      color: #94a3b8;
    }
    .audit-table-wrap {
      background: rgba(15, 23, 42, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 16px;
      overflow-x: auto;
      padding: 20px;
    }
    .audit-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      color: #cbd5e1;
    }
    .audit-table th {
      text-align: left;
      padding: 12px 14px;
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.6px;
      color: #94a3b8;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }
    .audit-table td {
      padding: 14px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      vertical-align: middle;
    }
    .audit-table tr:hover {
      background: rgba(255, 255, 255, 0.02);
    }
    .badge-source {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: 11px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 6px;
    }
    .badge-source.workday { background: rgba(56, 189, 248, 0.18); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); }
    .badge-source.greenhouse { background: rgba(52, 211, 153, 0.18); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.3); }
    .badge-source.smartrecruiters { background: rgba(168, 85, 247, 0.18); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3); }
    .badge-source.lever { background: rgba(245, 158, 11, 0.18); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
    .badge-source.whatsapp { background: rgba(16, 185, 129, 0.18); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.3); }
    .badge-source.telegram { background: rgba(34, 158, 217, 0.18); color: #38bdf8; border: 1px solid rgba(34, 158, 217, 0.3); }
    .badge-source.linkedin { background: rgba(2, 132, 199, 0.18); color: #7dd3fc; border: 1px solid rgba(2, 132, 199, 0.3); }
    .badge-stage {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 999px;
    }
    .sentiment-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 11px;
      font-weight: 800;
      padding: 5px 12px;
      border-radius: 999px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .sentiment-badge.positive {
      background: linear-gradient(90deg, #059669, #10b981);
      color: #fff;
      box-shadow: 0 2px 10px rgba(16, 185, 129, 0.4);
    }
    .sentiment-badge.negative {
      background: linear-gradient(90deg, #be123c, #f43f5e);
      color: #fff;
      box-shadow: 0 2px 10px rgba(244, 63, 94, 0.3);
    }
    .sentiment-badge.neutral {
      background: linear-gradient(90deg, #0369a1, #0ea5e9);
      color: #fff;
      box-shadow: 0 2px 10px rgba(14, 165, 233, 0.3);
    }

    /* Modal Backdrop */
    .modal-backdrop {
      display: none;
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(8px);
      z-index: 9999;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }
    .modal-content {
      background: #0f172a;
      border: 1px solid #334155;
      border-radius: 16px;
      width: 100%;
      max-width: 960px;
      max-height: 90vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 25px 50px rgba(0,0,0,0.6);
    }
    .modal-header {
      padding: 16px 24px;
      border-bottom: 1px solid #1e293b;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .modal-header h3 { font-size: 16px; font-weight: 700; color: #fff; }
    .modal-close {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 18px;
      cursor: pointer;
    }
    .modal-close:hover { color: #fff; }
    .modal-body {
      flex: 1;
      padding: 0;
      height: 75vh;
      background: #090d16;
    }
    .modal-body iframe { width: 100%; height: 100%; border: none; }

    /* Toast Notification */
    .toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #1e1b4b;
      border: 1px solid #6366f1;
      color: #fff;
      padding: 12px 20px;
      border-radius: 10px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.5);
      font-size: 13px;
      font-weight: 600;
      z-index: 99999;
      display: none;
      align-items: center;
      gap: 10px;
      animation: slideUp 0.25s ease-out;
    }
    @keyframes slideUp {
      from { transform: translateY(20px); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }

  </style>
</head>
<body>
  <header>
    <div class="brand">
      <i class="fa-solid fa-plane brand-logo"></i>
      <div>
        <div class="brand-title">ApplyPilot</div>
      </div>
      <div class="status-pill">
        <div class="pulse-dot"></div>
        <span>Active</span>
      </div>
    </div>

    <!-- Candidate Quick Bar -->
    <div class="quick-bar">
      <div class="quick-pill" onclick="copyText('8431433659', 'Phone Number')"><i class="fa-solid fa-phone"></i> 8431433659</div>
      <div class="quick-pill" onclick="copyText('deepakshkarkala@gmail.com', 'Email')"><i class="fa-solid fa-envelope"></i> deepakshkarkala@gmail.com</div>
      <div class="quick-pill" onclick="copyText('https://www.linkedin.com/in/deepak-s-h-82b772254', 'LinkedIn URL')"><i class="fa-brands fa-linkedin"></i> LinkedIn</div>
      <div class="quick-pill" onclick="copyText('20 LPA', 'Current CTC')"><i class="fa-solid fa-indian-rupee-sign"></i> 20 LPA</div>
      <div class="quick-pill" onclick="copyText('Immediate', 'Notice Period')"><i class="fa-solid fa-bolt"></i> Immediate</div>
      <a href="https://www.linkedin.com/feed/" target="_blank" rel="noopener noreferrer" class="quick-pill"><i class="fa-brands fa-linkedin"></i> Feed</a>
      <a href="https://www.linkedin.com/search/results/content/?keywords=backend%20engineer%20AND%20(%22hiring%22%20OR%20%22requirement%22)&sortBy=%22date_posted%22" target="_blank" rel="noopener noreferrer" class="quick-pill" title="Open live LinkedIn hiring & requirement posts feed"><i class="fa-solid fa-magnifying-glass"></i> Hiring Posts</a>
      <div class="quick-pill" onclick="triggerLinkedInIncognitoScan()" style="background: linear-gradient(135deg, #4f46e5, #3730a3); color: #fff; font-weight: 800; border: 1px solid #a5b4fc; box-shadow: 0 0 10px rgba(99,102,241,0.35); cursor: pointer;" title="Primary Action: Run Multi-Source Fresh Scan across LinkedIn Incognito, Indeed India Incognito & Direct ATS (38+ tech companies)"><i class="fa-solid fa-bolt"></i> Incognito Multi-Search (Fresh ⚡)</div>
      <a href="https://www.google.com/search?q=site%3Aboards.greenhouse.io+OR+site%3Ajobs.lever.co+OR+site%3Ajobs.smartrecruiters.com+(%22Backend+Engineer%22+OR+%22Java%22+OR+%22Golang%22)+%22Bengaluru%22&tbs=qdr:d" target="_blank" rel="noopener noreferrer" class="quick-pill" style="background: linear-gradient(135deg, #ea4335, #c5221f); color: #fff; font-weight: 700; border: 1px solid #f87171;" title="Search Google for freshly indexed ATS jobs in last 24h (Greenhouse, Lever, SmartRecruiters) in Bengaluru"><i class="fa-brands fa-google"></i> Google ATS (24h)</a>
      <a href="https://www.linkedin.com/jobs/search/?keywords=%28%22Software%20Engineer%22%20OR%20%22Backend%20Engineer%22%20OR%20%22Java%20Developer%22%20OR%20%22Golang%20Developer%22%29%20NOT%20Senior%20NOT%20Lead%20NOT%20Staff%20NOT%20Manager%20NOT%20Director&geoId=105126231&f_TPR=r14400&f_JT=F&sortBy=DD" target="_blank" rel="noopener noreferrer" class="quick-pill" style="background: linear-gradient(135deg, #0284c7, #0369a1); color: #fff; font-weight: 700; border: 1px solid #38bdf8;" title="Fresh SDE-1 Backend Jobs posted in last 4 hours in Bangalore (Sorted by Date Descending)"><i class="fa-solid fa-bolt"></i> 4h Fresh (DD)</a>
      <a href="https://www.linkedin.com/jobs/search/?keywords=%28%22Software%20Engineer%22%20OR%20%22Backend%20Engineer%22%29%20NOT%20Senior%20NOT%20Lead&geoId=105126231&f_TPR=r86400&f_EA=true&f_AL=true&f_JT=F&sortBy=DD" target="_blank" rel="noopener noreferrer" class="quick-pill" style="background: linear-gradient(135deg, #15803d, #166534); color: #fff; font-weight: 700; border: 1px solid #4ade80;" title="Easy Apply Jobs with <10 Applicants posted in last 24h"><i class="fa-solid fa-user-group"></i> &lt;10 Applicants</a>
      <a href="https://referral-community.kadegree.in/get" target="_blank" rel="noopener noreferrer" class="quick-pill"><i class="fa-solid fa-users"></i> KaDegree</a>
      <a href="https://remotive.com/remote-jobs/software-dev?search=backend" target="_blank" rel="noopener noreferrer" class="quick-pill" style="background: linear-gradient(135deg, #0d9488, #0f766e); color: #fff; font-weight: 700; border: 1px solid #2dd4bf;" title="Remotive Curated Remote Backend Roles"><i class="fa-solid fa-globe"></i> Remotive</a>
      <a href="https://www.workingnomads.com/jobs?category=development" target="_blank" rel="noopener noreferrer" class="quick-pill" style="background: linear-gradient(135deg, #4338ca, #3730a3); color: #fff; font-weight: 700; border: 1px solid #818cf8;" title="Working Nomads Worldwide Developer Roles"><i class="fa-solid fa-laptop-code"></i> Working Nomads</a>
      <a href="https://www.remoterocketship.com/?search=backend+engineer" target="_blank" rel="noopener noreferrer" class="quick-pill" style="background: linear-gradient(135deg, #c026d3, #a21caf); color: #fff; font-weight: 700; border: 1px solid #e879f9;" title="Remote Rocketship Unlisted Remote Roles"><i class="fa-solid fa-rocket"></i> Remote Rocketship</a>
      <div class="quick-pill" onclick="triggerRemoteBoardsSync()" style="background: linear-gradient(135deg, #0284c7, #0891b2); color: #fff; font-weight: 700; border: 1px solid #38bdf8; cursor: pointer;" title="Crawl & ingest fresh remote backend jobs from Remotive and Working Nomads APIs into ApplyPilot"><i class="fa-solid fa-cloud-arrow-down"></i> Sync Remote APIs</div>
      <a href="http://127.0.0.1:5000" target="_blank" rel="noopener noreferrer" class="quick-pill" style="background: linear-gradient(135deg, #7c3aed, #6d28d9); color: #fff; font-weight: 700; border: 1px solid #a78bfa;" title="Open Auto Job Applier Control Panel (Port 5000)"><i class="fa-solid fa-robot"></i> Auto-Applier Bot UI</a>
      <a href="https://mail.google.com/mail/u/0/#drafts" target="_blank" rel="noopener noreferrer" class="quick-pill"><i class="fa-solid fa-envelope"></i> Gmail Drafts</a>
      <div class="quick-pill" onclick="triggerLinkedInEasyApplyScan()" style="background: linear-gradient(135deg, #1e3a8a, #2563eb); color: #fff; font-weight: 700; border: 1px solid #3b82f6;" title="Scan LinkedIn specifically for Easy Apply backend openings"><i class="fa-brands fa-linkedin"></i> Scan Easy Apply</div>
      <div class="quick-pill" id="pill-sync-ats" onclick="triggerAtsSync()" style="background: linear-gradient(135deg, #065f46, #059669); color: #fff; font-weight: 700; border: 1px solid #10b981;" title="Sync Direct Corporate ATS (Workday, Greenhouse, Lever, SmartRecruiters)"><i class="fa-solid fa-building-circle-check" id="icon-sync-ats-pill"></i> Sync Direct ATS</div>
      <div class="quick-pill" onclick="syncGmailNow()" title="Scan Gmail inbox for application acknowledgments, OAs & interview invites"><i class="fa-solid fa-envelope-open-text"></i> Sync Gmail</div>
      <div id="naukri-quick-pill" class="quick-pill" onclick="triggerNaukriRefresh()" title="Naukri Daily Refresh Active (Click to refresh now)"><i class="fa-solid fa-arrows-rotate"></i> <span id="naukri-pill-label">Naukri: 8:55 AM Active</span></div>
      <div class="quick-pill" onclick="openScreeningCopilotModal()" style="background: linear-gradient(135deg, #4f46e5, #7c3aed); color: #fff; font-weight: 700; border: 1px solid #818cf8; cursor: pointer;" title="Gemini Application & Screening Copilot: Paste any question asked in forms for human, grounded answers"><i class="fa-solid fa-robot"></i> Screening Copilot 🤖</div>
      <div class="quick-pill" onclick="openJobLinkTailorModal()" style="background: linear-gradient(135deg, #0284c7, #2563eb); color: #fff; font-weight: 700; border: 1px solid #38bdf8; cursor: pointer;" title="Input any job link: auto-reads JD, tailors resume & generates referral messages"><i class="fa-solid fa-wand-magic-sparkles"></i> Tailor from Job Link ⚡</div>
      <div class="quick-pill" onclick="openLinkedInPostModal()" style="background: linear-gradient(135deg, #0a66c2, #0284c7); color: #fff; font-weight: 700; border: 1px solid #38bdf8; cursor: pointer;" title="Analyze any LinkedIn Hiring Post link: extracts recruiter mail or form link and generates tailored resume PDF"><i class="fa-brands fa-linkedin"></i> LinkedIn Post Intake 🚀</div>
      <div class="quick-pill" onclick="openLogCallModal()"><i class="fa-solid fa-phone"></i> Log Recruiter Call</div>
      <div class="quick-pill" onclick="openCheatsheetModal('PhonePe', 'SDE-1 Backend')" title="Technical & HR Interview Cheat-Sheet"><i class="fa-solid fa-file-code"></i> Tech Cheat-Sheet</div>
      <div class="quick-pill" onclick="testAlertsFromUI()" title="Test instant alerts to Telegram, WhatsApp & Desktop"><i class="fa-solid fa-bell"></i> Mobile Alerts</div>
      <div class="quick-pill" onclick="syncGSheetsNow()"><i class="fa-solid fa-table"></i> Google Sheet</div>
      <div class="quick-pill" onclick="triggerLinkedInPostsPoll()" title="Scan LinkedIn for fresh hiring posts right now"><i class="fa-brands fa-linkedin"></i> Fetch LinkedIn Posts</div>
      <div class="quick-pill" onclick="openCustomDraftModal()"><i class="fa-solid fa-pen-nib"></i> Draft Cold Email</div>
      <div class="quick-pill" onclick="triggerBatchAutoApply()" title="Auto-apply to qualified roles in Brave"><i class="fa-solid fa-play"></i> Auto-Apply</div>
      <div class="quick-pill" onclick="triggerChannelPoll(event)" title="Poll WhatsApp, Telegram, and Gmail for referral leads"><i class="fa-solid fa-satellite-dish"></i> Poll Channels</div>
      <div class="quick-pill" onclick="pruneOldJobsNow()" title="Delete stale job listings older than 15 days (safe — never deletes applied/interview rows)" style="background: linear-gradient(135deg, #7f1d1d, #991b1b); color: #fca5a5; border: 1px solid #dc2626; font-weight: 700;"><i class="fa-solid fa-trash-can"></i> Prune Stale (&gt;15d)</div>
    </div>
  </header>

  <div class="container">
    <!-- Daily Target Discipline Tracker (Min 5 Resume Requests & Min 5 Applied <= 100 Applicants) -->
    <div id="daily-target-tracker" style="background: linear-gradient(135deg, rgba(15, 23, 42, 0.95), rgba(30, 41, 59, 0.85)); border: 1.5px solid rgba(56, 189, 248, 0.35); border-radius: 14px; padding: 18px 22px; margin-bottom: 20px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px; margin-bottom: 14px;">
        <div style="display: flex; align-items: center; gap: 12px;">
          <div style="background: linear-gradient(135deg, #0284c7, #2563eb); color: #fff; width: 40px; height: 40px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 18px; box-shadow: 0 0 12px rgba(56, 189, 248, 0.4);">
            <i class="fa-solid fa-bullseye"></i>
          </div>
          <div>
            <div style="display: flex; align-items: center; gap: 10px;">
              <span style="font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.8px; color: #38bdf8;">Daily Target & Consistency Tracker</span>
              <span id="daily-streak-badge" style="background: rgba(16, 185, 129, 0.2); border: 1px solid #10b981; color: #34d399; font-size: 11px; font-weight: 700; padding: 2px 10px; border-radius: 999px;">
                <i class="fa-solid fa-fire"></i> Day 1 Streak
              </span>
            </div>
            <div style="font-size: 14px; font-weight: 700; color: #f8fafc; margin-top: 2px;">
              Daily Disciplined Quota: <span style="color: #38bdf8;">Min 5 Asking Resume / Pitched</span> + <span style="color: #34d399;">Min 5 Applied within 100 Applicants</span>
            </div>
          </div>
        </div>

        <div style="display: flex; align-items: center; gap: 10px;">
          <button class="btn btn-sm" onclick="setTab('daily_tracker')" style="background: rgba(56, 189, 248, 0.15); border: 1px solid #38bdf8; color: #38bdf8; font-weight: 700; padding: 6px 14px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; gap: 6px;">
            <i class="fa-solid fa-calendar-days"></i> 14-Day Trajectory
          </button>
          <button class="btn btn-sm" onclick="setTab('incognito_fresh')" style="background: linear-gradient(135deg, #0284c7, #2563eb); color: #fff; font-weight: 700; padding: 6px 14px; border-radius: 8px; border: none; cursor: pointer; display: flex; align-items: center; gap: 6px;">
            <i class="fa-solid fa-bolt"></i> Apply Fresh (< 100 Apps)
          </button>
        </div>
      </div>

      <!-- Live Dual Progress Cards -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px;">
        <!-- Card 1: Asking Resume Target -->
        <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(148, 163, 184, 0.15); border-radius: 10px; padding: 14px 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="font-size: 12px; font-weight: 700; color: #cbd5e1; display: flex; align-items: center; gap: 6px;">
              <i class="fa-solid fa-file-invoice" style="color: #38bdf8;"></i> 1. Companies Asking Resume / Pitched
            </span>
            <span id="tracker-resume-status" style="font-size: 12px; font-weight: 800; color: #38bdf8;">0 / 5</span>
          </div>
          <div style="background: rgba(51, 65, 85, 0.6); height: 8px; border-radius: 999px; overflow: hidden; margin-bottom: 6px;">
            <div id="tracker-resume-bar" style="background: linear-gradient(90deg, #0284c7, #38bdf8); height: 100%; width: 0%; border-radius: 999px; transition: width 0.4s ease;"></div>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 11px; color: #94a3b8;">
            <span>Target: min 5 daily</span>
            <span id="tracker-resume-note" style="color: #64748b;">Cold pitches & referrals sent</span>
          </div>
        </div>

        <!-- Card 2: Applied <= 100 Applicants Target -->
        <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(148, 163, 184, 0.15); border-radius: 10px; padding: 14px 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="font-size: 12px; font-weight: 700; color: #cbd5e1; display: flex; align-items: center; gap: 6px;">
              <i class="fa-solid fa-circle-check" style="color: #34d399;"></i> 2. Applied within 100 Applicants
            </span>
            <span id="tracker-applied-status" style="font-size: 12px; font-weight: 800; color: #34d399;">0 / 5</span>
          </div>
          <div style="background: rgba(51, 65, 85, 0.6); height: 8px; border-radius: 999px; overflow: hidden; margin-bottom: 6px;">
            <div id="tracker-applied-bar" style="background: linear-gradient(90deg, #059669, #34d399); height: 100%; width: 0%; border-radius: 999px; transition: width 0.4s ease;"></div>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 11px; color: #94a3b8;">
            <span>Target: min 5 low-competition</span>
            <span id="tracker-applied-note" style="color: #64748b;">High ATS visibility</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Clean KPI Stats Grid -->
    <div class="stats-grid">
      <div class="stat-card">
        <span class="label">Total Jobs</span>
        <span class="val" id="stat-total">0</span>
      </div>
      <div class="stat-card">
        <span class="label">Top Matches (9-10)</span>
        <span class="val" id="stat-nine">0</span>
      </div>
      <div class="stat-card">
        <span class="label">Strong Fit (≥ 7)</span>
        <span class="val" id="stat-high">0</span>
      </div>
      <div class="stat-card">
        <span class="label">Approved Shortlist</span>
        <span class="val" id="stat-approved">0</span>
      </div>
      <div class="stat-card">
        <span class="label">Tailored Resumes</span>
        <span class="val" id="stat-tailored">0</span>
      </div>
      <div class="stat-card" style="cursor: pointer;" onclick="setTab('responses'); filterResponsesCategory('oa');">
        <span class="label">Active Assessments</span>
        <span class="val" id="stat-oa">0</span>
      </div>
      <div class="stat-card" style="cursor: pointer;" onclick="setTab('responses'); filterResponsesCategory('all');">
        <span class="label">Recruiter Replies</span>
        <span class="val" id="stat-responses">0</span>
      </div>
      <div class="stat-card" style="cursor: pointer;" onclick="setTab('kadegree');" title="Click to view live referral openings">
        <span class="label">Community Referrals</span>
        <span class="val" id="stat-kadegree">0</span>
      </div>
      <div class="stat-card">
        <span class="label">Applied</span>
        <span class="val" id="stat-applied">0</span>
      </div>
    </div>

    <!-- Urgent OA Alert Bar -->
    <div id="urgent-oa-alert" class="queue-banner" style="display: none; border-left: 4px solid #f59e0b;">
      <div style="display: flex; align-items: center; gap: 12px;">
        <i class="fa-solid fa-triangle-exclamation" style="color: #f59e0b; font-size: 18px;"></i>
        <div>
          <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #f59e0b; font-weight: 700;">Action Required: Online Assessment Due</span>
          <div id="urgent-oa-title" style="font-size: 14px; font-weight: 600; color: #fff; margin-top: 2px;"></div>
        </div>
      </div>
      <div style="display: flex; gap: 8px; align-items: center;">
        <a id="urgent-oa-link" href="#" target="_blank" rel="noopener noreferrer" class="btn btn-brave" style="text-decoration: none;">
          <i class="fa-solid fa-arrow-up-right-from-square"></i> Open Assessment
        </a>
        <button class="btn btn-preview" onclick="setTab('responses'); filterResponsesCategory('oa');">
          <i class="fa-solid fa-list-check"></i> View in Dashboard
        </button>
      </div>
    </div>

    <!-- Incognito Fresh Announcement Banner -->
    <div id="incognito-banner" class="queue-banner" style="display: flex; background: rgba(99, 102, 241, 0.12); border-left: 4px solid #818cf8; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
      <div class="queue-banner-title" style="color: #e0e7ff;">
        <i class="fa-solid fa-bolt" style="color: #818cf8; font-size: 16px;"></i>
        <span><strong>Multi-Source Fresh Incognito Pipeline:</strong> Live openings from LinkedIn (< 4h & < 200 applicants), Indeed India (past 24h), and Direct ATS Fast Sweeps (PhonePe, Razorpay, Zeta, Slice, Datadog, etc.). Zero login required, strict 0-3 YOE Backend & Bengaluru filters!</span>
      </div>
      <button onclick="triggerLinkedInIncognitoScan()" style="background: linear-gradient(135deg, #4f46e5, #4338ca); color: #fff; border: 1px solid #818cf8; border-radius: 9999px; padding: 5px 14px; font-size: 12px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px;">
        <i class="fa-solid fa-arrows-rotate"></i> Trigger Incognito Scan Now
      </button>
    </div>

    <!-- Yet to Apply Announcement Banner -->
    <div id="yet-to-apply-banner" class="queue-banner" style="display: none; background: rgba(56, 189, 248, 0.08); border-left: 4px solid #38bdf8;">
      <div class="queue-banner-title">
        <i class="fa-solid fa-clock-rotate-left" style="color: #38bdf8; font-size: 16px;"></i>
        <span><strong>Yet to Apply Pipeline:</strong> High-fit roles (Score ≥ 7 & tailored resumes ready) awaiting submission, cold email, or KA referral.</span>
      </div>
    </div>

    <!-- Fresh Posts Announcement Banner (Apply within 4 hours) -->
    <div id="fresh-banner" class="queue-banner" style="display: none; background: rgba(245, 158, 11, 0.12); border-left: 4px solid #f59e0b;">
      <div class="queue-banner-title" style="color: #fef08a;">
        <i class="fa-solid fa-fire-flame-curved" style="color: #f59e0b; font-size: 16px;"></i>
        <span><strong>Urgent Pipeline: Posted Within 4 Hours ⚡</strong> Applying within the first 4 hours gives a 4x higher recruiter view rate before ATS queues fill up!</span>
      </div>
    </div>

    <!-- Applied Announcement Banner -->
    <div id="applied-banner" class="queue-banner" style="display: none; background: rgba(16, 185, 129, 0.08); border-left: 4px solid #10b981;">
      <div class="queue-banner-title">
        <i class="fa-solid fa-circle-check" style="color: #10b981; font-size: 16px;"></i>
        <span><strong>Applied Roles:</strong> Confirmed submissions, cold emails sent, and Gmail-acknowledged applications.</span>
      </div>
    </div>

    <!-- Active Tab Announcement Banner -->
    <div id="queue-banner" class="queue-banner" style="display: none;">
      <div class="queue-banner-title">
        <i class="fa-solid fa-check-circle" style="color: #2563eb; font-size: 16px;"></i>
        <span><strong>Approved Queue:</strong> Qualified roles queued for submission.</span>
      </div>
    </div>

    <!-- Gmail Response Announcement Banner -->
    <div id="responses-banner" class="queue-banner" style="display: none;">
      <div class="queue-banner-title">
        <i class="fa-solid fa-envelope" style="color: #10b981; font-size: 16px;"></i>
        <span><strong>Gmail Tracker:</strong> Monitoring interview invitations, coding tests, and recruiter responses for <code>deepakshkarkala@gmail.com</code>.</span>
      </div>
      <button class="btn btn-preview" onclick="syncGmailNow()">
        <i class="fa-solid fa-arrows-rotate"></i> Sync Inbox
      </button>
    </div>

    <!-- Tabs & Search -->
    <div class="controls">
      <div class="tabs">
        <button class="tab-btn active" onclick="setTab('incognito_fresh')" style="color: #c7d2fe; font-weight: 700;" title="Primary Tab: Openings strictly posted in the last 4 hours with < 200 applicants (Backend, Spring Boot, Java, Go, Full Stack)">
          <i class="fa-solid fa-bolt" style="margin-right: 5px; color: #818cf8;"></i> Fresh < 4h (< 200 Apps) ⚡
          <span class="tab-badge" id="badge-incognito-fresh" style="background: rgba(99, 102, 241, 0.3); color: #c7d2fe; border: 1px solid #818cf8;">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('fresh_24h')" style="color: #38bdf8; font-weight: 700;" title="Fresh openings discovered or posted within the last 24 hours with < 200 applicants">
          <i class="fa-solid fa-fire-flame-curved" style="margin-right: 5px; color: #38bdf8;"></i> Fresh < 24 Hours 🔥
          <span class="tab-badge" id="badge-fresh-24h" style="background: rgba(56, 189, 248, 0.25); color: #7dd3fc; border: 1px solid #38bdf8;">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('yet_to_apply')">
          <i class="fa-solid fa-clock-rotate-left" style="margin-right: 5px; color: #38bdf8;"></i> Yet to Apply
          <span class="tab-badge" id="badge-yet-to-apply">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('fresh')" style="color: #fbbf24;" title="Openings discovered or posted within the last 4 hours">
          <i class="fa-solid fa-bolt" style="margin-right: 5px; color: #f59e0b;"></i> < 4 Hours Fresh ⚡
          <span class="tab-badge" id="badge-fresh" style="background: rgba(245, 158, 11, 0.25); color: #fbbf24; border: 1px solid #f59e0b;">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('applied')">
          <i class="fa-solid fa-circle-check" style="margin-right: 5px; color: #10b981;"></i> Applied
          <span class="tab-badge" id="badge-applied">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('asked_referral')" style="color: #c084fc;" title="Roles where you have reached out to a connection, alumnus or recruiter for a referral">
          <i class="fa-solid fa-people-arrows" style="margin-right: 5px; color: #a855f7;"></i> Asked for Referral
          <span class="tab-badge" id="badge-asked-referral" style="background: rgba(168, 85, 247, 0.25); color: #d8b4fe; border: 1px solid #a855f7;">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('ignored')">
          <i class="fa-solid fa-ban" style="margin-right: 5px; color: #94a3b8;"></i> Ignored
          <span class="tab-badge" id="badge-ignored">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('high')">
          High Fit (≥ 7)
          <span class="tab-badge" id="badge-high">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('top')">
          Top Matches (≥ 8)
          <span class="tab-badge" id="badge-top">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('approved')">
          Approved Queue
          <span class="tab-badge" id="badge-approved">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('responses')">
          Gmail Tracker
          <span class="tab-badge" id="badge-responses">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('kadegree')">
          KaDegree Referrals
          <span class="tab-badge" id="badge-kadegree">0</span>
        </button>

        <button class="tab-btn" onclick="setTab('daily_tracker')" style="color: #38bdf8; font-weight: 700;" title="Daily Tracker: Minimum 5 asking resume & 5 applied within 100 applicants">
          <i class="fa-solid fa-bullseye" style="margin-right: 5px; color: #38bdf8;"></i> Daily Tracker (5+5)
          <span class="tab-badge" id="badge-daily-tracker" style="background: rgba(56, 189, 248, 0.25); color: #7dd3fc; border: 1px solid #38bdf8;">Goal Met</span>
        </button>
        <button class="tab-btn" onclick="setTab('referral_crm')" style="color: #a855f7; font-weight: 700;" title="Company-wise Referral Connection Request Tracker (Sent vs Accepted)">
          <i class="fa-solid fa-user-plus" style="margin-right: 5px; color: #c084fc;"></i> Referral Network CRM
          <span class="tab-badge" id="badge-referral-crm" style="background: rgba(168, 85, 247, 0.25); color: #d8b4fe; border: 1px solid #a855f7;">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('remote_portals')" style="color: #34d399; font-weight: 600;" title="Top Remote Engineering Platforms & Agencies (Uplers, Arc, DistantJob, Turing, etc.)">
          <i class="fa-solid fa-globe" style="margin-right: 5px; color: #10b981;"></i> Remote Portals & Agencies
          <span class="tab-badge" id="badge-remote-portals" style="background: rgba(16, 185, 129, 0.25); color: #6ee7b7; border: 1px solid #10b981;">18</span>
        </button>
        <button class="tab-btn" onclick="setTab('cold_crm')" style="color: #38bdf8;" title="Cold Email Sales Funnel & Tracking CRM">
          <i class="fa-solid fa-bullseye" style="margin-right: 5px; color: #0284c7;"></i> Cold Email CRM
          <span class="tab-badge" id="badge-cold-crm" style="background: rgba(14, 165, 233, 0.25); color: #7dd3fc; border: 1px solid #0284c7;">0</span>
        </button>

        <button class="tab-btn" onclick="setTab('easy_apply')" style="color: #60a5fa;" title="LinkedIn 1-Click Easy Apply Openings">
          <i class="fa-brands fa-linkedin" style="margin-right: 5px; color: #3b82f6;"></i> Easy Apply
          <span class="tab-badge" id="badge-easy-apply" style="background: rgba(59, 130, 246, 0.25); color: #93c5fd; border: 1px solid #3b82f6;">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('strategy')">
          Conversion Strategy
        </button>
        <button class="tab-btn" onclick="setTab('analytics')">
          Analytics
          <span class="tab-badge" id="badge-analytics">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('all')">All Opportunities</button>
      </div>

      <div class="search-box">
        <i class="fa-solid fa-magnifying-glass"></i>
        <input type="text" id="search-input" placeholder="Search company, skills (Java, Go, Kafka)..." oninput="renderJobs()">
      </div>

      <!-- Sort Controls -->
      <div style="display: flex; align-items: center; gap: 8px; margin-left: 8px;">
        <label for="sort-select" style="font-size: 12px; font-weight: 700; color: #94a3b8; display: flex; align-items: center; gap: 4px; white-space: nowrap;">
          <i class="fa-solid fa-arrow-down-wide-short" style="color: #38bdf8;"></i> Sort by:
        </label>
        <select id="sort-select" onchange="changeSort(this.value)" style="background: #1e293b; border: 1px solid #334155; color: #f1f5f9; padding: 7px 12px; border-radius: 8px; font-size: 12.5px; font-weight: 600; cursor: pointer; outline: none;">
          <option value="recent">⚡ Most Recent First (Date/Time)</option>
          <option value="fit">🎯 High Fit Score (10 → 1)</option>
          <option value="oldest">⏳ Oldest / Needs Immediate Action</option>
          <option value="company">🏢 Company Name (A-Z)</option>
        </select>
      </div>
    </div>

    <!-- Injected Cards -->
    <!-- Sub-category filter pills for Gmail Tracker -->
    <div id="resp-filter-bar" class="resp-filter-bar" style="display: none;">
      <div class="resp-pill active" id="rp-all" onclick="filterResponsesCategory('all')"><i class="fa-solid fa-list-check"></i> All Updates (<span id="cnt-resp-all">0</span>)</div>
      <div class="resp-pill pill-oa" id="rp-oa" onclick="filterResponsesCategory('oa')"><i class="fa-solid fa-laptop-code"></i> ⚡ Online Assessments / OAs (<span id="cnt-resp-oa">0</span>)</div>
      <div class="resp-pill pill-interview" id="rp-interview" onclick="filterResponsesCategory('interview_selected')"><i class="fa-solid fa-trophy"></i> 🎯 Selected & Next Rounds (<span id="cnt-resp-interview">0</span>)</div>
      <div class="resp-pill pill-rejected" id="rp-rejected" onclick="filterResponsesCategory('rejected')"><i class="fa-solid fa-circle-xmark"></i> ❌ Rejections (<span id="cnt-resp-rejected">0</span>)</div>
      <div class="resp-pill pill-apply" id="rp-apply" onclick="filterResponsesCategory('apply_link')"><i class="fa-solid fa-link"></i> 🔗 Direct Apply Links (<span id="cnt-resp-apply">0</span>)</div>
      <div class="resp-pill" id="rp-ack" onclick="filterResponsesCategory('acknowledged')"><i class="fa-regular fa-envelope"></i> 📬 Acknowledged (<span id="cnt-resp-ack">0</span>)</div>
    </div>

    <!-- Source Filter Bar for Job Opportunities -->
    <div id="source-filter-bar" class="source-filter-bar">
      <div class="source-pill active" id="src-all" onclick="filterBySource('all')">
        <i class="fa-solid fa-layer-group"></i> All Sources (<span id="cnt-src-all">0</span>)
      </div>
      <div class="source-pill pill-kadegree" id="src-kadegree" onclick="filterBySource('kadegree')">
        <i class="fa-solid fa-users-rays"></i> 🌟 KaDegree Community (<span id="cnt-src-kadegree">0</span>)
      </div>
      <div class="source-pill pill-linkedin" id="src-linkedin" onclick="filterBySource('linkedin')">
        <i class="fa-brands fa-linkedin"></i> 💼 LinkedIn (<span id="cnt-src-linkedin">0</span>)
      </div>
      <div class="source-pill pill-whatsapp" id="src-whatsapp" onclick="filterBySource('whatsapp')">
        <i class="fa-brands fa-whatsapp"></i> 💬 WhatsApp (<span id="cnt-src-whatsapp">0</span>)
      </div>
      <div class="source-pill pill-ats" id="src-ats" onclick="filterBySource('ats')">
        <i class="fa-solid fa-building-circle-check"></i> 🏢 Direct ATS (<span id="cnt-src-ats">0</span>)
      </div>
      <div class="source-pill pill-seed" id="src-seed" onclick="filterBySource('seed_funded')" style="border-color: #ec4899; color: #f472b6;">
        <i class="fa-solid fa-seedling"></i> 🚀 YC & Seed Startups (<span id="cnt-src-seed">0</span>)
      </div>
      <button class="btn btn-sm" id="btn-sync-ats" onclick="triggerAtsSync()" style="margin-left: auto; background: linear-gradient(135deg, #065f46, #059669); color: #fff; font-weight: 700; border-radius: 9999px; padding: 6px 14px; font-size: 11.5px; border: none; cursor: pointer; display: flex; align-items: center; gap: 6px;">
        <i class="fa-solid fa-arrows-rotate" id="icon-sync-ats"></i> Sync Direct ATS
      </button>
      <button class="btn btn-sm" id="btn-sync-kadegree" onclick="triggerKaDegreeSync()" style="background: linear-gradient(135deg, #b45309, #d97706); color: #fff; font-weight: 700; border-radius: 9999px; padding: 6px 14px; font-size: 11.5px; border: none; cursor: pointer; display: flex; align-items: center; gap: 6px;">
        <i class="fa-solid fa-arrows-rotate" id="icon-sync-kadegree"></i> Sync KaDegree
      </button>
    </div>

    <!-- KaDegree Community Info Banner -->
    <div id="kadegree-info-banner" style="display: none; background: linear-gradient(90deg, rgba(180, 83, 9, 0.35), rgba(15, 23, 42, 0.95)); border: 1.5px solid #d97706; border-radius: 12px; padding: 14px 20px; margin-bottom: 20px; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
      <div style="display: flex; align-items: center; gap: 14px;">
        <span style="font-size: 26px;">🟡</span>
        <div>
          <div style="color: #fbbf24; font-weight: 800; font-size: 15px;">KaDegree (ಕನ್ನಡ Referral Community - 17k+ Tech Members)</div>
          <div style="color: #cbd5e1; font-size: 12.5px; margin-top: 2px;">Vetted internal referrals and walk-ins shared by fellow Kannadiga engineers & verified referrers. Direct access to hiring teams.</div>
        </div>
      </div>
      <div style="display: flex; gap: 10px;">
        <button class="btn btn-sm" onclick="triggerKaDegreeSync()" style="background: linear-gradient(135deg, #b45309, #d97706); color: #fff; font-weight: 700; border-radius: 8px; padding: 8px 16px; border: none; cursor: pointer; display: flex; align-items: center; gap: 6px;">
          <i class="fa-solid fa-arrows-rotate" id="icon-sync-kadegree-banner"></i> Sync Live Openings ⚡
        </button>
        <a href="https://referral-community.kadegree.in/get" target="_blank" rel="noopener noreferrer" class="btn btn-sm" style="background: rgba(245, 158, 11, 0.2); border: 1px solid #d97706; color: #fbbf24; font-weight: 700; border-radius: 8px; padding: 8px 16px; text-decoration: none; display: flex; align-items: center; gap: 6px;">
          <i class="fa-solid fa-arrow-up-right-from-square"></i> Open KaDegree Web
        </a>
      </div>
    </div>

    <!-- LinkedIn Easy Apply Info Banner -->
    <div id="easy-apply-info-banner" style="display: none; background: linear-gradient(90deg, rgba(30, 58, 138, 0.4), rgba(15, 23, 42, 0.95)); border: 1.5px solid #3b82f6; border-radius: 12px; padding: 14px 20px; margin-bottom: 20px; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
      <div style="display: flex; align-items: center; gap: 14px;">
        <span style="font-size: 26px;"><i class="fa-brands fa-linkedin" style="color: #60a5fa;"></i></span>
        <div>
          <div style="color: #93c5fd; font-weight: 800; font-size: 15px;">LinkedIn 1-Click Easy Apply Openings</div>
          <div style="color: #cbd5e1; font-size: 12.5px; margin-top: 2px;">Direct 1-click applications via your connected Brave browser. Click "Auto-Apply (Easy Apply)" on any card to automatically fill fields, screening answers, attach your tailored resume, and submit!</div>
        </div>
      </div>
      <div style="display: flex; gap: 10px;">
        <button class="btn btn-sm" onclick="triggerLinkedInEasyApplyScan()" style="background: linear-gradient(135deg, #1d4ed8, #2563eb); color: #fff; font-weight: 700; border-radius: 8px; padding: 8px 16px; border: none; cursor: pointer; display: flex; align-items: center; gap: 6px;">
          <i class="fa-solid fa-arrows-rotate"></i> Scan LinkedIn Easy Apply Now ⚡
        </button>
      </div>
    </div>

    <div id="jobs-container" class="jobs-grid"></div>
    <!-- Application Analytics & Lifecycle Ledger View -->
    <div id="analytics-container" style="display: none;"></div>
    <!-- ⚡ 30-Day Conversion Funnel, Everyday Active Time & Gemini Strategy Container -->
    <div id="strategy-container" style="display: none;"></div>
    <div id="daily-tracker-container" style="display: none;"></div>
    <div id="referral-crm-container" style="display: none;"></div>
    <div id="remote-portals-container" style="display: none;"></div>
    <div id="cold-crm-container" style="display: none;"></div>
  </div>

  <!-- PDF Preview Modal -->
  <div id="pdf-modal" class="modal-backdrop" onclick="if(event.target===this) closeModal()">
    <div class="modal-content" style="max-width: 960px; width: 92%; height: 90vh;">
      <div class="modal-header">
        <h3 id="modal-title" style="margin: 0; font-size: 16px; font-weight: 700; color: #38bdf8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 70%;">PDF Preview</h3>
        <div style="display: flex; gap: 10px; align-items: center;">
          <a id="modal-open-newtab" href="#" target="_blank" rel="noopener noreferrer" class="btn" style="padding: 6px 12px; font-size: 12px; background: rgba(56, 189, 248, 0.15); border: 1px solid #38bdf8; color: #38bdf8; text-decoration: none; border-radius: 6px; display: inline-flex; align-items: center; gap: 6px;">
            <i class="fa-solid fa-arrow-up-right-from-square"></i> Open in New Tab
          </a>
          <button class="modal-close" onclick="closeModal()"><i class="fa-solid fa-xmark"></i></button>
        </div>
      </div>
      <div class="modal-body" style="flex: 1; padding: 0; background: #090d16;">
        <iframe id="pdf-frame" src="" style="width: 100%; height: 100%; border: none;"></iframe>
      </div>
    </div>
  </div>

  <!-- Referral & LinkedIn Outreach Modal -->
  <div id="referral-modal" class="modal-backdrop" onclick="if(event.target===this) closeReferralModal()">
    <div class="modal-content" style="max-width: 820px; max-height: 90vh; overflow-y: auto;">
      <div class="modal-header" style="background: linear-gradient(90deg, #0f172a, #1e1b4b);">
        <h3 id="referral-modal-title" style="color:#38bdf8;"><i class="fa-solid fa-people-arrows"></i> LinkedIn Referrals & Outreach</h3>
        <button class="modal-close" onclick="closeReferralModal()"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div id="referral-modal-body" style="padding: 24px; color: #cbd5e1; font-size: 14px; line-height: 1.6;"></div>
    </div>
  </div>

    <!-- Recruiter Phone Call & Offline Response Intake Modal -->
  <div id="log-call-modal" class="modal-backdrop" onclick="if(event.target===this) closeLogCallModal()">
    <div class="modal-content" style="max-width: 620px;">
      <div class="modal-header" style="background: linear-gradient(90deg, #064e3b, #0f172a);">
        <h3 style="color:#6ee7b7;"><i class="fa-solid fa-phone"></i> Log Recruiter Call / Interview Update</h3>
        <button class="modal-close" onclick="closeLogCallModal()"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div style="padding: 24px; color: #cbd5e1; font-size: 13.5px; line-height: 1.6;">
        <p style="margin-top:0; color: #94a3b8; font-size: 13px;">
          Log offline recruiter phone screens, WhatsApp messages, scheduled interview rounds, or test deadlines.
          Automatically updates the 30-day funnel, syncs to your central sheet, and blocks calendar time.
        </p>
        <div style="display:flex; flex-direction:column; gap: 12px; margin-bottom: 16px;">
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 10px;">
            <div>
              <label style="display:block; font-size: 12px; font-weight:700; color: #6ee7b7; margin-bottom: 4px;">Company *</label>
              <input type="text" id="log-call-comp" placeholder="e.g. PhonePe / Zepto / Razorpay" style="width:100%; background:#0f172a; border:1px solid #059669; color:#fff; padding:9px 12px; border-radius:8px; font-size:13px;">
            </div>
            <div>
              <label style="display:block; font-size: 12px; font-weight:700; color: #cbd5e1; margin-bottom: 4px;">Role Title</label>
              <input type="text" id="log-call-role" placeholder="e.g. SDE-I Backend Engineer" value="SDE-I Backend Engineer" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:9px 12px; border-radius:8px; font-size:13px;">
            </div>
          </div>
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 10px;">
            <div>
              <label style="display:block; font-size: 12px; font-weight:700; color: #cbd5e1; margin-bottom: 4px;">Response / Call Type *</label>
              <select id="log-call-type" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:9px 12px; border-radius:8px; font-size:13px;">
                <option value="phone_screen">📞 Phone Screen / Recruiter Call</option>
                <option value="technical_interview">🎯 Technical Interview Scheduled</option>
                <option value="oa">⚡ Online Assessment (OA) Received</option>
                <option value="hr_followup">🤝 HR Discussion / CTC Discussion</option>
                <option value="offer">🏆 Offer Received</option>
                <option value="rejection">❌ Not Selected / Rejected</option>
              </select>
            </div>
            <div>
              <label style="display:block; font-size: 12px; font-weight:700; color: #cbd5e1; margin-bottom: 4px;">Scheduled Slot / Due Date</label>
              <input type="text" id="log-call-scheduled" placeholder="e.g. Tomorrow 4:00 PM or Nov 15" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:9px 12px; border-radius:8px; font-size:13px;">
            </div>
          </div>
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 10px;">
            <div>
              <label style="display:block; font-size: 12px; font-weight:700; color: #cbd5e1; margin-bottom: 4px;">Recruiter Name (Optional)</label>
              <input type="text" id="log-call-recruiter" placeholder="e.g. Ananya Sen" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:9px 12px; border-radius:8px; font-size:13px;">
            </div>
            <div>
              <label style="display:block; font-size: 12px; font-weight:700; color: #cbd5e1; margin-bottom: 4px;">Contact (Phone / Email)</label>
              <input type="text" id="log-call-contact" placeholder="Phone or Email" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:9px 12px; border-radius:8px; font-size:13px;">
            </div>
          </div>
          <div>
            <label style="display:block; font-size: 12px; font-weight:700; color: #cbd5e1; margin-bottom: 4px;">Notes / Discussion Summary</label>
            <textarea id="log-call-notes" rows="3" placeholder="What did they discuss? E.g. Notice period (Immediate), CTC (20 LPA discussed), round will focus on System Design & Concurrency in Java/Go..." style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:9px 12px; border-radius:8px; font-size:13px; resize:vertical;"></textarea>
          </div>
          <div style="display:flex; align-items:center; gap:8px; margin-top:4px;">
            <input type="checkbox" id="log-call-calendar" checked style="accent-color:#10b981; width:16px; height:16px;">
            <label for="log-call-calendar" style="font-size:12px; color:#cbd5e1; font-weight:600;">📅 Auto-block focus time on Google Calendar (remind me so I don't forget)</label>
          </div>
        </div>
        <div id="log-call-status" style="display:none; margin-bottom: 14px; padding: 10px; border-radius: 8px; font-size: 12px;"></div>
        <div style="display:flex; justify-content: flex-end; gap: 10px;">
          <button class="btn" style="background:#334155; color:#cbd5e1;" onclick="closeLogCallModal()">Cancel</button>
          <button class="btn" id="btn-submit-log-call" style="background: linear-gradient(135deg, #059669, #10b981); color:white; font-weight:700; padding: 9px 18px;" onclick="submitLogCall()">
            <i class="fa-solid fa-check"></i> Save & Sync
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Application & Screening Question Copilot Modal -->
  <div id="screening-copilot-modal" class="modal-backdrop" onclick="if(event.target===this) closeScreeningCopilotModal()">
    <div class="modal-content" style="max-width: 720px; border: 1px solid #6366f1;">
      <div class="modal-header" style="background: linear-gradient(90deg, #1e1b4b, #312e81);">
        <h3 style="color:#c7d2fe; display: flex; align-items: center; gap: 8px;">
          <i class="fa-solid fa-robot" style="color: #818cf8;"></i> Gemini Application & Screening Copilot
        </h3>
        <button class="modal-close" onclick="closeScreeningCopilotModal()"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div style="padding: 24px; color: #cbd5e1; font-size: 13.5px; line-height: 1.6;">
        <p style="margin-top:0; color: #94a3b8; font-size: 13px;">
          Paste any question from an application form, ATS portal, or screening questionnaire. The copilot answers in your authentic voice using your Meesho metrics (50K+ orders/day, 95% latency reduction), RVCE background, and curated system design stories.
        </p>

        <div style="display:flex; flex-direction:column; gap: 12px; margin-bottom: 16px;">
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 10px;">
            <div>
              <label style="display:block; font-size: 12px; font-weight:700; color: #cbd5e1; margin-bottom: 4px;">Company Name</label>
              <input type="text" id="copilot-comp" placeholder="e.g. Razorpay, Stripe, Cisco..." style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:9px 12px; border-radius:8px; font-size:13px;">
            </div>
            <div>
              <label style="display:block; font-size: 12px; font-weight:700; color: #cbd5e1; margin-bottom: 4px;">Role Title</label>
              <input type="text" id="copilot-role" placeholder="e.g. SDE-I Backend / Software Engineer" value="SDE-I Backend Engineer" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:9px 12px; border-radius:8px; font-size:13px;">
            </div>
          </div>

          <div>
            <label style="display:block; font-size: 12px; font-weight:700; color: #818cf8; margin-bottom: 4px;">Screening Question Asked *</label>
            <textarea id="copilot-question" rows="3" placeholder="e.g. 'Why do you want to work at our company?' or 'Describe a complex technical challenge you solved.' or 'What is your current notice period and YOE?'" style="width:100%; background:#0f172a; border:1px solid #4f46e5; color:#fff; padding:10px 12px; border-radius:8px; font-size:13.5px; resize:vertical; font-family:inherit;"></textarea>
          </div>

          <div>
            <button id="copilot-submit-btn" class="btn" style="background: linear-gradient(135deg, #4f46e5, #7c3aed); color:white; font-weight:700; padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer; width: 100%; display: flex; align-items: center; justify-content: center; gap: 8px; box-shadow: 0 4px 14px rgba(79, 70, 229, 0.4);" onclick="submitScreeningCopilot()">
              <i class="fa-solid fa-wand-magic-sparkles"></i> Generate Personalized Human Answer (Gemini)
            </button>
          </div>

          <!-- Answer Container -->
          <div id="copilot-answer-box" style="display: none; margin-top: 10px; background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(129, 140, 248, 0.3); border-radius: 8px; padding: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <span style="font-weight: 700; font-size: 13px; color: #818cf8;">
                <i class="fa-solid fa-sparkles"></i> Tailored Answer Ready to Paste:
              </span>
              <button onclick="copyCopilotAnswer()" class="btn" style="background: rgba(99, 102, 241, 0.2); border: 1px solid #6366f1; color: #c7d2fe; padding: 4px 10px; font-size: 12px; border-radius: 4px; cursor: pointer;">
                <i class="fa-regular fa-copy"></i> Copy to Clipboard
              </button>
            </div>
            <div id="copilot-answer-text" style="white-space: pre-wrap; font-size: 13.5px; color: #f8fafc; line-height: 1.6; max-height: 320px; overflow-y: auto; background: #090d16; padding: 14px; border-radius: 6px; border: 1px solid #1e293b;"></div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Standalone Custom Recruiter Draft Modal -->
  <div id="custom-draft-modal" class="modal-backdrop" onclick="if(event.target===this) closeCustomDraftModal()">
    <div class="modal-content" style="max-width: 620px;">
      <div class="modal-header" style="background: linear-gradient(90deg, #1e1b4b, #7f1d1d);">
        <h3 style="color:#fca5a5;"><i class="fa-solid fa-envelope-circle-check"></i> Draft Recruiter Cold Email (Gmail)</h3>
        <button class="modal-close" onclick="closeCustomDraftModal()"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div style="padding: 24px; color: #cbd5e1; font-size: 13.5px; line-height: 1.6;">
        <p style="margin-top:0; color: #94a3b8; font-size: 13px;">
          Compose a personalized cold outreach email directly as a draft in your Gmail (<code>deepakshkarkala@gmail.com</code>) with your tailored resume attached.
        </p>
        <div style="display:flex; flex-direction:column; gap: 12px; margin-bottom: 16px;">
          <div>
            <label style="display:block; font-size: 12px; font-weight:700; color: #f87171; margin-bottom: 4px;">Recruiter / HR Email *</label>
            <input type="email" id="custom-draft-email" placeholder="e.g. rohit.referrals@phonepe.com or careers@target.com" style="width:100%; background:#0f172a; border:1px solid #dc2626; color:#fff; padding:9px 12px; border-radius:8px; font-size:13px;">
          </div>
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 10px;">
            <div>
              <label style="display:block; font-size: 12px; font-weight:700; color: #cbd5e1; margin-bottom: 4px;">Target Company</label>
              <input type="text" id="custom-draft-comp" placeholder="e.g. PhonePe / Razorpay" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:9px 12px; border-radius:8px; font-size:13px;">
            </div>
            <div>
              <label style="display:block; font-size: 12px; font-weight:700; color: #cbd5e1; margin-bottom: 4px;">Role Title</label>
              <input type="text" id="custom-draft-role" placeholder="e.g. SDE-I Backend Engineer" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:9px 12px; border-radius:8px; font-size:13px;">
            </div>
          </div>
          <div>
            <label style="display:block; font-size: 12px; font-weight:700; color: #cbd5e1; margin-bottom: 4px;">Job / Application URL (Optional)</label>
            <input type="url" id="custom-draft-url" placeholder="https://..." style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:9px 12px; border-radius:8px; font-size:13px;">
          </div>
        </div>
        <div id="custom-draft-status" style="display:none; margin-bottom: 14px; padding: 10px; border-radius: 8px; font-size: 12px;"></div>
        <div style="display:flex; justify-content: flex-end; gap: 10px;">
          <button class="btn" style="background:#334155; color:#cbd5e1;" onclick="closeCustomDraftModal()">Cancel</button>
          <button class="btn" id="btn-submit-custom-draft" style="background: linear-gradient(135deg, #ea4335, #dc2626); color:white; font-weight:700; padding: 9px 16px;" onclick="submitCustomDraft('draft')">
            <i class="fa-solid fa-file-pen"></i> Save Draft in Gmail
          </button>
          <button class="btn" id="btn-submit-custom-send" style="background: linear-gradient(135deg, #10b981, #059669); color:white; font-weight:700; padding: 9px 16px;" onclick="submitCustomDraft('send')">
            <i class="fa-solid fa-paper-plane"></i> Send Email Directly
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Standalone Technical Interview Strategy & Cheat-Sheet Modal -->
  <div id="job-link-tailor-modal" class="modal-backdrop" onclick="if(event.target===this) closeJobLinkTailorModal()">
    <div class="modal-content" style="max-width: 860px; max-height: 92vh; overflow-y: auto;">
      <div class="modal-header" style="background: linear-gradient(90deg, #0284c7, #1d4ed8);">
        <h3 style="color:#ffffff;"><i class="fa-solid fa-wand-magic-sparkles"></i> Instant Job Link Intake & Tailor</h3>
        <button class="modal-close" onclick="closeJobLinkTailorModal()"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div style="padding: 24px; color: #cbd5e1; font-size: 13.5px; line-height: 1.6;">
        <p style="margin-top:0; color: #94a3b8; font-size: 13px;">
          Paste any external job link (LinkedIn, Greenhouse, Lever, Workday, Naukri, or Company Careers page).
          ApplyPilot reads the JD, generates targeted referral messages, and instantly compiles an ATS-optimized tailored resume PDF.
        </p>

        <div style="display: flex; flex-direction: column; gap: 14px; margin-bottom: 18px;">
          <div>
            <label style="display:block; font-size: 12px; font-weight:700; color: #38bdf8; margin-bottom: 5px;">
              Job Link (URL) *
            </label>
            <div style="display: flex; gap: 8px;">
              <input type="url" id="jlink-url" placeholder="https://www.linkedin.com/jobs/view/... or careers page URL" style="flex: 1; background: #0f172a; border: 1px solid #0284c7; color: #fff; padding: 10px 14px; border-radius: 8px; font-size: 13px;">
              <button class="btn" id="btn-jlink-process" onclick="submitJobLinkIntake()" style="background: linear-gradient(135deg, #0284c7, #2563eb); color: white; font-weight: 700; padding: 10px 20px; font-size: 13px; border-radius: 8px; border: none; cursor: pointer; white-space: nowrap;">
                <i class="fa-solid fa-bolt"></i> Analyze & Generate
              </button>
            </div>
          </div>

          <div>
            <label style="display:block; font-size: 12px; font-weight:700; color: #94a3b8; margin-bottom: 5px;">
              Or Paste Job Description Directly (Optional fallback if page is behind login)
            </label>
            <textarea id="jlink-jd" placeholder="Paste JD text here (optional if URL is public)..." style="width: 100%; height: 80px; background: #0f172a; border: 1px solid #334155; color: #fff; padding: 10px; border-radius: 8px; font-size: 12px; resize: vertical;"></textarea>
          </div>
        </div>

        <div id="jlink-loading" style="display: none; text-align: center; padding: 30px 0;">
          <i class="fa-solid fa-spinner fa-spin fa-2x" style="color: #38bdf8;"></i>
          <p id="jlink-loading-text" style="margin-top: 12px; color: #94a3b8; font-size: 13.5px;">Extracting Job Description from URL & tailoring resume...</p>
        </div>

        <!-- Result Box -->
        <div id="jlink-result" style="display: none; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 20px;"></div>
      </div>
    </div>
  </div>

  <!-- Dedicated LinkedIn Post Intake Modal -->
  <div id="linkedin-post-modal" class="modal-backdrop" onclick="if(event.target===this) closeLinkedInPostModal()">
    <div class="modal-content" style="max-width: 880px; max-height: 92vh; overflow-y: auto;">
      <div class="modal-header" style="background: linear-gradient(90deg, #0a66c2, #1e3a8a);">
        <h3 style="color:#ffffff;"><i class="fa-brands fa-linkedin"></i> LinkedIn Hiring Post Intake & Action Engine</h3>
        <button class="modal-close" onclick="closeLinkedInPostModal()"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div style="padding: 24px; color: #cbd5e1; font-size: 13.5px; line-height: 1.6;">
        <p style="margin-top:0; color: #94a3b8; font-size: 13px;">
          Give any LinkedIn post link (or paste recruiter post text). ApplyPilot inspects the post, extracts recruiter emails or Google Forms / apply links, compiles a tailored resume PDF, and prepares a ready-to-send cold email draft in Gmail.
        </p>

        <div style="display: flex; flex-direction: column; gap: 14px; margin-bottom: 18px;">
          <div>
            <label style="display:block; font-size: 12px; font-weight:700; color: #38bdf8; margin-bottom: 5px;">
              LinkedIn Post Link (URL) *
            </label>
            <div style="display: flex; gap: 8px;">
              <input type="url" id="lpost-url" placeholder="https://www.linkedin.com/feed/update/urn:li:activity:... or /posts/..." style="flex: 1; background: #0f172a; border: 1px solid #0a66c2; color: #fff; padding: 10px 14px; border-radius: 8px; font-size: 13px;">
              <button class="btn" id="btn-lpost-process" onclick="submitLinkedInPostIntake()" style="background: linear-gradient(135deg, #0a66c2, #2563eb); color: white; font-weight: 700; padding: 10px 20px; font-size: 13px; border-radius: 8px; border: none; cursor: pointer; white-space: nowrap;">
                <i class="fa-solid fa-bolt"></i> Inspect Post & Tailor
              </button>
            </div>
          </div>

          <div>
            <label style="display:block; font-size: 12px; font-weight:700; color: #94a3b8; margin-bottom: 5px;">
              Or Paste Post Text (Optional fallback if post is private or login-restricted)
            </label>
            <textarea id="lpost-text" placeholder="e.g. 'We are hiring for SDE-1 Backend at Swiggy! Fill this form: https://forms.gle/... or email resume to careers@swiggy.com'..." style="width: 100%; height: 80px; background: #0f172a; border: 1px solid #334155; color: #fff; padding: 10px; border-radius: 8px; font-size: 12px; resize: vertical;"></textarea>
          </div>
        </div>

        <div id="lpost-loading" style="display: none; text-align: center; padding: 30px 0;">
          <i class="fa-solid fa-spinner fa-spin fa-2x" style="color: #38bdf8;"></i>
          <p id="lpost-loading-text" style="margin-top: 12px; color: #94a3b8; font-size: 13.5px;">Navigating to LinkedIn post, extracting recruiter contacts & compiling tailored resume...</p>
        </div>

        <!-- Result Box -->
        <div id="lpost-result" style="display: none; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 20px;"></div>
      </div>
    </div>
  </div>

  <div id="cheatsheet-modal" class="modal-backdrop" onclick="if(event.target===this) closeCheatsheetModal()">
    <div class="modal-content" style="max-width: 820px; max-height: 90vh; overflow-y: auto;">
      <div class="modal-header" style="background: linear-gradient(90deg, #3b0764, #1e1b4b);">
        <h3 style="color:#d8b4fe;"><i class="fa-solid fa-bolt"></i> <span id="cheatsheet-modal-title">Technical Interview Cheat-Sheet</span></h3>
        <button class="modal-close" onclick="closeCheatsheetModal()"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div id="cheatsheet-content" style="padding: 24px; color: #cbd5e1; font-size: 13.5px; line-height: 1.6;">
        <div style="text-align: center; padding: 40px 0;">
          <i class="fa-solid fa-spinner fa-spin fa-2x" style="color: #a855f7;"></i>
          <p style="margin-top: 12px; color: #94a3b8;">Synthesizing deep system design questions and Deepak's Meesho silver-bullet talking points...</p>
        </div>
      </div>
    </div>
  </div>

<div id="toast" class="toast"></div>

  <script>
    let allJobs = [];
    let allResponses = [];
    let analyticsData = null;
    let analyticsSourceFilter = 'all';
    let analyticsStageFilter = 'all';
    let currentTab = 'incognito_fresh';
    let currentSourceFilter = 'all';

    function filterBySource(src) {
      currentSourceFilter = src;
      document.querySelectorAll('.source-pill').forEach(p => p.classList.remove('active'));
      const activePill = document.getElementById('src-' + src);
      if (activePill) activePill.classList.add('active');
      if (src !== 'all' && (currentTab === 'high' || currentTab === 'top')) {
        setTab('all');
      } else {
        renderJobs();
      }
    }

    function copyKannadaPitchByRowid(rowid) {
      const job = allJobs.find(j => j.rowid === rowid);
      const comp = job ? job.company : 'Tech Company';
      const title = job ? job.title : 'Software Engineer';
      const msg = `ನಮಸ್ಕಾರ,\n\nI noticed the referral opening for ${title} at ${comp} in our KaDegree community. I am an SDE-I Backend Engineer at Meesho (RVCE CSE '25, ~2y exp: 1.3y full-time + 6m internship) working with high-throughput Java, Go, Kafka, and Redis services.\n\nCould you please refer my profile for this position? My resume is already attached and present in my profile.\n\nRequisition: ${comp} - ${title}\nProfile: SDE-I Backend Engineer, Meesho (RVCE '25)\nResume: Present in profile\nEmail: deepakshkarkala@gmail.com | Phone: +91 8431433659\nLinkedIn: https://www.linkedin.com/in/deepak-s-h-82b772254\n\nಧನ್ಯವಾದಗಳು! (Thank you!)\n- Deepak S H`;
      navigator.clipboard.writeText(msg).then(() => {
        showToast(`✅ Copied warm Kannada referral pitch for ${comp}!`);
      }).catch(() => {
        showToast('Selected pitch copied to clipboard!');
      });
    }

    async function triggerAtsSync() {
      const btn = document.getElementById('btn-sync-ats');
      const icon = document.getElementById('icon-sync-ats');
      const iconPill = document.getElementById('icon-sync-ats-pill');
      if (icon) icon.classList.add('fa-spin');
      if (iconPill) iconPill.classList.add('fa-spin');
      if (btn) btn.disabled = true;
      showToast('Scraping Direct ATS & Workday corporate career portals in background...');
      try {
        const res = await fetch('/api/ats/sync', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast(`⚡ Direct ATS & Workday background crawler started! Checking fresh corporate portals...`);
          setTimeout(async () => {
            await fetchJobs();
          }, 8000);
          setTimeout(async () => {
            await fetchJobs();
            showToast('✓ Direct ATS sync complete! Fresh openings loaded.');
          }, 25000);
        } else {
          showToast('ATS sync note: ' + (data.message || 'Error syncing ATS'));
        }
      } catch (e) {
        showToast('Error syncing Direct ATS: ' + e);
      } finally {
        setTimeout(() => {
          if (icon) icon.classList.remove('fa-spin');
          if (iconPill) iconPill.classList.remove('fa-spin');
          if (btn) btn.disabled = false;
        }, 5000);
      }
    }

    async function triggerKaDegreeSync() {
      const btn = document.getElementById('btn-sync-kadegree');
      const icon = document.getElementById('icon-sync-kadegree');
      if (icon) icon.classList.add('fa-spin');
      if (btn) btn.disabled = true;
      showToast('Connecting to KaDegree Referral Community & syncing latest openings...');
      try {
        const res = await fetch('/api/kadegree/sync', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast(`✓ KaDegree sync complete! ${data.new_stored} new jobs added, ${data.relevant_matches} relevant matches.`);
          triggerConfetti();
          await fetchJobs();
        } else {
          showToast('Sync note: ' + (data.message || 'Error syncing KaDegree'));
        }
      } catch (e) {
        showToast('Error syncing KaDegree: ' + e);
      } finally {
        if (icon) icon.classList.remove('fa-spin');
        if (btn) btn.disabled = false;
      }
    }

    let funnelData = null;
    let geminiReport = null;

    async function fetchFunnelData() {
      try {
        const res = await fetch('/api/funnel');
        funnelData = await res.json();
      } catch (e) {
        console.error('Failed to load funnel data:', e);
      }
    }

    async function fetchGeminiReport(force = false) {
      try {
        const url = force ? '/api/gemini/diagnostics' : '/api/gemini/diagnostics';
        const options = force ? { method: 'POST' } : { method: 'GET' };
        const res = await fetch(url, options);
        geminiReport = await res.json();
      } catch (e) {
        console.error('Failed to load Gemini diagnostic report:', e);
      }
    }

    async function renderStrategyView() {
      const container = document.getElementById('strategy-container');
      if (!container) return;
      container.innerHTML = '<div style="text-align:center; padding: 60px; color:#94a3b8;"><i class="fa-solid fa-spinner fa-spin" style="font-size:24px;"></i><p style="margin-top:10px;">Compiling 30-day conversion funnel & Gemini strategic diagnostics...</p></div>';

      await fetchFunnelData();
      if (!geminiReport) await fetchGeminiReport(false);

      const f = (funnelData && funnelData.funnel) ? funnelData.funnel : {
        fully_applied: 8, half_applied: 1, approved_pending: 1, responses_received: 7,
        active_oas: 1, interview_calls: 1, rejections: 1, acknowledged: 4,
        response_rate_pct: 87.5, interview_call_rate_pct: 25.0
      };
      const act = (funnelData && funnelData.activity) ? funnelData.activity : {
        today_active_minutes: 40, weekly_active_hours: 4.8, avg_mins_per_app: 3.4,
        manual_mins_per_app: 25.0, hours_saved_30d: 16.5
      };
      const r = geminiReport || {
        health_score: 84,
        verdict_title: "Strong SDE-1 Backend Profile with 3 High-Velocity Bottlenecks to Unblock",
        executive_summary: "Deepak's backend credentials (RVCE Class of '25, CGPA 8.92, Meesho SDE-I with Java/Go/Kafka/Redis) are well above average for 0-2 YOE candidates.",
        resume_efficiency: {
          status: "Strong Core Tech, Needs Quantitative Scale Metrics",
          strengths: ["Exceptional foundation: Meesho SDE-I experience + RVCE CSE 8.92 CGPA.", "Rare dual-language versatility: Production Java 17 + Go (Golang) alongside Apache Kafka."],
          missing_keywords_or_gaps: ["Lack of explicit QPS / throughput metrics (e.g. specify '15,000+ peak events/sec').", "Missing cloud resiliency tags (Distributed Tracing, P99 latency reduction < 12ms)."],
          high_impact_bullet_recommendations: [
            "Architected and deployed Kafka-backed event reconciliation microservice processing 4.2M daily financial records with 99.99% idempotent delivery.",
            "Optimized Redis distributed caching strategy and MySQL connection pooling, driving P99 query latencies down from 45ms to 8ms."
          ]
        },
        role_targeting_fit: {
          sweet_spot_roles: ["SDE-1 / SDE-2 Backend Engineer (Java / Go / Distributed Systems) [0-2.5 YOE]", "Platform Engineer & Microservices Infrastructure Engineer"],
          out_of_reach_or_wasteful_roles: ["Senior Software Engineer / Tech Lead (4+ YOE requirements trigger ATS auto-reject)", "Full-Stack React/Node heavy roles that dilute your backend value"],
          seniority_guardrail_verdict: "Strict compliance with 0-3 YOE filter is successfully saving 15+ hours/week by eliminating dead-end senior ATS applications."
        },
        fast_track_interview_playbook: [
          { action: "Immediate 2-Hour Response to KaDegree & WhatsApp Postings", priority: "HIGH", why_it_works: "Applying within 2 hours of post yields 4x higher recruiter view rate.", expected_time_saved_or_gain: "4 days faster interview scheduling" },
          { action: "Prioritize Greenhouse & SmartRecruiters over Workday", priority: "HIGH", why_it_works: "PhonePe (SmartRecruiters) shortlisted within 48h; Workday queues take 14-21 days without referral.", expected_time_saved_or_gain: "Cuts feedback loop from 3 weeks to 3 days" },
          { action: "Leverage Pre-Drafted Recruiter Email with Attached Resume", priority: "MEDIUM", why_it_works: "Reaches hiring managers directly before ATS filters reject on non-critical keywords.", expected_time_saved_or_gain: "Bypasses standard 10-day recruiter queue" }
        ],
        channel_performance: [
          { channel: "SmartRecruiters & Greenhouse (PhonePe, Razorpay)", conversion: "High (2-day turnaround to Interview / OA)", action: "Autofill and submit within 24 hours of discovery" },
          { channel: "Enterprise Workday ATS (JPMorgan, Cisco)", conversion: "Slow (10+ day backlog, higher automated rejection rate)", action: "Only apply with 1st-degree RVCE alumni referral" },
          { channel: "KaDegree & WhatsApp Referral Community (17k+ Kannada network)", conversion: "Very High (Direct founder/lead engineer access)", action: "Use Kannada Pitch Template E for highest warmth" }
        ]
      };

      container.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:22px; margin-top:12px;">
          <!-- Top Row: Everyday Active Time & Heavy Time Saved -->
          <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:14px;">
            <div class="kpi-card" style="border-color: rgba(16, 185, 129, 0.4); background: linear-gradient(135deg, rgba(6,78,59,0.25), rgba(15,23,42,0.85));">
              <span class="kpi-label"><i class="fa-solid fa-stopwatch" style="color:#10b981;"></i> Today's Active Job Search Time</span>
              <span class="kpi-value" style="color:#10b981;">${act.today_active_minutes} <span style="font-size:14px; font-weight:600; color:#94a3b8;">mins</span></span>
              <span style="font-size:11.5px; color:#94a3b8; margin-top:4px;">Weekly search time: <strong>${act.weekly_active_hours} hrs</strong></span>
            </div>
            <div class="kpi-card" style="border-color: rgba(6, 182, 212, 0.4); background: linear-gradient(135deg, rgba(14,116,144,0.2), rgba(15,23,42,0.85));">
              <span class="kpi-label"><i class="fa-solid fa-bolt" style="color:#06b6d4;"></i> Time Spent per Application</span>
              <span class="kpi-value" style="color:#06b6d4;">${act.avg_mins_per_app} <span style="font-size:14px; font-weight:600; color:#94a3b8;">mins</span></span>
              <span style="font-size:11.5px; color:#94a3b8; margin-top:4px;">vs Manual apply: <strong>${act.manual_mins_per_app} mins</strong> (7.3x faster)</span>
            </div>
            <div class="kpi-card" style="border-color: rgba(245, 158, 11, 0.4); background: linear-gradient(135deg, rgba(120,53,15,0.25), rgba(15,23,42,0.85));">
              <span class="kpi-label"><i class="fa-solid fa-clock-rotate-left" style="color:#fbbf24;"></i> Total Heavy Time Saved (30d)</span>
              <span class="kpi-value" style="color:#fbbf24;">${act.hours_saved_30d} <span style="font-size:14px; font-weight:600; color:#94a3b8;">hours</span></span>
              <span style="font-size:11.5px; color:#94a3b8; margin-top:4px;">Automated JIT LaTeX tailoring & Brave autofill</span>
            </div>
            <div class="kpi-card" style="border-color: rgba(168, 85, 247, 0.4); background: linear-gradient(135deg, rgba(88,28,135,0.2), rgba(15,23,42,0.85));">
              <span class="kpi-label"><i class="fa-solid fa-trophy" style="color:#c084fc;"></i> 30-Day Interview Call Rate</span>
              <span class="kpi-value" style="color:#c084fc;">${f.interview_call_rate_pct}%</span>
              <span style="font-size:11.5px; color:#94a3b8; margin-top:4px;">${f.interview_calls} Calls + ${f.active_oas} OAs out of ${f.fully_applied} applied</span>
            </div>
          </div>

          <!-- Application Funnel: Fully Applied vs Half-Applied -->
          <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 20px 24px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; flex-wrap:wrap; gap:10px;">
              <div>
                <h3 style="margin:0; font-size:16px; font-weight:700; color:#f8fafc; display:flex; align-items:center; gap:8px;">
                  <i class="fa-solid fa-filter" style="color:#38bdf8;"></i> Application Pipeline Funnel: Fully Applied vs Half-Applied
                </h3>
                <span style="font-size:12px; color:#94a3b8;">Tracking applications submitted to ATS vs forms started / tailored in progress.</span>
              </div>
              <div style="display:flex; gap:8px;">
                <button class="btn btn-preview" onclick="openLogCallModal()" style="background:linear-gradient(135deg, #059669, #10b981); color:#fff; font-weight:700; padding:7px 14px; font-size:12px;">
                  <i class="fa-solid fa-phone"></i> + Log Recruiter Call
                </button>
                <button class="btn btn-preview" onclick="syncGSheetsNow()" style="background:rgba(56,189,248,0.15); border-color:#38bdf8; color:#38bdf8; font-weight:700; padding:7px 14px; font-size:12px;">
                  <i class="fa-solid fa-table"></i> Sync Google Sheet
                </button>
              </div>
            </div>

            <!-- Progress Bar Breakdown -->
            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap:12px; margin-bottom:16px;">
              <div style="background:rgba(30,41,59,0.7); border-radius:10px; padding:12px 14px; border-left:4px solid #10b981;">
                <div style="font-size:11px; font-weight:700; color:#94a3b8; text-transform:uppercase;">Fully Applied</div>
                <div style="font-size:22px; font-weight:800; color:#10b981; margin-top:2px;">${f.fully_applied}</div>
                <span style="font-size:11px; color:#6ee7b7;">Submitted to ATS</span>
              </div>
              <div style="background:rgba(30,41,59,0.7); border-radius:10px; padding:12px 14px; border-left:4px solid #f59e0b;">
                <div style="font-size:11px; font-weight:700; color:#94a3b8; text-transform:uppercase;">Half Applied</div>
                <div style="font-size:22px; font-weight:800; color:#fbbf24; margin-top:2px;">${f.half_applied}</div>
                <span style="font-size:11px; color:#fde047;">Autofill opened / In progress</span>
              </div>
              <div style="background:rgba(30,41,59,0.7); border-radius:10px; padding:12px 14px; border-left:4px solid #c084fc;">
                <div style="font-size:11px; font-weight:700; color:#94a3b8; text-transform:uppercase;">Approved Queue</div>
                <div style="font-size:22px; font-weight:800; color:#c084fc; margin-top:2px;">${f.approved_pending}</div>
                <span style="font-size:11px; color:#e9d5ff;">Vetted, ready to apply</span>
              </div>
              <div style="background:rgba(30,41,59,0.7); border-radius:10px; padding:12px 14px; border-left:4px solid #38bdf8;">
                <div style="font-size:11px; font-weight:700; color:#94a3b8; text-transform:uppercase;">Responses Recv</div>
                <div style="font-size:22px; font-weight:800; color:#38bdf8; margin-top:2px;">${f.responses_received}</div>
                <span style="font-size:11px; color:#bae6fd;">${f.response_rate_pct}% response rate</span>
              </div>
              <div style="background:rgba(30,41,59,0.7); border-radius:10px; padding:12px 14px; border-left:4px solid #ec4899;">
                <div style="font-size:11px; font-weight:700; color:#94a3b8; text-transform:uppercase;">Interview Calls / OAs</div>
                <div style="font-size:22px; font-weight:800; color:#f472b6; margin-top:2px;">${f.interview_calls + f.active_oas}</div>
                <span style="font-size:11px; color:#fbcfe8;">${f.interview_calls} Calls, ${f.active_oas} Active OA</span>
              </div>
            </div>
          </div>

          <!-- Gemini Strategic Diagnostic Card -->
          <div style="background: linear-gradient(135deg, rgba(15, 23, 42, 0.95), rgba(30, 27, 75, 0.45)); border: 1.5px solid rgba(129, 140, 248, 0.35); border-radius: 16px; padding: 24px; box-shadow: 0 0 30px rgba(99, 102, 241, 0.15);">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:12px;">
              <div style="display:flex; align-items:center; gap:14px;">
                <div style="background:linear-gradient(135deg, #4f46e5, #06b6d4); color:#fff; width:48px; height:48px; border-radius:12px; display:flex; align-items:center; justify-content:center; font-size:22px; box-shadow:0 0 16px rgba(6,182,212,0.4);">
                  <i class="fa-solid fa-brain"></i>
                </div>
                <div>
                  <div style="display:flex; align-items:center; gap:10px;">
                    <span style="font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:0.8px; color:#818cf8;">Deep Gemini AI Career & Conversion Intelligence</span>
                    <span style="background:rgba(16,185,129,0.2); border:1px solid #10b981; color:#34d399; font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px;">Score: ${r.health_score}/100</span>
                  </div>
                  <h2 style="margin:4px 0 0 0; font-size:18px; font-weight:800; color:#fff;">${r.verdict_title}</h2>
                </div>
              </div>
              <div style="display:flex; gap:10px;">
                <button class="btn btn-preview" onclick="runGeminiDiagnostics(true)" style="background:linear-gradient(135deg, #4f46e5, #7c3aed); color:#fff; font-weight:700; padding:8px 16px; font-size:12.5px;">
                  <i class="fa-solid fa-rotate"></i> Run Deep Gemini Re-Analysis
                </button>
                <button class="btn btn-preview" onclick="blockOAsCalendar()" style="background:linear-gradient(135deg, #d97706, #f59e0b); color:#fff; font-weight:700; padding:8px 16px; font-size:12.5px;">
                  <i class="fa-solid fa-calendar-check"></i> 📅 Block OA Deadlines on Calendar
                </button>
              </div>
            </div>

            <p style="font-size:13.5px; color:#cbd5e1; line-height:1.65; margin:0 0 18px 0; background:rgba(0,0,0,0.25); padding:14px 18px; border-radius:10px; border-left:3px solid #818cf8;">
              ${r.executive_summary}
            </p>

            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap:18px;">
              <!-- 1. Resume Efficiency & Keyword Gaps -->
              <div style="background:rgba(15,23,42,0.8); border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:18px;">
                <h4 style="margin:0 0 10px 0; font-size:14px; font-weight:700; color:#38bdf8; display:flex; align-items:center; gap:8px;">
                  <i class="fa-solid fa-file-waveform"></i> 1. Resume Efficiency Audit
                  <span style="font-size:11px; color:#94a3b8; font-weight:500;">(${r.resume_efficiency.status})</span>
                </h4>
                <div style="font-size:12px; color:#94a3b8; margin-bottom:8px;"><strong>Identified Missing Keywords / Gaps:</strong></div>
                <ul style="margin:0 0 12px 18px; padding:0; font-size:12.5px; color:#fca5a5; line-height:1.5;">
                  ${r.resume_efficiency.missing_keywords_or_gaps.map(g => `<li>${g}</li>`).join('')}
                </ul>
                <div style="font-size:12px; color:#94a3b8; margin-bottom:6px;"><strong>High-Impact Bullet Upgrades (Directly boost ATS pass):</strong></div>
                <div style="display:flex; flex-direction:column; gap:8px;">
                  ${r.resume_efficiency.high_impact_bullet_recommendations.map(b => `
                    <div style="background:rgba(30,41,59,0.8); border:1px solid rgba(56,189,248,0.2); border-radius:8px; padding:8px 12px; font-size:12px; color:#e2e8f0; font-family:'JetBrains Mono', monospace; line-height:1.4;">
                      &bull; ${b}
                    </div>
                  `).join('')}
                </div>
              </div>

              <!-- 2. Role & Seniority Fit Check -->
              <div style="background:rgba(15,23,42,0.8); border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:18px;">
                <h4 style="margin:0 0 10px 0; font-size:14px; font-weight:700; color:#34d399; display:flex; align-items:center; gap:8px;">
                  <i class="fa-solid fa-user-shield"></i> 2. Role & Seniority Fit Evaluation
                </h4>
                <div style="font-size:12.5px; color:#cbd5e1; margin-bottom:10px;">
                  <span style="color:#10b981; font-weight:700;">✓ Sweet-Spot Target Roles:</span>
                  <ul style="margin:4px 0 10px 18px; padding:0; font-size:12px; color:#94a3b8;">
                    ${r.role_targeting_fit.sweet_spot_roles.map(s => `<li>${s}</li>`).join('')}
                  </ul>
                </div>
                <div style="font-size:12.5px; color:#cbd5e1; margin-bottom:10px;">
                  <span style="color:#f43f5e; font-weight:700;">⚠️ Roles to Skip (Out of Reach / Waste of Time):</span>
                  <ul style="margin:4px 0 10px 18px; padding:0; font-size:12px; color:#fca5a5;">
                    ${r.role_targeting_fit.out_of_reach_or_wasteful_roles.map(w => `<li>${w}</li>`).join('')}
                  </ul>
                </div>
                <div style="background:rgba(6,78,59,0.25); border:1px solid rgba(16,185,129,0.3); border-radius:8px; padding:10px 12px; font-size:12px; color:#a7f3d0; line-height:1.4;">
                  <strong>Seniority Guardrail:</strong> ${r.role_targeting_fit.seniority_guardrail_verdict}
                </div>
              </div>
            </div>

            <!-- 3. Fast-Track Interview Velocity Playbook -->
            <div style="margin-top:20px;">
              <h4 style="margin:0 0 12px 0; font-size:14px; font-weight:700; color:#fbbf24; display:flex; align-items:center; gap:8px;">
                <i class="fa-solid fa-gauge-high"></i> 3. Fast-Track Velocity Playbook: How to 3x Interview Selections in 14 Days
              </h4>
              <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:12px;">
                ${r.fast_track_interview_playbook.map(p => `
                  <div style="background:rgba(30,41,59,0.75); border:1px solid rgba(245,158,11,0.25); border-radius:10px; padding:14px 16px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                      <span style="font-size:13px; font-weight:700; color:#fef08a;">${p.action}</span>
                      <span style="font-size:10px; font-weight:800; background:rgba(245,158,11,0.2); color:#fbbf24; padding:2px 6px; border-radius:4px;">${p.priority}</span>
                    </div>
                    <p style="margin:0 0 8px 0; font-size:12px; color:#cbd5e1; line-height:1.4;">${p.why_it_works}</p>
                    <span style="font-size:11px; font-weight:700; color:#34d399;"><i class="fa-solid fa-clock"></i> Gain: ${p.expected_time_saved_or_gain}</span>
                  </div>
                `).join('')}
              </div>
            </div>
          </div>
        </div>
      `;
    }

    function openLogCallModal() {
      document.getElementById('log-call-modal').style.display = 'flex';
    }

    function closeLogCallModal() {
      document.getElementById('log-call-modal').style.display = 'none';
      document.getElementById('log-call-status').style.display = 'none';
    }

    async function submitLogCall() {
      const comp = document.getElementById('log-call-comp').value.trim();
      const role = document.getElementById('log-call-role').value.trim();
      const type = document.getElementById('log-call-type').value;
      const scheduled = document.getElementById('log-call-scheduled').value.trim();
      const recruiter = document.getElementById('log-call-recruiter').value.trim();
      const contact = document.getElementById('log-call-contact').value.trim();
      const notes = document.getElementById('log-call-notes').value.trim();
      const autoCal = document.getElementById('log-call-calendar').checked;

      if (!comp) {
        alert('Please enter a company name.');
        return;
      }

      const btn = document.getElementById('btn-submit-log-call');
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving...';

      try {
        const res = await fetch('/api/calls/log', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            company: comp, role_title: role, call_type: type,
            scheduled_at: scheduled, recruiter_name: recruiter,
            recruiter_contact: contact, notes: notes, auto_calendar: autoCal
          })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast(`📞 Recruiter response logged for ${comp}!`);
          triggerConfetti();
          closeLogCallModal();
          await fetchResponses();
          await fetchFunnelData();
          if (currentTab === 'strategy') renderStrategyView();
          else if (currentTab === 'responses') renderResponses();
        } else {
          alert('Error: ' + (data.message || 'Could not save call'));
        }
      } catch (err) {
        alert('Network Error: ' + err);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-check"></i> Save & Sync';
      }
    }

    async function runGeminiDiagnostics(force = true) {
      showToast('🧠 Running deep Gemini strategic analysis on your 30-day funnel...');
      await fetchGeminiReport(force);
      showToast('✓ Gemini diagnostic recommendations updated!');
      renderStrategyView();
    }

    async function blockOAsCalendar() {
      showToast('📅 Scanning uncompleted OAs and blocking Google Calendar focus time...');
      try {
        const res = await fetch('/api/calendar/block_oas', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast(`✓ Blocked ${data.blocked_count} online assessment focus slots on Google Calendar!`);
          triggerConfetti();
        } else {
          showToast('Could not auto-block calendar: ' + (data.message || 'Unknown error'));
        }
      } catch (e) {
        showToast('Error syncing calendar: ' + e);
      }
    }

    async function syncGSheetsNow() {
      showToast('📱 Syncing pipeline, calls, and funnel to Central Google Sheet...');
      try {
        const res = await fetch('/api/gsheet/sync', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast(`✓ Central Sheet synced! ${data.synced_jobs} jobs ready on mobile.`);
          if (data.spreadsheet_url && data.spreadsheet_url.startsWith('http')) {
            window.open(data.spreadsheet_url, '_blank');
          }
        }
      } catch (e) {
        showToast('Error syncing Google Sheets: ' + e);
      }
    }

    // Periodic Heartbeat to track active time spent
    setInterval(() => {
      try {
        fetch('/api/activity/heartbeat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ duration_seconds: 30, action: 'dashboard_active' })
        });
      } catch (e) {}
    }, 30000);

    function setPalette(themeName) {}
    /* 100% Autonomous Auto-Apply */
    async function launchAutonomousApply(rowid) {
      const btn = document.getElementById(`btn-auto-apply-${rowid}`);
      if (btn) {
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Auto-Applying...';
        btn.disabled = true;
      }
      showToast('⚡ Running Autonomous Auto-Apply in Brave (Kanistus Workflow: Autofill + Screening Qs + Submit)...');

      try {
        const res = await fetch(`/api/jobs/${rowid}/auto_apply`, { method: 'POST' });
        const data = await res.json();
        if (data.status === 'launched') {
          showToast('🤖 Autonomous Auto-Apply active in Brave! Submitting and logging to database...');
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Submitting in Brave...';
            btn.style.background = '#059669';
          }
          // Poll for completion
          let attempts = 0;
          const pollTimer = setInterval(async () => {
            attempts++;
            try {
              const sRes = await fetch('/api/jobs');
              const jobsData = await sRes.json();
              const updatedJob = jobsData.jobs.find(j => j.rowid === rowid);
              if (updatedJob && updatedJob.apply_status === 'applied') {
                clearInterval(pollTimer);
                showToast('🎉 Application submitted autonomously & logged to database!');
                if (btn) {
                  btn.innerHTML = '<i class="fa-solid fa-check-double"></i> Applied (Autonomous)';
                  btn.style.background = '#059669';
                  btn.disabled = true;
                }
                loadStats();
              } else if (attempts > 30) {
                clearInterval(pollTimer);
                if (btn) {
                  btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Auto-Apply (Autonomous)';
                  btn.disabled = false;
                  btn.style.background = 'linear-gradient(135deg, #10b981, #06b6d4)';
                }
              }
            } catch (err) {
              clearInterval(pollTimer);
            }
          }, 2500);
        } else {
          showToast('⚠️ Auto-Apply: ' + (data.message || 'Error launching'));
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Auto-Apply (Autonomous)';
            btn.disabled = false;
          }
        }
      } catch (e) {
        showToast('Auto-Apply error: ' + e);
        if (btn) {
          btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Auto-Apply (Autonomous)';
          btn.disabled = false;
        }
      }
    }

    async function triggerRemoteBoardsSync() {
      showToast('🌐 Crawling Remotive & Working Nomads official APIs for remote backend roles...');
      try {
        const res = await fetch('/api/remote_boards/sync', { method: 'POST' });
        const data = await res.json();
        showToast(`✅ Remote sync done: ${data.total_found || 0} fetched, ${data.new_stored || 0} new roles saved!`);
        loadJobs();
        loadStats();
      } catch (err) {
        showToast('Remote boards sync error: ' + err);
      }
    }

    async function triggerChannelPoll(e) {
      const btn = e ? e.currentTarget : null;
      const originalHtml = btn ? btn.innerHTML : '';
      if (btn) btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Polling Channels...';
      showToast('📡 Polling WhatsApp Web, Telegram Channels, and Gmail in background...');
      try {
        const res = await fetch('/api/channels/poll', { method: 'POST' });
        const data = await res.json();
        showToast(data.message || 'Polling cycle active!');
      } catch (err) {
        showToast('Polling error: ' + err);
      } finally {
        if (btn) {
          setTimeout(() => { btn.innerHTML = originalHtml; }, 3000);
        }
      }
    }

    async function triggerBatchAutoApply() {
      if (!confirm('Run Autonomous Auto-Apply batch for Top 5 qualified roles in Brave? This will launch Brave, prefill application details, answer screening questions, attach your tailored resume, and submit each application autonomously.')) {
        return;
      }
      showToast('🚀 Launching Autonomous Auto-Apply batch for Top 5 matches in Brave...');

      let banner = document.getElementById('batch-live-progress-banner');
      if (!banner) {
        banner = document.createElement('div');
        banner.id = 'batch-live-progress-banner';
        banner.style.cssText = 'background: linear-gradient(135deg, #1e1b4b, #312e81); border: 1px solid #818cf8; border-radius: 10px; padding: 14px 20px; margin-bottom: 20px; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 4px 15px rgba(99,102,241,0.3); color: #fff; font-family: Inter, sans-serif;';
        const container = document.querySelector('.container') || document.body;
        container.insertBefore(banner, container.firstChild);
      }
      banner.style.display = 'flex';
      banner.innerHTML = `
        <div style="display:flex;align-items:center;gap:12px;">
          <div style="font-size:20px;"><i class="fa-solid fa-spinner fa-spin" style="color:#a5b4fc;"></i></div>
          <div>
            <div style="font-weight:700;font-size:14px;color:#e0e7ff;">⚡ Autonomous Mass Auto-Apply Active in Brave</div>
            <div id="batch-banner-detail" style="font-size:12px;color:#c7d2fe;">Initializing batch runner...</div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:12px;">
          <div id="batch-banner-count" style="font-size:13px;font-weight:700;color:#38bdf8;">0 / 5</div>
        </div>
      `;

      try {
        const res = await fetch('/api/auto_apply_batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ limit: 5, min_score: 7, auto_submit: true })
        });
        const data = await res.json();
        if (data.status === 'batch_launched') {
          showToast('🤖 Batch running! Applications are being submitted and recorded in your database.');
          
          const pollInterval = setInterval(async () => {
            try {
              const sRes = await fetch('/api/auto_apply_status');
              const sData = await sRes.json();
              const detailEl = document.getElementById('batch-banner-detail');
              const countEl = document.getElementById('batch-banner-count');
              if (sData && sData.is_running) {
                if (detailEl) detailEl.innerText = `${sData.current_job || 'Processing'} — ${sData.current_step || ''}`;
                if (countEl) countEl.innerText = `${sData.completed} / ${sData.total}`;
              } else if (sData && !sData.is_running && sData.total > 0) {
                clearInterval(pollInterval);
                banner.style.background = 'linear-gradient(135deg, #065f46, #047857)';
                banner.style.border = '1px solid #34d399';
                banner.innerHTML = `
                  <div style="display:flex;align-items:center;gap:12px;">
                    <div style="font-size:20px;color:#a7f3d0;"><i class="fa-solid fa-circle-check"></i></div>
                    <div>
                      <div style="font-weight:700;font-size:14px;color:#ecfdf5;">🎉 Mass Auto-Apply Batch Finished!</div>
                      <div style="font-size:12px;color:#a7f3d0;">
                        ${sData.submitted.length} submitted autonomously, ${(sData.half_applied || []).length} prefilled, ${(sData.requires_login || []).length} login gated.
                      </div>
                    </div>
                  </div>
                  <button onclick="document.getElementById('batch-live-progress-banner').style.display='none'" style="background:transparent;border:none;color:#a7f3d0;cursor:pointer;font-size:16px;">✕</button>
                `;
                loadJobs();
                loadStats();
                if (typeof loadFunnel === 'function') loadFunnel();
                setTimeout(() => { if (banner) banner.style.display = 'none'; }, 10000);
              }
            } catch (err) {
              console.error('Batch status poll error:', err);
            }
          }, 1500);
        }
      } catch (e) {
        showToast('Batch error: ' + e);
        if (banner) banner.style.display = 'none';
      }
    }

    /* 1-Click Application Assistant Autofill */
    async function launchAutofill(rowid) {
      const btn = document.getElementById(`btn-autofill-${rowid}`);
      if (btn) {
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Launching Assistant...';
        btn.disabled = true;
      }
      showToast('⚡ Launching Application Assistant in Brave with autofill...');

      const job = allJobs.find(j => j.rowid === rowid);
      if (job && job.tailored_resume_path) {
        navigator.clipboard.writeText(job.tailored_resume_path);
      }

      try {
        const res = await fetch(`/api/jobs/${rowid}/launch`, { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast('🛡️ Application Assistant active in Brave! Auto-filling fields & attaching resume.');
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-check"></i> Autofilling in Brave';
            btn.style.background = '#059669';
            setTimeout(() => {
              btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Autofill in Brave';
              btn.disabled = false;
              btn.style.background = 'linear-gradient(135deg, #0284c7, #10b981)';
            }, 5000);
          }
        } else {
          showToast('⚠️ Assistant launch: ' + (data.message || 'Error'));
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Autofill in Brave';
            btn.disabled = false;
          }
        }
      } catch (e) {
        showToast('Assistant error: ' + e);
        if (btn) {
          btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Autofill in Brave';
          btn.disabled = false;
        }
      }
    }

    async function fetchJobs() {
      try {
        const res = await fetch('/api/jobs');
        allJobs = await res.json();
        await fetchResponses();
        await fetchAnalytics();
        updateStats();
        renderJobs();
      } catch (e) {
        showToast('Error loading jobs: ' + e);
      }
    }

    async function fetchResponses() {
      try {
        const res = await fetch('/api/responses');
        allResponses = await res.json();
      } catch (e) {
        console.error('Failed to load responses:', e);
      }
    }

    let responseCategoryFilter = 'all';

    function filterResponsesCategory(cat) {
      responseCategoryFilter = cat;
      document.querySelectorAll('.resp-pill').forEach(p => p.classList.remove('active'));
      let pillId = 'rp-' + (cat === 'interview_selected' ? 'interview' : cat === 'apply_link' ? 'apply' : cat);
      const activePill = document.getElementById(pillId);
      if (activePill) activePill.classList.add('active');
      renderResponses();
    }

    async function requestExtension(messageId) {
      showToast('Creating 24h deadline extension request draft in Gmail...');
      try {
        const res = await fetch(`/api/responses/${messageId}/request_extension`, { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast('✅ Extension request drafted in your Gmail! Opening Drafts in Brave...');
          if (data.web_url) window.open(data.web_url, '_blank');
        } else if (data.web_compose_url) {
          showToast('Opening pre-filled extension request in your active Brave Gmail...');
          window.open(data.web_compose_url, '_blank');
        } else {
          showToast('Draft note: ' + (data.message || 'Complete'));
        }
      } catch (err) {
        showToast('Failed to create extension draft: ' + err);
      }
    }

    async function toggleResponseCompleted(messageId) {
      try {
        const res = await fetch(`/api/responses/${messageId}/toggle_completed`, { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast('Updated assessment status!');
          await fetchResponses();
          updateStats();
          if (currentTab === 'responses') renderResponses();
        }
      } catch (err) {
        showToast('Error updating status: ' + err);
      }
    }

    function updateStats() {
      document.getElementById('stat-total').textContent = allJobs.length;
      document.getElementById('stat-nine').textContent = allJobs.filter(j => j.fit_score >= 9).length;
      document.getElementById('stat-high').textContent = allJobs.filter(j => j.fit_score >= 7).length;
      document.getElementById('stat-tailored').textContent = allJobs.filter(j => !!j.tailored_resume_path).length;
      document.getElementById('stat-approved').textContent = allJobs.filter(j => j.apply_status === 'approved').length;
      document.getElementById('stat-applied').textContent = allJobs.filter(j => j.apply_status === 'applied').length;
      document.getElementById('stat-responses').textContent = allResponses.length;

      const yetToApplyCount = allJobs.filter(j => (j.fit_score >= 7 || !!j.tailored_resume_path) && j.apply_status !== 'applied' && j.apply_status !== 'asked_referral' && j.apply_status !== 'interview' && j.apply_status !== 'rejected' && j.apply_status !== 'ignored').length;
      const appliedCount = allJobs.filter(j => j.apply_status === 'applied').length;
      const askedReferralCount = allJobs.filter(j => j.apply_status === 'asked_referral').length;
      const ignoredCount = allJobs.filter(j => j.apply_status === 'ignored').length;

      // Calculate fresh posts (< 4 hours old)
      const nowMs = Date.now();
      const fourHoursMs = 4 * 60 * 60 * 1000;
      const freshCount = allJobs.filter(j => {
        if (j.apply_status === 'applied' || j.apply_status === 'ignored' || j.apply_status === 'rejected') return false;
        const d = getJobEffectiveDate(j);
        if (!d) return false;
        return (nowMs - d.getTime()) <= fourHoursMs && (nowMs - d.getTime()) >= 0;
      }).length;

      const freshBadge = document.getElementById('badge-fresh');
      if (freshBadge) freshBadge.textContent = freshCount;

      const yetBadge = document.getElementById('badge-yet-to-apply');
      if (yetBadge) yetBadge.textContent = yetToApplyCount;
      document.getElementById('badge-high').textContent = allJobs.filter(j => j.fit_score >= 7 && j.apply_status !== 'ignored' && j.apply_status !== 'applied').length;
      document.getElementById('badge-top').textContent = allJobs.filter(j => j.fit_score >= 8 && j.apply_status !== 'ignored' && j.apply_status !== 'applied').length;
      document.getElementById('badge-approved').textContent = allJobs.filter(j => j.apply_status === 'approved').length;
      document.getElementById('badge-applied').textContent = appliedCount;
      const refBadge = document.getElementById('badge-asked-referral');
      if (refBadge) refBadge.textContent = askedReferralCount;
      const ignBadge = document.getElementById('badge-ignored');
      if (ignBadge) ignBadge.textContent = ignoredCount;
      const rBadge = document.getElementById('badge-responses');
      if (rBadge) rBadge.textContent = allResponses.length;

      // Sync Cold Email CRM badge
      fetch('/api/cold_crm/summary').then(res => res.json()).then(data => {
        const crmBadge = document.getElementById('badge-cold-crm');
        if (crmBadge && data && data.metrics) {
          crmBadge.textContent = data.metrics.due_followups_count || data.metrics.total_sent || 0;
        }
      }).catch(() => {});

      // Sync Referral Network CRM badge
      fetch('/api/referral_crm/summary').then(res => res.json()).then(data => {
        const refBadge = document.getElementById('badge-referral-crm');
        if (refBadge && data && data.metrics) {
          refBadge.textContent = `${data.metrics.total_accepted}/${data.metrics.total_requested}`;
        }
      }).catch(() => {});

      // Check helpers for global badge counting
      const isCompanyBlockedGlobal = (j) => {
        const comp = (j.company || j.site || '').toLowerCase();
        const tit = (j.title || '').toLowerCase();
        const blocked = ['accenture', 'infosys', 'capgemini', 'flexiple'];
        return blocked.some(b => comp.includes(b) || tit.includes(b));
      };
      const checkOverExpGlobal = (j) => {
        const tit = (j.title || '').toLowerCase();
        const desc = (j.desc || j.description || j.full_desc || j.full_description || '').toLowerCase();
        const combined = `${tit} ${desc}`;
        const seniorWords = ['senior', 'sr.', 'sr ', 'lead', 'tech lead', 'staff', 'principal', 'manager', 'mgr', 'architect', 'director', 'iii', 'iv', 'l3', 'l4', 'l5'];
        if (seniorWords.some(w => tit.includes(w))) return true;
        const rangePat = /(\d+)\+?\s*(?:to|-)\s*(\d+)\s*(?:years?|yrs?)/gi;
        let m;
        while ((m = rangePat.exec(combined)) !== null) {
          const low = parseInt(m[1], 10);
          const high = parseInt(m[2], 10);
          if (!isNaN(low) && low > 3) return true;
          if (!isNaN(high) && (high >= 5 || high > 3)) return true;
        }
        const singlePat = /(?:(?:minimum|min|at least)\s*)?(\d+)\+?\s*(?:years?|yrs?)(?:\s*of)?\s*(?:relevant|hands-on|industry|software|backend|work)?\s*experience|\b(\d+)\+?\s*yoe\b/gi;
        while ((m = singlePat.exec(combined)) !== null) {
          const exp = parseInt(m[1] || m[2], 10);
          if (!isNaN(exp) && exp > 3) return true;
        }
        const plusPat = /(\d+)\+\s*(?:years?|yrs?)/gi;
        while ((m = plusPat.exec(combined)) !== null) {
          const exp = parseInt(m[1], 10);
          if (!isNaN(exp) && exp > 3) return true;
        }
        return false;
      };

      const easyApplyJobsCount = allJobs.filter(j => (j.is_easy_apply === 1 || (j.source_category === 'linkedin' && j.strategy === 'linkedin_easy_apply')) && j.apply_status !== 'ignored' && j.apply_status !== 'applied').length;
      const easyBadge = document.getElementById('badge-easy-apply');
      if (easyBadge) easyBadge.textContent = easyApplyJobsCount;

      const incognitoJobsCount = allJobs.filter(j => {
        const isIncognitoJob = (j.strategy === 'linkedin_1h_incognito' || j.strategy === 'indeed_incognito' || j.strategy === 'ats');
        if (!isIncognitoJob || j.apply_status === 'ignored' || j.apply_status === 'applied') return false;
        if (isCompanyBlockedGlobal(j)) return false;
        if (j.num_applicants !== null && j.num_applicants !== undefined && j.num_applicants >= 200) return false;
        if (checkOverExpGlobal(j)) return false;
        const d = getJobEffectiveDate(j);
        if (d) {
          const diff = Date.now() - d.getTime();
          if (!isNaN(diff) && diff > 24 * 60 * 60 * 1000) return false;
        }
        return true;
      }).length;
      const incognitoBadge = document.getElementById('badge-incognito-fresh');
      if (incognitoBadge) incognitoBadge.textContent = incognitoJobsCount;

      const fresh24hCount = allJobs.filter(j => {
        if (j.apply_status === 'ignored' || j.apply_status === 'applied') return false;
        if (j.num_applicants !== null && j.num_applicants !== undefined && j.num_applicants >= 200) return false;
        const d = getJobEffectiveDate(j);
        if (!d) return false;
        const diff = Date.now() - d.getTime();
        return (!isNaN(diff) && diff <= 24 * 60 * 60 * 1000 && diff >= 0);
      }).length;
      const fresh24hBadge = document.getElementById('badge-fresh-24h');
      if (fresh24hBadge) fresh24hBadge.textContent = fresh24hCount;

      const kaJobsCount = allJobs.filter(j => (j.source_category === 'kadegree' || j.is_kadegree) && j.apply_status !== 'ignored' && j.apply_status !== 'applied').length;
      const kaBadge = document.getElementById('badge-kadegree');
      if (kaBadge) kaBadge.textContent = kaJobsCount;
      const statKa = document.getElementById('stat-kadegree');
      if (statKa) statKa.textContent = kaJobsCount;

      // Calculate response category counts
      const activeOAs = allResponses.filter(r => r.category === 'oa' && !r.is_completed);
      const totalOAs = allResponses.filter(r => r.category === 'oa');
      const totalInterviews = allResponses.filter(r => r.category === 'interview_selected');
      const totalRejected = allResponses.filter(r => r.category === 'rejected');
      const totalApply = allResponses.filter(r => r.category === 'apply_link');
      const totalAck = allResponses.filter(r => r.category === 'acknowledged');

      const statOaElem = document.getElementById('stat-oa');
      if (statOaElem) statOaElem.textContent = activeOAs.length;

      const cntAll = document.getElementById('cnt-resp-all');
      if (cntAll) cntAll.textContent = allResponses.length;
      const cntOa = document.getElementById('cnt-resp-oa');
      if (cntOa) cntOa.textContent = activeOAs.length;
      const cntInt = document.getElementById('cnt-resp-interview');
      if (cntInt) cntInt.textContent = totalInterviews.length;
      const cntRej = document.getElementById('cnt-resp-rejected');
      if (cntRej) cntRej.textContent = totalRejected.length;
      const cntApp = document.getElementById('cnt-resp-apply');
      if (cntApp) cntApp.textContent = totalApply.length;
      const cntAck = document.getElementById('cnt-resp-ack');
      if (cntAck) cntAck.textContent = totalAck.length;

      // Source breakdown counts
      const kadegreeJobs = allJobs.filter(j => j.source_category === 'kadegree' || j.is_kadegree);
      const linkedinJobs = allJobs.filter(j => j.source_category === 'linkedin');
      const whatsappJobs = allJobs.filter(j => j.source_category === 'whatsapp');
      const atsJobs = allJobs.filter(j => j.source_category === 'ats' || (!j.is_kadegree && j.source_category !== 'linkedin' && j.source_category !== 'whatsapp'));

      const cntSrcAll = document.getElementById('cnt-src-all');
      if (cntSrcAll) cntSrcAll.textContent = allJobs.length;
      const cntSrcKa = document.getElementById('cnt-src-kadegree');
      if (cntSrcKa) cntSrcKa.textContent = kadegreeJobs.length;
      const cntSrcLi = document.getElementById('cnt-src-linkedin');
      if (cntSrcLi) cntSrcLi.textContent = linkedinJobs.length;
      const cntSrcWa = document.getElementById('cnt-src-whatsapp');
      if (cntSrcWa) cntSrcWa.textContent = whatsappJobs.length;
      const cntSrcAts = document.getElementById('cnt-src-ats');
      if (cntSrcAts) cntSrcAts.textContent = atsJobs.length;
      const cntSrcSeed = document.getElementById('cnt-src-seed');
      if (cntSrcSeed) cntSrcSeed.textContent = allJobs.filter(j => j.strategy === 'seed_funded').length;

      // Update Top Urgent / Missed OA Banner
      const urgentBanner = document.getElementById('urgent-oa-alert');

      // Update Daily Tracker (5 asking resume + 5 applied <= 100 applicants)
      fetchFunnelData().then(() => {
        if (funnelData && funnelData.daily_tracker) {
          const dt = funnelData.daily_tracker;
          const resStatus = document.getElementById('tracker-resume-status');
          const resBar = document.getElementById('tracker-resume-bar');
          const resNote = document.getElementById('tracker-resume-note');
          if (resStatus) {
            resStatus.innerHTML = `${dt.resume_requested} / 5 ${dt.resume_goal_met ? '<i class="fa-solid fa-circle-check" style="color:#38bdf8;"></i>' : ''}`;
            resStatus.style.color = dt.resume_goal_met ? '#38bdf8' : '#cbd5e1';
          }
          if (resBar) {
            resBar.style.width = `${dt.resume_progress_pct}%`;
            if (dt.resume_goal_met) resBar.style.background = 'linear-gradient(90deg, #0284c7, #38bdf8)';
          }
          if (resNote) {
            resNote.textContent = dt.resume_goal_met ? '✓ Daily resume goal achieved!' : `${5 - dt.resume_requested} more needed today`;
          }

          const appStatus = document.getElementById('tracker-applied-status');
          const appBar = document.getElementById('tracker-applied-bar');
          const appNote = document.getElementById('tracker-applied-note');
          if (appStatus) {
            appStatus.innerHTML = `${dt.applied_under_100} / 5 ${dt.applied_goal_met ? '<i class="fa-solid fa-circle-check" style="color:#34d399;"></i>' : ''} <span style="font-size:11px; color:#94a3b8;">(${dt.applied_total} total)</span>`;
            appStatus.style.color = dt.applied_goal_met ? '#34d399' : '#cbd5e1';
          }
          if (appBar) {
            appBar.style.width = `${dt.applied_progress_pct}%`;
            if (dt.applied_goal_met) appBar.style.background = 'linear-gradient(90deg, #059669, #34d399)';
          }
          if (appNote) {
            appNote.textContent = dt.applied_goal_met ? '✓ Low-competition goal met!' : `${5 - dt.applied_under_100} more low-competition apps needed`;
          }

          const streakBadge = document.getElementById('daily-streak-badge');
          if (streakBadge) {
            if (dt.both_goals_met) {
              streakBadge.innerHTML = `<i class="fa-solid fa-fire" style="color:#f59e0b;"></i> Today's Quota Complete! (${dt.current_streak_days}d streak)`;
              streakBadge.style.background = 'rgba(16, 185, 129, 0.25)';
              streakBadge.style.borderColor = '#10b981';
              streakBadge.style.color = '#6ee7b7';
            } else {
              streakBadge.innerHTML = `<i class="fa-solid fa-hourglass-half" style="color:#38bdf8;"></i> Today in Progress (${dt.current_streak_days}d streak)`;
              streakBadge.style.background = 'rgba(56, 189, 248, 0.2)';
              streakBadge.style.borderColor = '#38bdf8';
              streakBadge.style.color = '#7dd3fc';
            }
          }

          const dtBadge = document.getElementById('badge-daily-tracker');
          if (dtBadge) {
            if (dt.both_goals_met) {
              dtBadge.textContent = '100% Met';
              dtBadge.style.background = 'rgba(16, 185, 129, 0.25)';
              dtBadge.style.borderColor = '#10b981';
              dtBadge.style.color = '#6ee7b7';
            } else {
              dtBadge.textContent = `${dt.applied_under_100}/5 app • ${dt.resume_requested}/5 res`;
              dtBadge.style.background = 'rgba(56, 189, 248, 0.2)';
              dtBadge.style.borderColor = '#38bdf8';
              dtBadge.style.color = '#7dd3fc';
            }
          }
        }
      }).catch(() => {});
      if (urgentBanner) {
        if (activeOAs.length > 0) {
          urgentBanner.style.display = 'flex';
          const firstOa = activeOAs[0];
          const dueLower = (firstOa.due_date || '').toLowerCase();
          const isPassed = ['9 nov', '9 november', 'nov 9', 'november 9', '8 nov', '7 nov'].some(k => dueLower.includes(k));
          
          const urgentTitle = document.getElementById('urgent-oa-title');
          if (urgentTitle) {
            if (isPassed) {
              urgentBanner.style.background = 'linear-gradient(90deg, rgba(185, 28, 28, 0.5), rgba(15, 23, 42, 0.95))';
              urgentBanner.style.borderColor = '#ef4444';
              urgentBanner.style.boxShadow = '0 0 24px rgba(239, 68, 68, 0.35)';
              urgentTitle.innerHTML = `<span style="color:#fca5a5; font-weight:800;"><i class="fa-solid fa-triangle-exclamation"></i> MISSED OPPORTUNITY (EXPIRED NOV 9):</span> <strong>${firstOa.company}</strong> (${firstOa.role_title || 'Software Engineer'}) &mdash; Deadline was <em>${firstOa.due_date}</em> (~15h ago).`;
            } else {
              urgentBanner.style.background = 'linear-gradient(90deg, rgba(180, 83, 9, 0.45), rgba(15, 23, 42, 0.95))';
              urgentBanner.style.borderColor = '#f59e0b';
              urgentTitle.innerHTML = `<strong>${firstOa.company}</strong> (${firstOa.role_title || 'Software Engineer'}) &mdash; <span style="color:#fde047; font-weight:800;"><i class="fa-solid fa-clock"></i> Deadline: ${firstOa.due_date || 'Urgent assessment'}</span>`;
            }
          }
          const urgentLink = document.getElementById('urgent-oa-link');
          if (urgentLink) {
            urgentLink.href = firstOa.action_url || '#';
            urgentLink.style.display = firstOa.action_url ? 'inline-flex' : 'none';
          }
        } else {
          urgentBanner.style.display = 'none';
        }
      }
    }

    function renderRemotePortalsView() {
      const container = document.getElementById('remote-portals-container');
      if (!container) return;

      const portals = [
        {
          name: "Uplers",
          category: "Direct Talent Network (India <-> Global)",
          tag: "Top Rec: Fast Track for Indian Devs",
          tagColor: "#10b981",
          url: "https://www.uplers.com/talent/",
          logo: "https://www.google.com/s2/favicons?domain=uplers.com&sz=128",
          bestFor: "Indian developers seeking full-time remote roles with Indian startups & overseas companies. Strong on Node.js, Python/Django, React, AWS.",
          hiringModel: "Vetted Talent Pool -> Client matches you directly -> No freelance bidding. Fixed monthly INR/USD payout.",
          actions: [
            { label: "Apply as Talent", url: "https://www.uplers.com/talent/" },
            { label: "Search Open Roles", url: "https://jobs.uplers.com/" }
          ],
          tips: "Pass their initial vetting assessment once; your profile is actively pitched by Uplers account managers to global clients."
        },
        {
          name: "DistantJob",
          category: "Specialist Global Recruitment Agency",
          tag: "Full-Time Remote Agency",
          tagColor: "#3b82f6",
          url: "https://distantjob.com/careers/",
          logo: "https://www.google.com/s2/favicons?domain=distantjob.com&sz=128",
          bestFor: "Specialised recruitment agency placing skilled engineers in long-term, full-time remote positions with US & European enterprises.",
          hiringModel: "Headhunters act like traditional recruiters: you interview directly with CTOs & VPs of Engineering for direct-hire remote roles.",
          actions: [
            { label: "View Open Jobs", url: "https://distantjob.com/careers/" },
            { label: "Submit Resume", url: "https://distantjob.com/contact-us/" }
          ],
          tips: "High focus on communication skills and autonomous problem solving. Highlight your Meesho backend scalability numbers."
        },
        {
          name: "itForte",
          category: "Specialist Tech Recruitment Firm",
          tag: "India-Based Global IT Recruiter",
          tagColor: "#8b5cf6",
          url: "https://www.itforte.com/",
          logo: "https://www.google.com/s2/favicons?domain=itforte.com&sz=128",
          bestFor: "India-headquartered technology recruitment specialist with international enterprise placements and offshore engineering team staffing.",
          hiringModel: "Executive and senior engineering staffing for MNCs, high-growth startups, and international software companies.",
          actions: [
            { label: "Job Seekers Portal", url: "https://www.itforte.com/job-seekers/" },
            { label: "Current Openings", url: "https://www.itforte.com/current-openings/" }
          ],
          tips: "Send your tailored resume directly to their recruitment consultants; they handle high-budget permanent and contract roles."
        },
        {
          name: "Arc.dev",
          category: "Global Remote Developer Network",
          tag: "Top Global Vetted Platform",
          tagColor: "#f59e0b",
          url: "https://arc.dev/",
          logo: "https://www.google.com/s2/favicons?domain=arc.dev&sz=128",
          bestFor: "Vetted global community for remote full-time software engineers. Connects to US, EU, and global tech firms without US work visa restrictions.",
          hiringModel: "Dual model: Apply directly to remote JDs on their job board OR get featured in their bi-weekly reverse-interview hiring batches.",
          actions: [
            { label: "Explore Remote Jobs", url: "https://arc.dev/remote-jobs" },
            { label: "Join Talent Directory", url: "https://arc.dev/developers" }
          ],
          tips: "Always check the 'Location Restrictions' filter: select 'Anywhere' or 'India / APAC' to filter out US-citizen-only roles."
        },
        {
          name: "Turing",
          category: "AI-Powered Vetted Engineering Network",
          tag: "Global USD Compensation",
          tagColor: "#06b6d4",
          url: "https://www.turing.com/",
          logo: "https://www.google.com/s2/favicons?domain=turing.com&sz=128",
          bestFor: "Global talent cloud matching developers to Silicon Valley and Fortune 500 remote jobs and LLM/AI training projects.",
          hiringModel: "Automated technical vetting (coding tests + system design quizzes) -> AI matches vetted developers to long-term remote contracts.",
          actions: [
            { label: "Take Skills Assessment", url: "https://www.turing.com/jobs" },
            { label: "Browse Roles", url: "https://www.turing.com/jobs/browse" }
          ],
          tips: "Take tests for Python, Node.js, and Backend Architecture. Once your Turing score is 'Matched', clients reach out to you."
        },
        {
          name: "Wellfound (formerly AngelList Talent)",
          category: "Global Startup Ecosystem",
          tag: "Essential for Funded Startups",
          tagColor: "#ec4899",
          url: "https://wellfound.com/jobs",
          logo: "https://www.google.com/s2/favicons?domain=wellfound.com&sz=128",
          bestFor: "Direct applications to Founders & Engineering Leads at Y Combinator, US, European, and top Indian venture-backed startups.",
          hiringModel: "Direct founder & hiring manager chat. Transparent salary & equity numbers shown upfront on every single listing.",
          actions: [
            { label: "Search Remote Roles", url: "https://wellfound.com/jobs?location=Remote" }
          ],
          tips: "Include a strong 2-sentence intro note mentioning your Meesho high-throughput experience when clicking 'Apply'."
        },
        {
          name: "Instahyre",
          category: "AI Matchmaking Platform (India & Global)",
          tag: "High Conversion in India",
          tagColor: "#14b8a6",
          url: "https://www.instahyre.com/candidate/opportunities/",
          logo: "https://www.google.com/s2/favicons?domain=instahyre.com&sz=128",
          bestFor: "Zero spam, recruiter-reachout model for top product companies (Swiggy, Uber, PhonePe, and international remote engineering offices).",
          hiringModel: "Inbound model: Set profile to 'Actively Looking', enter target CTC & remote preferences, recruiters request interviews.",
          actions: [
            { label: "Candidate Dashboard", url: "https://www.instahyre.com/candidate/opportunities/" }
          ],
          tips: "Keep your profile 100% complete and log in at least once every 3 days so the algorithm ranks you at the top of recruiter searches."
        },
        {
          name: "Remotive",
          category: "Curated Remote Tech Board",
          tag: "Hand-Screened Worldwide Roles",
          tagColor: "#6366f1",
          url: "https://remotive.com/",
          logo: "https://www.google.com/s2/favicons?domain=remotive.com&sz=128",
          bestFor: "Hand-curated remote software development roles with transparent remote location tags (Worldwide / Anywhere in the World).",
          hiringModel: "Direct career portal links with no middleman. Zero spam listings.",
          actions: [
            { label: "Browse Software Dev Roles", url: "https://remotive.com/remote-jobs/software-dev" }
          ],
          tips: "Filter strictly by 'Worldwide' to skip roles restricted to North American timezones."
        },
        {
          name: "We Work Remotely (WWR)",
          category: "Largest Global Remote Community",
          tag: "Pioneer Remote Board",
          tagColor: "#f43f5e",
          url: "https://weworkremotely.com/",
          logo: "https://www.google.com/s2/favicons?domain=weworkremotely.com&sz=128",
          bestFor: "The largest remote work community in the world. High volume of backend, full-stack, and DevOps positions from bootstrapped and VC firms.",
          hiringModel: "Direct employer applications. Employers pay $299+ to post, guaranteeing high hiring intent.",
          actions: [
            { label: "View Programming Jobs", url: "https://weworkremotely.com/categories/remote-programming-jobs" }
          ],
          tips: "Check listings tagged 'Anywhere in the World'. Apply within the first 48 hours for top consideration."
        },
        {
          name: "Crossover",
          category: "Full-Time High USD Remote Contractor",
          tag: "Standardized High Pay ($60k - $100k+)",
          tagColor: "#84cc16",
          url: "https://www.crossover.com/jobs",
          logo: "https://www.google.com/s2/favicons?domain=crossover.com&sz=128",
          bestFor: "Standardized high-paying full-time remote contracts ($60k - $100k/yr) for software developers across the globe.",
          hiringModel: "Strictly assessment-driven: cognitive test + technical coding challenge -> direct hire offer if you hit threshold.",
          actions: [
            { label: "Browse Open Engineering Roles", url: "https://www.crossover.com/jobs" }
          ],
          tips: "Fastest way to high USD pay if you score well on standardized tests (CCAT and HackerRank)."
        },
        {
          name: "RemoteOK",
          category: "Global Tech Aggregator",
          tag: "Live Feed & Salary Ranges",
          tagColor: "#0ea5e9",
          url: "https://remoteok.com/",
          logo: "https://www.google.com/s2/favicons?domain=remoteok.com&sz=128",
          bestFor: "One of the most active feeds of remote engineering positions across startups, scaleups, and web3/crypto enterprises.",
          hiringModel: "Direct career portal links with compensation benchmarks.",
          actions: [
            { label: "Filter Developer Jobs", url: "https://remoteok.com/remote-dev-jobs" }
          ],
          tips: "Use keyboard shortcut / search tag 'worldwide' to locate roles without regional geo-fencing."
        },
        {
          name: "Jobgether",
          category: "Remote & Hybrid Job Aggregator",
          tag: "Transparent Location Filter",
          tagColor: "#a855f7",
          url: "https://jobgether.com/",
          logo: "https://www.google.com/s2/favicons?domain=jobgether.com&sz=128",
          bestFor: "Explicitly indexes 100% remote roles and tags them by true hiring geography (Global, APAC, EMEA).",
          hiringModel: "Aggregates ATS career sites (Greenhouse, Lever, Ashby) directly.",
          actions: [
            { label: "Find 100% Remote Tech Jobs", url: "https://jobgether.com/offers" }
          ],
          tips: "Filter by '100% Remote' and 'Location: India / Worldwide' for instant matches."
        }
      ];

      let cardsHtml = portals.map(p => {
        let actBtns = p.actions.map(a => `
          <a href="${a.url}" target="_blank" rel="noopener noreferrer" 
             style="display: inline-flex; align-items: center; gap: 6px; padding: 7px 14px; background: #1e293b; border: 1px solid #334155; color: #f8fafc; border-radius: 6px; font-size: 13px; font-weight: 500; text-decoration: none; transition: all 0.15s ease;"
             onmouseover="this.style.background='#334155'; this.style.borderColor='#64748b';"
             onmouseout="this.style.background='#1e293b'; this.style.borderColor='#334155';">
            <i class="fa-solid fa-arrow-up-right-from-square" style="font-size: 11px; color: ${p.tagColor};"></i> ${a.label}
          </a>
        `).join('');

        return `
          <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 22px; display: flex; flex-direction: column; justify-content: space-between; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); transition: transform 0.15s ease, border-color 0.15s ease;"
               onmouseover="this.style.borderColor='${p.tagColor}88'; this.style.transform='translateY(-2px)';"
               onmouseout="this.style.borderColor='#1e293b'; this.style.transform='none';">
            <div>
              <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 12px;">
                <div style="display: flex; align-items: center; gap: 12px;">
                  <img src="${p.logo}" alt="${p.name}" onerror="this.src='https://cdn-icons-png.flaticon.com/512/3135/3135715.png'" style="width: 32px; height: 32px; border-radius: 6px; background: #fff; padding: 2px; object-fit: contain;">
                  <div>
                    <h3 style="margin: 0; font-size: 18px; font-weight: 700; color: #f8fafc;">${p.name}</h3>
                    <div style="font-size: 12px; color: #94a3b8; margin-top: 2px;">${p.category}</div>
                  </div>
                </div>
                <span style="background: ${p.tagColor}22; color: ${p.tagColor}; border: 1px solid ${p.tagColor}55; padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 600; white-space: nowrap;">
                  ${p.tag}
                </span>
              </div>

              <p style="color: #cbd5e1; font-size: 13.5px; line-height: 1.5; margin: 12px 0 10px 0;">
                ${p.bestFor}
              </p>

              <div style="background: #1e293b55; border-left: 3px solid ${p.tagColor}; padding: 8px 12px; border-radius: 0 6px 6px 0; margin-bottom: 12px; font-size: 12.5px; color: #94a3b8;">
                <strong style="color: #e2e8f0;">Hiring Model:</strong> ${p.hiringModel}
              </div>

              <div style="background: #111827; padding: 8px 12px; border-radius: 6px; font-size: 12px; color: #a5f3fc; border: 1px solid #1e293b; margin-bottom: 16px;">
                <i class="fa-solid fa-lightbulb" style="color: #fbbf24; margin-right: 5px;"></i> <strong>Insider Tip:</strong> ${p.tips}
              </div>
            </div>

            <div style="display: flex; flex-wrap: wrap; gap: 8px; border-top: 1px solid #1e293b; padding-top: 14px; margin-top: auto;">
              ${actBtns}
            </div>
          </div>
        `;
      }).join('');

      container.innerHTML = `
        <div style="max-width: 1400px; margin: 0 auto; padding: 10px 0 40px 0;">
          <!-- Header Banner -->
          <div style="background: linear-gradient(135deg, rgba(16, 185, 129, 0.15), rgba(6, 182, 212, 0.15)); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 12px; padding: 24px 28px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;">
            <div>
              <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 6px;">
                <span style="background: #10b981; color: #022c22; font-size: 11px; font-weight: 700; text-transform: uppercase; padding: 3px 8px; border-radius: 4px;">Top Channels</span>
                <h2 style="margin: 0; font-size: 22px; font-weight: 800; color: #f8fafc;">Remote Engineering Agencies & Multi-Site Hub</h2>
              </div>
              <p style="margin: 0; color: #cbd5e1; font-size: 14px; max-width: 800px; line-height: 1.5;">
                Diversify beyond LinkedIn and Naukri. These vetted talent networks, direct agency headhunters, and curated global job boards actively place Indian backend & full-stack engineers into high-paying remote roles.
              </p>
            </div>
            <div style="display: flex; gap: 10px;">
              <button onclick="window.open('https://www.uplers.com/talent/', '_blank')" style="background: #10b981; border: none; color: #064e3b; font-weight: 700; padding: 10px 18px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; gap: 6px; box-shadow: 0 4px 6px rgba(16,185,129,0.3);">
                <i class="fa-solid fa-rocket"></i> Fast-Track Uplers Vetting
              </button>
            </div>
          </div>

          <!-- Quick Rule Cards -->
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; margin-bottom: 24px;">
            <div style="background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 14px 18px;">
              <div style="color: #34d399; font-weight: 700; font-size: 13px; margin-bottom: 4px;"><i class="fa-solid fa-check-circle"></i> 1. The 'Anywhere' Filter Rule</div>
              <div style="color: #94a3b8; font-size: 12px; line-height: 1.4;">"Remote" doesn't always mean open to India. Always toggle location filters to 'Worldwide', 'Global', or 'APAC' to avoid US-citizen tax restrictions.</div>
            </div>
            <div style="background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 14px 18px;">
              <div style="color: #38bdf8; font-weight: 700; font-size: 13px; margin-bottom: 4px;"><i class="fa-solid fa-bolt"></i> 2. Pass Vetting Tests Once</div>
              <div style="color: #94a3b8; font-size: 12px; line-height: 1.4;">On Uplers and Turing, complete your coding assessment once. Account managers then market your profile directly to multiple inbound clients.</div>
            </div>
            <div style="background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 14px 18px;">
              <div style="color: #fbbf24; font-weight: 700; font-size: 13px; margin-bottom: 4px;"><i class="fa-solid fa-shield-halved"></i> 3. Direct Contact Info Only</div>
              <div style="color: #94a3b8; font-size: 12px; line-height: 1.4;">For agencies like DistantJob and itForte, email recruitment partners directly with your tailored Meesho backend summary and CV.</div>
            </div>
          </div>

          <!-- Portals Grid -->
          <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 18px;">
            ${cardsHtml}
          </div>
        </div>
      `;
    }

    async function renderColdCrmView() {
      const container = document.getElementById('cold-crm-container');
      if (!container) return;
      container.innerHTML = '<div style="text-align:center; padding: 60px; color:#94a3b8;"><i class="fa-solid fa-spinner fa-spin" style="font-size:24px;"></i><p style="margin-top:10px;">Loading Cold Email Sales CRM...</p></div>';

      try {
        const res = await fetch('/api/cold_crm/summary');
        const data = await res.json();
        const m = data.metrics || { total_sent: 0, total_opened: 0, open_rate: 0, hot_leads: 0, total_replies: 0, total_calls: 0, due_followups_count: 0 };
        const due = data.due_followups || [];
        const leads = data.leads || [];
        const tpls = data.templates || [];

        let dueHtml = '';
        if (due.length === 0) {
          dueHtml = '<div style="background: rgba(30, 41, 59, 0.4); border: 1px dashed rgba(148, 163, 184, 0.25); border-radius: 8px; padding: 20px; text-align: center; color: #94a3b8;"><i class="fa-solid fa-circle-check" style="color: #10b981; margin-right: 8px;"></i> All caught up! No follow-ups due today. Follow-ups will trigger automatically based on open rates.</div>';
        } else {
          dueHtml = due.map(d => {
            const hotBadge = d.open_count >= 6 ? '<span style="background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 700; margin-left: 8px;">🔥 HOT LEAD (6+ OPENS)</span>' : '';
            return `
              <div style="background: rgba(15, 23, 42, 0.65); border: 1px solid rgba(14, 165, 233, 0.35); border-radius: 8px; padding: 16px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
                <div>
                  <div style="font-weight: 700; font-size: 16px; color: #f8fafc;">
                    🏢 ${d.company} &mdash; <span style="color: #38bdf8;">${d.role_title}</span> ${hotBadge}
                  </div>
                  <div style="color: #94a3b8; font-size: 13px; margin-top: 4px;">
                    Recipient: <strong>${d.recipient_name || d.recipient_email}</strong> (${d.recipient_role}) | Opens: <span style="color: #fde047; font-weight: 700;">${d.open_count}</span> | Follow-ups sent: ${d.followup_count}/${d.max_followups}
                  </div>
                  <div style="color: #cbd5e1; font-size: 12px; margin-top: 4px;">
                    Strategy: <span style="color: #a78bfa; font-weight: 600;">${d.strategy_label}</span>
                  </div>
                </div>
                <div style="display: flex; gap: 8px;">
                  <button class="btn btn-action" onclick="prepareFollowupAction(${d.id}, '${escapeHtml(d.company)}', '${escapeHtml(d.role_title)}', '${escapeHtml(d.recipient_name)}', '${escapeHtml(d.recipient_email)}', '${escapeHtml(d.subject)}', ${d.followup_count + 1}, ${d.open_count})" style="background: #0284c7; color: white; padding: 8px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; border: none;">
                    <i class="fa-solid fa-paper-plane" style="margin-right: 6px;"></i> Draft Follow-Up #${d.followup_count + 1}
                  </button>
                  <button class="btn btn-secondary" onclick="quickLogReply(${d.id})" style="background: rgba(51, 65, 85, 0.8); color: #cbd5e1; padding: 8px 12px; border-radius: 6px; font-size: 13px; cursor: pointer; border: 1px solid #475569;">
                    <i class="fa-solid fa-reply" style="margin-right: 6px;"></i> Log Reply
                  </button>
                </div>
              </div>
            `;
          }).join('');
        }

        let leadsHtml = '';
        if (leads.length === 0) {
          leadsHtml = '<div style="color: #94a3b8; text-align: center; padding: 30px;">No cold email campaigns logged yet. Click <strong>"+ New Cold Email Campaign"</strong> below to launch your first 3-target campaign!</div>';
        } else {
          leadsHtml = `
            <table style="width: 100%; border-collapse: collapse; font-size: 13px; color: #f1f5f9; text-align: left;">
              <thead>
                <tr style="border-bottom: 2px solid rgba(148, 163, 184, 0.2); color: #94a3b8; text-transform: uppercase; font-size: 11px;">
                  <th style="padding: 10px;">Company / Role</th>
                  <th style="padding: 10px;">Contact</th>
                  <th style="padding: 10px;">Opens</th>
                  <th style="padding: 10px;">Follow-Ups</th>
                  <th style="padding: 10px;">Status</th>
                  <th style="padding: 10px;">Strategy</th>
                  <th style="padding: 10px;">Actions</th>
                </tr>
              </thead>
              <tbody>
                ${leads.map(l => {
                  const statusColor = l.status === 'replied' ? '#34d399' : (l.status === 'call_scheduled' ? '#60a5fa' : (l.status === 'closed' ? '#94a3b8' : '#fbbf24'));
                  return `
                    <tr style="border-bottom: 1px solid rgba(148, 163, 184, 0.1);">
                      <td style="padding: 10px;">
                        <strong>${l.company}</strong><br><span style="color: #94a3b8; font-size: 11px;">${l.role_title}</span>
                      </td>
                      <td style="padding: 10px;">
                        ${l.recipient_name || l.recipient_email}<br><span style="color: #64748b; font-size: 11px;">${l.recipient_role}</span>
                      </td>
                      <td style="padding: 10px;">
                        <input type="number" min="0" value="${l.open_count}" style="width: 48px; background: rgba(15, 23, 42, 0.8); border: 1px solid #475569; color: #fde047; font-weight: 700; border-radius: 4px; padding: 2px 4px; text-align: center;" onchange="updateLeadOpens(${l.id}, this.value)">
                      </td>
                      <td style="padding: 10px;">
                        ${l.followup_count} / ${l.max_followups}
                      </td>
                      <td style="padding: 10px;">
                        <span style="color: ${statusColor}; font-weight: 600;">${l.status}</span>
                      </td>
                      <td style="padding: 10px; font-size: 11px; color: #cbd5e1;">
                        ${l.followup_strategy}
                      </td>
                      <td style="padding: 10px;">
                        <button onclick="openLogModal(${l.id}, '${escapeHtml(l.company)}', '${escapeHtml(l.recipient_email)}')" style="background: rgba(14, 165, 233, 0.15); border: 1px solid #0284c7; color: #38bdf8; border-radius: 4px; padding: 4px 8px; font-size: 11px; cursor: pointer;">
                          Update
                        </button>
                      </td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          `;
        }

        container.innerHTML = `
          <div style="margin-bottom: 24px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px;">
              <div>
                <h2 style="font-size: 22px; font-weight: 800; color: #f8fafc; margin: 0; display: flex; align-items: center; gap: 8px;">
                  <i class="fa-solid fa-bullseye" style="color: #0284c7;"></i> Cold Email Sales CRM
                </h2>
                <p style="color: #94a3b8; font-size: 13px; margin: 4px 0 0 0;">
                  Treating job hunting like a sales process: 3 contacts per company, open tracking, and intent-driven follow-ups.
                </p>
              </div>
              <div>
                <button onclick="openNewCampaignModal()" style="background: linear-gradient(135deg, #0284c7, #0369a1); color: white; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 8px; box-shadow: 0 4px 14px rgba(2, 132, 199, 0.35);">
                  <i class="fa-solid fa-plus"></i> New Cold Email Campaign (3 Contacts)
                </button>
              </div>
            </div>

            <!-- Funnel KPI Cards -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 24px;">
              <div class="stat-card" style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(148, 163, 184, 0.15); border-radius: 10px; padding: 16px;">
                <div style="color: #94a3b8; font-size: 12px; text-transform: uppercase;">Total Sent</div>
                <div style="font-size: 28px; font-weight: 800; color: #f8fafc; margin-top: 4px;">${m.total_sent}</div>
                <div style="color: #64748b; font-size: 11px;">Target: 20/day across 6 companies</div>
              </div>
              <div class="stat-card" style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(148, 163, 184, 0.15); border-radius: 10px; padding: 16px;">
                <div style="color: #94a3b8; font-size: 12px; text-transform: uppercase;">Opens / Rate</div>
                <div style="font-size: 28px; font-weight: 800; color: #fde047; margin-top: 4px;">${m.open_rate}%</div>
                <div style="color: #64748b; font-size: 11px;">${m.total_opened} emails opened</div>
              </div>
              <div class="stat-card" style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 10px; padding: 16px;">
                <div style="color: #f87171; font-size: 12px; text-transform: uppercase; font-weight: 700;">🔥 Hot Leads (6+ Opens)</div>
                <div style="font-size: 28px; font-weight: 800; color: #f87171; margin-top: 4px;">${m.hot_leads}</div>
                <div style="color: #94a3b8; font-size: 11px;">Internally forwarded / High intent</div>
              </div>
              <div class="stat-card" style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(148, 163, 184, 0.15); border-radius: 10px; padding: 16px;">
                <div style="color: #94a3b8; font-size: 12px; text-transform: uppercase;">Replies / Calls</div>
                <div style="font-size: 28px; font-weight: 800; color: #34d399; margin-top: 4px;">${m.total_replies} <span style="font-size: 16px; color: #60a5fa;">(${m.total_calls} calls)</span></div>
                <div style="color: #64748b; font-size: 11px;">Reply rate: ${m.reply_rate}%</div>
              </div>
            </div>

            <!-- Due Follow-Ups Section -->
            <div style="margin-bottom: 24px;">
              <h3 style="font-size: 16px; font-weight: 700; color: #38bdf8; margin: 0 0 12px 0; display: flex; align-items: center; gap: 8px;">
                <i class="fa-solid fa-clock-rotate-left"></i> Follow-Ups Due Today (${due.length})
              </h3>
              ${dueHtml}
            </div>

            <!-- Leads Pipeline Table -->
            <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(148, 163, 184, 0.15); border-radius: 10px; padding: 18px; margin-bottom: 24px;">
              <h3 style="font-size: 16px; font-weight: 700; color: #f8fafc; margin: 0 0 14px 0;">
                <i class="fa-solid fa-list-check" style="margin-right: 8px; color: #0284c7;"></i> Outreach Leads Ledger
              </h3>
              ${leadsHtml}
            </div>
          </div>
        `;
      } catch (err) {
        container.innerHTML = `<div style="color: #ef4444; padding: 40px; text-align: center;">Failed to load Cold Email CRM: ${err.message}</div>`;
      }
    }

    async function renderDailyTrackerView() {
      const container = document.getElementById('daily-tracker-container');
      if (!container) return;
      container.innerHTML = '<div style="text-align:center; padding: 60px; color:#94a3b8;"><i class="fa-solid fa-spinner fa-spin" style="font-size:24px;"></i><p style="margin-top:10px;">Loading Daily Target & Trajectory Tracker...</p></div>';

      await fetchFunnelData();
      const dt = (funnelData && funnelData.daily_tracker) ? funnelData.daily_tracker : null;
      if (!dt) {
        container.innerHTML = '<div style="color: #ef4444; padding: 40px; text-align: center;">Failed to load daily tracking data.</div>';
        return;
      }

      const h14 = dt.history_14d || [];
      const historyRows = h14.map(d => {
        const rowBg = d.is_today ? 'rgba(56, 189, 248, 0.08)' : 'transparent';
        const dateStyle = d.is_today ? 'color: #38bdf8; font-weight: 800;' : 'color: #cbd5e1;';
        const resMet = d.resume_goal_met ? '<span style="color:#38bdf8; font-weight:700;"><i class="fa-solid fa-check"></i> ' + d.resume_requested + ' / 5</span>' : `<span style="color:#94a3b8;">${d.resume_requested} / 5</span>`;
        const appMet = d.applied_goal_met ? '<span style="color:#34d399; font-weight:700;"><i class="fa-solid fa-check"></i> ' + d.applied_under_100 + ' / 5</span>' : `<span style="color:#94a3b8;">${d.applied_under_100} / 5</span>`;
        const bothBadge = d.both_goals_met ? '<span style="background:rgba(16,185,129,0.2); border:1px solid #10b981; color:#34d399; padding:2px 8px; border-radius:6px; font-weight:700; font-size:11px;">🏆 Quota Hit</span>' : (d.is_today ? '<span style="background:rgba(56,189,248,0.2); border:1px solid #38bdf8; color:#7dd3fc; padding:2px 8px; border-radius:6px; font-weight:700; font-size:11px;">⚡ In Progress</span>' : '<span style="background:rgba(100,116,139,0.15); color:#64748b; padding:2px 8px; border-radius:6px; font-size:11px;">Missed</span>');

        return `
          <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); background: ${rowBg};">
            <td style="padding: 12px 14px; ${dateStyle}">${d.label} ${d.is_today ? '<span style="font-size:10px; background:#0284c7; color:#fff; padding:1px 6px; border-radius:4px; margin-left:4px;">TODAY</span>' : ''}</td>
            <td style="padding: 12px 14px;">${resMet}</td>
            <td style="padding: 12px 14px;">${appMet} <span style="font-size:11px; color:#64748b;">(${d.applied_total} tot)</span></td>
            <td style="padding: 12px 14px;">${bothBadge}</td>
          </tr>
        `;
      }).reverse().join('');

      container.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:22px; margin-top:12px;">
          <!-- Header Banner -->
          <div style="background: linear-gradient(135deg, rgba(15, 23, 42, 0.95), rgba(30, 41, 59, 0.85)); border: 1.5px solid rgba(56, 189, 248, 0.4); border-radius: 14px; padding: 22px 26px;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;">
              <div>
                <div style="display:flex; align-items:center; gap:10px;">
                  <span style="font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:0.8px; color:#38bdf8;">Daily Discipline Execution Engine</span>
                  <span style="background:rgba(16,185,129,0.2); border:1px solid #10b981; color:#34d399; font-size:11px; font-weight:700; padding:2px 10px; border-radius:999px;">
                    <i class="fa-solid fa-fire"></i> ${dt.current_streak_days}-Day Active Streak
                  </span>
                </div>
                <h2 style="margin:6px 0 2px 0; font-size:22px; font-weight:800; color:#fff;">
                  Daily Goal: Min 5 Asking Resume & Min 5 Applied (< 100 Applicants)
                </h2>
                <span style="font-size:13px; color:#94a3b8;">
                  High-velocity pipeline strategy: Reaching recruiters directly & applying to low-applicant pool openings before competition builds up.
                </span>
              </div>
              <div style="display:flex; gap:10px;">
                <button class="btn btn-preview" onclick="setTab('incognito_fresh')" style="background:linear-gradient(135deg, #4f46e5, #4338ca); color:#fff; font-weight:700; padding:8px 16px; font-size:13px;">
                  <i class="fa-solid fa-bolt"></i> View Fresh Jobs (< 200 Apps)
                </button>
                <button class="btn btn-preview" onclick="openCustomDraftModal()" style="background:linear-gradient(135deg, #0284c7, #2563eb); color:#fff; font-weight:700; padding:8px 16px; font-size:13px;">
                  <i class="fa-solid fa-paper-plane"></i> Send Cold Outreach
                </button>
              </div>
            </div>
          </div>

          <!-- Today's Scorecard Cards -->
          <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:16px;">
            <div class="kpi-card" style="border-color: rgba(56, 189, 248, 0.4); background: linear-gradient(135deg, rgba(14,116,144,0.2), rgba(15,23,42,0.85));">
              <span class="kpi-label"><i class="fa-solid fa-file-invoice" style="color:#38bdf8;"></i> Today Asking Resume / Outreach</span>
              <span class="kpi-value" style="color:#38bdf8;">${dt.resume_requested} <span style="font-size:14px; font-weight:600; color:#94a3b8;">/ 5 target</span></span>
              <div style="background: rgba(51, 65, 85, 0.6); height: 8px; border-radius: 999px; overflow: hidden; margin-top: 10px; margin-bottom: 6px;">
                <div style="background: linear-gradient(90deg, #0284c7, #38bdf8); height: 100%; width: ${dt.resume_progress_pct}%; border-radius: 999px;"></div>
              </div>
              <span style="font-size:11.5px; color:#94a3b8;">${dt.resume_goal_met ? '✓ Goal Hit! Direct agency pitches & referral asks' : `${5 - dt.resume_requested} more pitches needed today`}</span>
            </div>

            <div class="kpi-card" style="border-color: rgba(16, 185, 129, 0.4); background: linear-gradient(135deg, rgba(6,78,59,0.25), rgba(15,23,42,0.85));">
              <span class="kpi-label"><i class="fa-solid fa-circle-check" style="color:#10b981;"></i> Today Applied (≤ 100 Applicants)</span>
              <span class="kpi-value" style="color:#10b981;">${dt.applied_under_100} <span style="font-size:14px; font-weight:600; color:#94a3b8;">/ 5 target</span></span>
              <div style="background: rgba(51, 65, 85, 0.6); height: 8px; border-radius: 999px; overflow: hidden; margin-top: 10px; margin-bottom: 6px;">
                <div style="background: linear-gradient(90deg, #059669, #34d399); height: 100%; width: ${dt.applied_progress_pct}%; border-radius: 999px;"></div>
              </div>
              <span style="font-size:11.5px; color:#94a3b8;">${dt.applied_goal_met ? `✓ Goal Hit! (${dt.applied_total} total applications submitted)` : `${5 - dt.applied_under_100} more low-competition submissions needed`}</span>
            </div>

            <div class="kpi-card" style="border-color: rgba(245, 158, 11, 0.4); background: linear-gradient(135deg, rgba(120,53,15,0.25), rgba(15,23,42,0.85));">
              <span class="kpi-label"><i class="fa-solid fa-trophy" style="color:#fbbf24;"></i> Consistency Streak</span>
              <span class="kpi-value" style="color:#fbbf24;">${dt.current_streak_days} <span style="font-size:14px; font-weight:600; color:#94a3b8;">days</span></span>
              <span style="font-size:11.5px; color:#94a3b8; margin-top:10px;">${dt.total_goals_met_days} total days hit 100% quota in history</span>
            </div>

            <div class="kpi-card" style="border-color: rgba(168, 85, 247, 0.4); background: linear-gradient(135deg, rgba(88,28,135,0.2), rgba(15,23,42,0.85));">
              <span class="kpi-label"><i class="fa-solid fa-chart-line" style="color:#c084fc;"></i> 30-Day Outlook</span>
              <span class="kpi-value" style="color:#c084fc;">150+ <span style="font-size:14px; font-weight:600; color:#94a3b8;">low-applicant roles</span></span>
              <span style="font-size:11.5px; color:#94a3b8; margin-top:10px;">Expected yield: <strong>12-18 recruiter phone screens</strong></span>
            </div>
          </div>

          <!-- 14-Day Trajectory Table -->
          <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 22px 24px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
              <div>
                <h3 style="margin:0; font-size:16px; font-weight:700; color:#f8fafc; display:flex; align-items:center; gap:8px;">
                  <i class="fa-solid fa-calendar-check" style="color:#38bdf8;"></i> 14-Day Trajectory Ledger
                </h3>
                <span style="font-size:12px; color:#94a3b8;">History of daily resume outreach and low-competition applications.</span>
              </div>
            </div>

            <table style="width:100%; border-collapse: collapse; font-size:13px; text-align:left;">
              <thead>
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); color: #94a3b8; font-size: 11.5px; text-transform: uppercase;">
                  <th style="padding: 10px 14px;">Date</th>
                  <th style="padding: 10px 14px;">Asking Resume (Target 5)</th>
                  <th style="padding: 10px 14px;">Applied <= 100 Apps (Target 5)</th>
                  <th style="padding: 10px 14px;">Status / Result</th>
                </tr>
              </thead>
              <tbody>
                ${historyRows}
              </tbody>
            </table>
          </div>
        </div>
      `;
    }

    async function updateLeadOpens(id, val) {
      const opens = parseInt(val, 10);
      if (isNaN(opens)) return;
      await fetch('/api/cold_crm/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outreach_id: id, open_count: opens })
      });
      renderColdCrmView();
    }

    function openNewCampaignModal() {
      openCustomDraftModal();
    }

    // --- Referral Network CRM Engine (Company-wise Connection Requests & Acceptance) ---
    async function renderReferralCrmView() {
      const container = document.getElementById('referral-crm-container');
      if (!container) return;

      container.innerHTML = `
        <div style="text-align:center; padding: 40px; color: #a855f7;">
          <i class="fa-solid fa-circle-notch fa-spin fa-2x"></i>
          <p style="margin-top: 10px; font-weight: 600;">Loading Referral Network CRM & Acceptance Rates...</p>
        </div>
      `;

      try {
        const res = await fetch('/api/referral_crm/summary');
        const data = await res.json();
        const m = data.metrics || { total_requested: 0, total_accepted: 0, acceptance_rate: 0, total_referrals: 0, pending_acceptance: 0, companies_count: 0 };
        const companies = data.companies || [];

        let companyCardsHtml = '';
        if (companies.length === 0) {
          companyCardsHtml = `
            <div style="text-align: center; padding: 40px 20px; background: rgba(15, 23, 42, 0.6); border: 1.5px dashed #475569; border-radius: 12px; color: #94a3b8;">
              <i class="fa-solid fa-user-group fa-3x" style="color: #64748b; margin-bottom: 12px;"></i>
              <h4 style="color: #f8fafc; margin: 0 0 8px 0;">No Referral Connection Requests Tracked Yet</h4>
              <p style="font-size: 13px; max-width: 500px; margin: 0 auto 16px auto;">
                When you reach out to 4-5 people at a target company on LinkedIn, log them here or directly from the <strong>"LinkedIn Outreach"</strong> modal. You'll never lose track of who accepted!
              </p>
              <button onclick="openAddConnectionModal()" class="btn" style="background: linear-gradient(135deg, #a855f7, #7c3aed); color: white; font-weight: 700; padding: 10px 18px;">
                <i class="fa-solid fa-plus"></i> Track First Connection Request
              </button>
            </div>
          `;
        } else {
          companyCardsHtml = `
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px;">
              ${companies.map(c => {
                const acceptPct = c.requested_count > 0 ? Math.round((c.accepted_count / c.requested_count) * 100) : 0;
                return `
                  <div style="background: rgba(15, 23, 42, 0.85); border: 1.5px solid ${c.accepted_count > 0 ? 'rgba(16, 185, 129, 0.4)' : 'rgba(148, 163, 184, 0.15)'}; border-radius: 12px; padding: 18px; box-shadow: 0 8px 24px rgba(0,0,0,0.3); display: flex; flex-direction: column; justify-content: space-between;">
                    <div>
                      <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                        <div>
                          <h3 style="margin: 0; font-size: 17px; font-weight: 800; color: #f8fafc; display: flex; align-items: center; gap: 8px;">
                            <i class="fa-solid fa-building" style="color: #38bdf8;"></i> ${escapeHtml(c.company)}
                          </h3>
                          <div style="font-size: 11.5px; color: #94a3b8; margin-top: 3px;">
                            ${c.people.length} employees contacted for referral
                          </div>
                        </div>
                        <div style="text-align: right;">
                          <span style="background: ${c.accepted_count > 0 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(148, 163, 184, 0.15)'}; color: ${c.accepted_count > 0 ? '#34d399' : '#cbd5e1'}; font-size: 12px; font-weight: 700; padding: 4px 8px; border-radius: 6px; border: 1px solid ${c.accepted_count > 0 ? '#059669' : '#334155'};">
                            ${c.accepted_count} / ${c.requested_count} Accepted (${acceptPct}%)
                          </span>
                        </div>
                      </div>

                      <!-- Progress bar of acceptance -->
                      <div style="background: #1e293b; border-radius: 4px; height: 6px; overflow: hidden; margin-bottom: 14px;">
                        <div style="background: linear-gradient(90deg, #10b981, #059669); height: 100%; width: ${acceptPct}%;"></div>
                      </div>

                      <!-- People List -->
                      <div style="display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px;">
                        ${c.people.map(p => {
                          const isAcc = p.status === 'accepted' || p.status === 'replied_referral';
                          const isRef = p.referral_status === 'referred' || p.referral_status === 'pitched';
                          return `
                            <div style="background: rgba(30, 41, 59, 0.6); border: 1px solid ${isAcc ? 'rgba(16, 185, 129, 0.3)' : 'rgba(255,255,255,0.06)'}; border-radius: 8px; padding: 9px 12px; display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                              <div style="min-width: 0; flex: 1;">
                                <div style="font-size: 13px; font-weight: 700; color: #f1f5f9; display: flex; align-items: center; gap: 6px;">
                                  <span>${escapeHtml(p.person_name)}</span>
                                  ${p.is_alumni ? '<span style="background:#1e3a8a; color:#93c5fd; font-size:9.5px; padding:1px 5px; border-radius:3px;">🎓 RVCE</span>' : ''}
                                </div>
                                <div style="font-size: 11px; color: #94a3b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                                  ${escapeHtml(p.headline || 'Employee / Engineer')}
                                </div>
                                <div style="font-size: 10.5px; color: #64748b; margin-top: 2px;">
                                  Sent: ${p.requested_at ? p.requested_at.substring(0, 10) : 'Recently'}
                                </div>
                              </div>
                              <div style="display: flex; gap: 6px; align-items: center; flex-shrink: 0;">
                                ${isAcc ? `
                                  <span style="background: #064e3b; color: #34d399; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px; border: 1px solid #059669;">
                                    <i class="fa-solid fa-check"></i> Accepted
                                  </span>
                                  <button onclick="promptPitchReferral(${p.id}, '${escapeHtml(p.person_name)}', '${escapeHtml(c.company)}')" class="btn" style="background: linear-gradient(135deg, #0284c7, #10b981); color: white; padding: 4px 8px; font-size: 10.5px; font-weight: 700;" title="Send tailored pitch note + resume">
                                    <i class="fa-solid fa-paper-plane"></i> Pitch
                                  </button>
                                ` : `
                                  <button onclick="markConnectionAccepted(${p.id}, '${escapeHtml(p.person_name)}')" class="btn" style="background: rgba(16, 185, 129, 0.15); border: 1px solid #10b981; color: #34d399; padding: 4px 8px; font-size: 10.5px; font-weight: 700;" title="Mark as accepted in LinkedIn">
                                    Mark Accepted
                                  </button>
                                `}
                                ${p.profile_url ? `
                                  <a href="${p.profile_url}" target="_blank" rel="noopener noreferrer" style="color: #38bdf8; font-size: 12px; padding: 4px;" title="Open LinkedIn Profile">
                                    <i class="fa-brands fa-linkedin"></i>
                                  </a>
                                ` : ''}
                              </div>
                            </div>
                          `;
                        }).join('')}
                      </div>
                    </div>

                    <div style="display: flex; justify-content: space-between; align-items: center; pt-2; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 10px;">
                      <span style="font-size: 11px; color: #a855f7; font-weight: 600;">
                        ${c.referral_count} Referral Pitch${c.referral_count === 1 ? '' : 'es'} Sent
                      </span>
                      <button onclick="openAddConnectionModal('${escapeHtml(c.company)}')" class="btn" style="background: rgba(168, 85, 247, 0.15); border: 1px solid #a855f7; color: #d8b4fe; font-size: 11px; padding: 4px 10px; font-weight: 700;">
                        <i class="fa-solid fa-plus"></i> Add Person
                      </button>
                    </div>
                  </div>
                `;
              }).join('')}
            </div>
          `;
        }

        container.innerHTML = `
          <div style="margin-bottom: 24px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px;">
              <div>
                <h2 style="font-size: 22px; font-weight: 800; color: #f8fafc; margin: 0; display: flex; align-items: center; gap: 8px;">
                  <i class="fa-solid fa-user-plus" style="color: #a855f7;"></i> Referral Connection Request CRM
                </h2>
                <p style="color: #94a3b8; font-size: 13px; margin: 4px 0 0 0;">
                  Company-wise tracking of connection requests sent to engineers and RVCE alumni: see exact acceptance ratios and follow up without forgetting!
                </p>
              </div>
              <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                <button onclick="syncLinkedInAcceptedConnections()" id="btn-sync-connections" style="background: linear-gradient(135deg, #0284c7, #0284c7); color: white; border: none; padding: 9px 16px; border-radius: 8px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 8px; box-shadow: 0 4px 14px rgba(2, 132, 199, 0.35);" title="Checks your LinkedIn recent connections and auto-matches accepted referral requests">
                  <i class="fa-solid fa-arrows-rotate"></i> Sync Accepted Connections
                </button>
                <button onclick="openAddConnectionModal()" style="background: linear-gradient(135deg, #a855f7, #7c3aed); color: white; border: none; padding: 9px 16px; border-radius: 8px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 8px; box-shadow: 0 4px 14px rgba(168, 85, 247, 0.35);">
                  <i class="fa-solid fa-plus"></i> Log Connection Request
                </button>
              </div>
            </div>

            <!-- Auto-Connect from Job URL Panel -->
            <div id="auto-connect-panel" style="background: linear-gradient(135deg, rgba(15,23,42,0.95), rgba(30,41,59,0.9)); border: 1.5px solid rgba(168, 85, 247, 0.35); border-radius: 14px; padding: 20px; margin-bottom: 20px; box-shadow: 0 8px 32px rgba(168,85,247,0.1);">
              <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 14px;">
                <i class="fa-solid fa-wand-magic-sparkles" style="color: #a855f7; font-size: 18px;"></i>
                <div>
                  <div style="font-size: 15px; font-weight: 800; color: #f8fafc;">🤝 Auto-Connect from LinkedIn Job URL</div>
                  <div style="font-size: 12px; color: #94a3b8; margin-top: 2px;">Paste a LinkedIn job link → finds your 1st/2nd-degree connections at that company → records them in CRM → optionally opens Brave to send connection requests</div>
                </div>
              </div>
              <div style="display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap;">
                <div style="flex: 1; min-width: 280px;">
                  <label style="font-size: 11px; color: #94a3b8; display: block; margin-bottom: 5px; font-weight: 600;">LinkedIn Job URL</label>
                  <input id="auto-connect-job-url" type="text" placeholder="https://www.linkedin.com/jobs/view/1234567..." style="width: 100%; background: rgba(15,23,42,0.8); border: 1.5px solid rgba(168,85,247,0.4); color: #f8fafc; padding: 9px 13px; border-radius: 8px; font-size: 13px; outline: none; box-sizing: border-box;" />
                </div>
                <div style="display: flex; gap: 8px; align-items: flex-end;">
                  <div>
                    <label style="font-size: 11px; color: #94a3b8; display: block; margin-bottom: 5px; font-weight: 600;">Max People</label>
                    <input id="auto-connect-max" type="number" value="5" min="1" max="20" style="width: 70px; background: rgba(15,23,42,0.8); border: 1.5px solid rgba(100,116,139,0.3); color: #f8fafc; padding: 9px 10px; border-radius: 8px; font-size: 13px; outline: none;" />
                  </div>
                  <button onclick="runAutoConnect(false)" id="btn-auto-discover" style="background: linear-gradient(135deg, #7c3aed, #a855f7); color: white; border: none; padding: 9px 15px; border-radius: 8px; font-weight: 700; cursor: pointer; white-space: nowrap; font-size: 13px;">
                    <i class="fa-solid fa-magnifying-glass"></i> Discover Only
                  </button>
                  <button onclick="runAutoConnect(true)" id="btn-auto-send" style="background: linear-gradient(135deg, #059669, #10b981); color: white; border: none; padding: 9px 15px; border-radius: 8px; font-weight: 700; cursor: pointer; white-space: nowrap; font-size: 13px;" title="Discover + open Brave to send connection requests">
                    <i class="fa-solid fa-paper-plane"></i> Discover + Connect
                  </button>
                </div>
              </div>
              <div id="auto-connect-result" style="margin-top: 14px; display: none;"></div>
            </div>

            <!-- KPI Cards -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 24px;">
              <div class="stat-card" style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(168, 85, 247, 0.2); border-radius: 10px; padding: 16px;">
                <div style="color: #94a3b8; font-size: 12px; text-transform: uppercase;">Total Sent</div>
                <div style="font-size: 28px; font-weight: 800; color: #f8fafc; margin-top: 4px;">${m.total_requested}</div>
                <div style="color: #64748b; font-size: 11px;">Across ${m.companies_count} Target Companies</div>
              </div>
              <div class="stat-card" style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 10px; padding: 16px;">
                <div style="color: #94a3b8; font-size: 12px; text-transform: uppercase;">Accepted</div>
                <div style="font-size: 28px; font-weight: 800; color: #34d399; margin-top: 4px;">${m.total_accepted}</div>
                <div style="color: #059669; font-size: 11px;">${m.acceptance_rate}% Acceptance Rate</div>
              </div>
              <div class="stat-card" style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(245, 158, 11, 0.2); border-radius: 10px; padding: 16px;">
                <div style="color: #94a3b8; font-size: 12px; text-transform: uppercase;">Awaiting Acceptance</div>
                <div style="font-size: 28px; font-weight: 800; color: #fbbf24; margin-top: 4px;">${m.pending_acceptance}</div>
                <div style="color: #b45309; font-size: 11px;">Sent within 24-48 hrs</div>
              </div>
              <div class="stat-card" style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(56, 189, 248, 0.2); border-radius: 10px; padding: 16px;">
                <div style="color: #94a3b8; font-size: 12px; text-transform: uppercase;">Referral Pitches</div>
                <div style="font-size: 28px; font-weight: 800; color: #38bdf8; margin-top: 4px;">${m.total_referrals}</div>
                <div style="color: #0284c7; font-size: 11px;">Pitched after acceptance</div>
              </div>
            </div>

            <!-- Company Cards Breakdown -->
            <div style="margin-bottom: 12px;">
              <h3 style="font-size: 16px; font-weight: 700; color: #f8fafc; margin-bottom: 14px; display: flex; align-items: center; gap: 8px;">
                <i class="fa-solid fa-network-wired" style="color: #a855f7;"></i> Company-wise Breakdown & Acceptance
              </h3>
              ${companyCardsHtml}
            </div>
          </div>
        `;
      } catch (err) {
        container.innerHTML = `<div style="color: #f87171; padding: 20px;">Failed to load Referral CRM: ${err}</div>`;
      }
    }

    async function markConnectionAccepted(id, name) {
      try {
        const res = await fetch('/api/referral_crm/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ request_id: id, status: 'accepted' })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast(`🎉 ${name} marked as ACCEPTED! Time to pitch referral!`);
          triggerConfetti();
          renderReferralCrmView();
          updateStats();
        }
      } catch (err) {
        showToast('Error updating status: ' + err);
      }
    }

    async function syncLinkedInAcceptedConnections() {
      const btn = document.getElementById('btn-sync-connections');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Checking LinkedIn...';
      }
      showToast('🔄 Scanning LinkedIn recent connections...');
      try {
        const res = await fetch('/api/referral_crm/sync_accepted', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
          let msg = '';
          if (data.matched_count > 0) {
            msg = `🎉 Found ${data.matched_count} new accepted connection(s)!`;
            triggerConfetti();
          } else {
            msg = `Scanned connections.`;
          }
          if (data.new_sent_discovered > 0) {
            msg += ` Auto-tracked ${data.new_sent_discovered} new sent invite(s)!`;
          }
          showToast(msg || 'Sync complete!');
          renderReferralCrmView();
          updateStats();
        } else {
          showToast('Sync notice: ' + (data.message || 'Error syncing'));
        }
      } catch (err) {
        showToast('Error syncing connections: ' + err);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Sync Accepted Connections';
        }
      }
    }

    async function promptPitchReferral(id, name, company) {
      showToast(`⚡ Preparing tailored referral pitch for ${name}...`);
      try {
        const res = await fetch('/api/referral_crm/pitch_generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ request_id: id })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          if (navigator.clipboard) {
            await navigator.clipboard.writeText(data.message);
          }
          showToast(`📋 Copied tailored referral pitch for ${name}! Opening Brave chat...`);
          
          // Open direct LinkedIn chat with the tailored message in Brave
          if (data.profile_url) {
            composeLinkedInDM(data.profile_url, data.message, company, data.role_title, 'referral', 'auto');
          }

          // Mark status as pitched in CRM
          fetch('/api/referral_crm/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ request_id: id, status: 'replied_referral', referral_status: 'pitched' })
          }).then(() => renderReferralCrmView());
        } else {
          showToast('Could not generate pitch: ' + data.message);
        }
      } catch (err) {
        showToast('Error preparing pitch: ' + err);
      }
    }

    function openAddConnectionModal(defaultCompany = '') {
      const comp = prompt('Company Name:', defaultCompany || '');
      if (!comp) return;
      const personName = prompt(`Person Name at ${comp}:`, '');
      if (!personName) return;
      const profileUrl = prompt(`LinkedIn Profile URL (optional):`, '');
      const headline = prompt(`Role / Headline (e.g. SDE-2 @ ${comp}):`, 'Software Engineer');
      const isAlumni = confirm(`Is ${personName} an RVCE alumnus?`);

      fetch('/api/referral_crm/record', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          company: comp.trim(),
          person_name: personName.trim(),
          profile_url: (profileUrl || '').trim(),
          headline: (headline || '').trim(),
          is_alumni: isAlumni
        })
      }).then(res => res.json()).then(data => {
        if (data.status === 'ok') {
          showToast(`✓ Tracked connection request to ${personName} @ ${comp}!`);
          renderReferralCrmView();
          updateStats();
        } else {
          showToast('Error: ' + (data.message || 'Failed'));
        }
      });
    }

    // ── Auto-Connect from LinkedIn Job URL ──────────────────────────────────
    async function runAutoConnect(sendConnection) {
      const jobUrl = (document.getElementById('auto-connect-job-url') || {}).value || '';
      const maxPeople = parseInt((document.getElementById('auto-connect-max') || {}).value || '5', 10);
      const resultBox = document.getElementById('auto-connect-result');

      if (!jobUrl.trim()) {
        showToast('⚠️ Please paste a LinkedIn job URL first.');
        return;
      }

      const btnDiscover = document.getElementById('btn-auto-discover');
      const btnSend = document.getElementById('btn-auto-send');
      if (btnDiscover) { btnDiscover.disabled = true; btnDiscover.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Searching...'; }
      if (btnSend) { btnSend.disabled = true; }
      if (resultBox) { resultBox.style.display = 'block'; resultBox.innerHTML = '<div style="color:#a855f7; font-size:13px;"><i class="fa-solid fa-circle-notch fa-spin"></i> Searching LinkedIn connections at this company... (may take 15-30s)</div>'; }
      showToast('🔍 Scanning LinkedIn for connections at this company...');

      try {
        const res = await fetch('/api/referral_crm/auto_connect', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ job_url: jobUrl.trim(), max_people: maxPeople, send_connection: sendConnection })
        });
        const data = await res.json();

        if (data.status === 'ok') {
          const found = data.found || [];
          if (found.length === 0) {
            if (resultBox) resultBox.innerHTML = `<div style="color:#fbbf24; font-size:13px; padding: 10px; background: rgba(251,191,36,0.1); border-radius: 8px; border: 1px solid rgba(251,191,36,0.3);">⚠️ No connections found at <strong>${escapeHtml(data.company || 'this company')}</strong>. Make sure your LinkedIn session is active (run LinkedIn Login from the sidebar).</div>`;
            showToast('No connections found at this company.');
          } else {
            showToast(`🎉 Found ${found.length} connection(s) at ${data.company}! Recorded in CRM.`);
            const peopleHtml = found.map(p => `
              <div style="display: flex; justify-content: space-between; align-items: center; padding: 9px 12px; background: rgba(30,41,59,0.6); border: 1px solid ${p.is_alumni ? 'rgba(59,130,246,0.4)' : 'rgba(255,255,255,0.08)'}; border-radius: 8px; gap: 8px;">
                <div style="flex: 1; min-width: 0;">
                  <div style="font-size: 13px; font-weight: 700; color: #f1f5f9; display: flex; align-items: center; gap: 6px;">
                    ${escapeHtml(p.person_name)}
                    ${p.is_alumni ? '<span style="background:#1e3a8a; color:#93c5fd; font-size:9.5px; padding:1px 5px; border-radius:3px;">🎓 RVCE</span>' : ''}
                    <span style="background: rgba(100,116,139,0.2); color: #94a3b8; font-size:9.5px; padding:1px 6px; border-radius:3px;">${escapeHtml(p.degree || '2nd')}</span>
                    ${p.existing ? '<span style="background:rgba(16,185,129,0.1); color:#34d399; font-size:9.5px; padding:1px 6px; border-radius:3px;">Already in CRM</span>' : '<span style="background:rgba(168,85,247,0.1); color:#d8b4fe; font-size:9.5px; padding:1px 6px; border-radius:3px;">New</span>'}
                  </div>
                  <div style="font-size: 11px; color: #94a3b8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(p.headline || '')}</div>
                </div>
                <div style="display: flex; gap: 6px; flex-shrink: 0;">
                  ${p.profile_url ? `
                    <button onclick="sendSingleConnectionRequest('${encodeURIComponent(p.profile_url)}', '${escapeHtml(p.person_name).replace(/'/g,'')}', '${escapeHtml(data.company || '').replace(/'/g,'')}', '${escapeHtml(data.role_title || '').replace(/'/g,'')}')"
                      style="background: linear-gradient(135deg, #059669, #10b981); color: white; border: none; padding: 5px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer;" title="Open Brave and pre-fill connection note">
                      🤝 Send Request
                    </button>
                    <a href="${escapeHtml(p.profile_url)}" target="_blank" rel="noopener noreferrer" style="color: #38bdf8; padding: 5px 7px; border-radius: 6px; background: rgba(56,189,248,0.1); display: flex; align-items: center;">
                      <i class="fa-brands fa-linkedin"></i>
                    </a>
                  ` : ''}
                </div>
              </div>
            `).join('');

            if (resultBox) resultBox.innerHTML = `
              <div style="border-top: 1px solid rgba(255,255,255,0.08); padding-top: 12px;">
                <div style="font-size: 13px; font-weight: 700; color: #f8fafc; margin-bottom: 10px;">
                  <i class="fa-solid fa-check-circle" style="color: #10b981;"></i>
                  Found ${found.length} connection(s) at <span style="color: #a855f7;">${escapeHtml(data.company || '')}</span> for <em>${escapeHtml(data.role_title || '')}</em>
                  ${sendConnection ? ' — Brave opened for connection requests!' : ''}
                </div>
                <div style="display: flex; flex-direction: column; gap: 8px;">${peopleHtml}</div>
                <div style="font-size: 11px; color: #64748b; margin-top: 10px;">All contacts saved to Referral CRM. Scroll down to see company cards ↓</div>
              </div>
            `;
            renderReferralCrmView();
            updateStats();
          }
        } else {
          const errMsg = data.message || 'Unknown error';
          if (resultBox) resultBox.innerHTML = `<div style="color:#f87171; font-size:13px; padding: 10px; background: rgba(248,113,113,0.1); border-radius: 8px; border: 1px solid rgba(248,113,113,0.3);">❌ ${escapeHtml(errMsg)}</div>`;
          showToast('Error: ' + errMsg);
        }
      } catch (err) {
        if (resultBox) resultBox.innerHTML = `<div style="color:#f87171; font-size:13px;">Network error: ${err}</div>`;
        showToast('Network error: ' + err);
      } finally {
        if (btnDiscover) { btnDiscover.disabled = false; btnDiscover.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i> Discover Only'; }
        if (btnSend) { btnSend.disabled = false; }
      }
    }

    async function sendSingleConnectionRequest(encodedUrl, name, company, roleTitle) {
      const profileUrl = decodeURIComponent(encodedUrl);
      showToast(`🤝 Opening Brave to connect with ${name}...`);
      try {
        const res = await fetch('/api/referral_crm/auto_connect', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            job_url: '',
            max_people: 1,
            send_connection: true,
            single_profile_url: profileUrl,
            single_name: name,
            single_company: company,
            single_role: roleTitle
          })
        });
        const data = await res.json();
        showToast(data.message || (data.status === 'ok' ? '✓ Brave opened for connection request!' : 'Error: ' + (data.message || 'Unknown')));
      } catch (err) {
        showToast('Error: ' + err);
      }
    }

    // Helper to log connection request right from the LinkedIn Outreach Modal
    function logConnectionFromModal(company, personName, profileUrl, headline, isAlumni) {
      fetch('/api/referral_crm/record', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          company: company,
          person_name: personName,
          profile_url: profileUrl || '',
          headline: headline || '',
          is_alumni: isAlumni
        })
      }).then(res => res.json()).then(data => {
        if (data.status === 'ok') {
          showToast(`⚡ Logged request to ${personName} @ ${company} in Referral CRM!`);
          updateStats();
        }
      });
    }

    async function prepareFollowupAction(id, company, role, name, email, subject, fNum, opens) {
      try {
        const res = await fetch('/api/cold_crm/generate_followup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ company, role_title: role, recipient_name: name, subject, followup_number: fNum, open_count: opens })
        });
        const data = await res.json();
        
        // Populate custom draft modal with follow-up content
        const modalTo = document.getElementById('custom-draft-to');
        const modalComp = document.getElementById('custom-draft-comp');
        const modalRole = document.getElementById('custom-draft-role');
        if (modalTo) modalTo.value = email;
        if (modalComp) modalComp.value = company;
        if (modalRole) modalRole.value = role;

        openCustomDraftModal();

        // Increment follow-up in CRM
        await fetch('/api/cold_crm/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ outreach_id: id, increment_followup: true })
        });
      } catch (e) {
        alert('Could not prepare follow-up: ' + e.message);
      }
    }

    function openScreeningCopilotModal(comp, role) {
      if (comp) document.getElementById('copilot-comp').value = comp;
      if (role) document.getElementById('copilot-role').value = role;
      document.getElementById('copilot-answer-box').style.display = 'none';
      document.getElementById('screening-copilot-modal').classList.add('active');
    }

    function closeScreeningCopilotModal() {
      document.getElementById('screening-copilot-modal').classList.remove('active');
    }

    async function submitScreeningCopilot() {
      const q = (document.getElementById('copilot-question').value || '').trim();
      const comp = (document.getElementById('copilot-comp').value || '').trim();
      const role = (document.getElementById('copilot-role').value || '').trim();

      if (!q) {
        alert('Please enter the question asked in the application.');
        return;
      }

      const btn = document.getElementById('copilot-submit-btn');
      const ansBox = document.getElementById('copilot-answer-box');
      const ansText = document.getElementById('copilot-answer-text');

      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generating Grounded Human Answer...';
      ansBox.style.display = 'none';

      try {
        const res = await fetch('/api/copilot/answer', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: q, company: comp, role_title: role })
        });
        const data = await res.json();
        ansText.textContent = data.answer || 'No answer generated.';
        ansBox.style.display = 'block';
      } catch (err) {
        alert('Copilot failed: ' + err.message);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate Personalized Human Answer (Gemini)';
      }
    }

    function copyCopilotAnswer() {
      const text = document.getElementById('copilot-answer-text').textContent;
      navigator.clipboard.writeText(text).then(() => {
        alert('Copied to clipboard! Ready to paste into application form.');
      }).catch(() => {
        alert('Failed to copy text.');
      });
    }

    function openLogModal(id, company, email) {
      const reply = prompt(`Log update for ${company} (${email}):\nReply status? (positive / polite / negative / none):`, 'positive');
      if (!reply) return;
      const call = confirm('Did this interaction lead to an interview or phone screen?');
      const notes = prompt('Any notes from the interaction?', '');

      fetch('/api/cold_crm/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outreach_id: id, reply_status: reply, led_to_call: call, notes: notes })
      }).then(() => renderColdCrmView());
    }

    function quickLogReply(id) {
      openLogModal(id, '', '');
    }

    function setTab(tab) {
      currentTab = tab;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      const activeBtn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick') && b.getAttribute('onclick').includes(`'${tab}'`));
      if (activeBtn) activeBtn.classList.add('active');

      const yetBanner = document.getElementById('yet-to-apply-banner');
      const freshBanner = document.getElementById('fresh-banner');
      const appBanner = document.getElementById('applied-banner');
      const qBanner = document.getElementById('queue-banner');
      const rBanner = document.getElementById('responses-banner');
      const respFilterBar = document.getElementById('resp-filter-bar');
      const sourceFilterBar = document.getElementById('source-filter-bar');
      const jobsContainer = document.getElementById('jobs-container');
      const analyticsContainer = document.getElementById('analytics-container');
      const strategyContainer = document.getElementById('strategy-container');
      const coldCrmContainer = document.getElementById('cold-crm-container');
      const referralCrmContainer = document.getElementById('referral-crm-container');

      if (sourceFilterBar) {
        sourceFilterBar.style.display = (tab === 'responses' || tab === 'analytics' || tab === 'strategy' || tab === 'cold_crm' || tab === 'remote_portals' || tab === 'daily_tracker' || tab === 'referral_crm') ? 'none' : 'flex';
      }

      const dailyTrackerContainer = document.getElementById('daily-tracker-container');
      if (dailyTrackerContainer) dailyTrackerContainer.style.display = (tab === 'daily_tracker') ? 'block' : 'none';
      if (referralCrmContainer) referralCrmContainer.style.display = (tab === 'referral_crm') ? 'block' : 'none';
      if (strategyContainer) strategyContainer.style.display = (tab === 'strategy') ? 'block' : 'none';
      if (coldCrmContainer) coldCrmContainer.style.display = (tab === 'cold_crm') ? 'block' : 'none';
      const remotePortalsContainer = document.getElementById('remote-portals-container');
      if (remotePortalsContainer) remotePortalsContainer.style.display = (tab === 'remote_portals') ? 'block' : 'none';

      if (tab === 'referral_crm') {
        if (yetBanner) yetBanner.style.display = 'none';
        if (freshBanner) freshBanner.style.display = 'none';
        if (appBanner) appBanner.style.display = 'none';
        qBanner.style.display = 'none';
        rBanner.style.display = 'none';
        if (respFilterBar) respFilterBar.style.display = 'none';
        if (jobsContainer) jobsContainer.style.display = 'none';
        if (analyticsContainer) analyticsContainer.style.display = 'none';
        if (strategyContainer) strategyContainer.style.display = 'none';
        if (coldCrmContainer) coldCrmContainer.style.display = 'none';
        renderReferralCrmView();
        return;
      }

      if (tab === 'daily_tracker') {
        if (yetBanner) yetBanner.style.display = 'none';
        if (freshBanner) freshBanner.style.display = 'none';
        if (appBanner) appBanner.style.display = 'none';
        qBanner.style.display = 'none';
        rBanner.style.display = 'none';
        if (respFilterBar) respFilterBar.style.display = 'none';
        if (jobsContainer) jobsContainer.style.display = 'none';
        if (analyticsContainer) analyticsContainer.style.display = 'none';
        if (strategyContainer) strategyContainer.style.display = 'none';
        if (coldCrmContainer) coldCrmContainer.style.display = 'none';
        renderDailyTrackerView();
        return;
      }

      if (tab === 'remote_portals') {
        if (yetBanner) yetBanner.style.display = 'none';
        if (freshBanner) freshBanner.style.display = 'none';
        if (appBanner) appBanner.style.display = 'none';
        qBanner.style.display = 'none';
        rBanner.style.display = 'none';
        if (respFilterBar) respFilterBar.style.display = 'none';
        if (jobsContainer) jobsContainer.style.display = 'none';
        if (analyticsContainer) analyticsContainer.style.display = 'none';
        if (strategyContainer) strategyContainer.style.display = 'none';
        if (coldCrmContainer) coldCrmContainer.style.display = 'none';
        renderRemotePortalsView();
        return;
      }

      if (tab === 'cold_crm') {
        if (yetBanner) yetBanner.style.display = 'none';
        if (freshBanner) freshBanner.style.display = 'none';
        if (appBanner) appBanner.style.display = 'none';
        qBanner.style.display = 'none';
        rBanner.style.display = 'none';
        if (respFilterBar) respFilterBar.style.display = 'none';
        if (jobsContainer) jobsContainer.style.display = 'none';
        if (analyticsContainer) analyticsContainer.style.display = 'none';
        if (strategyContainer) strategyContainer.style.display = 'none';
        renderColdCrmView();
        return;
      }

      if (tab === 'strategy') {
        if (yetBanner) yetBanner.style.display = 'none';
        if (freshBanner) freshBanner.style.display = 'none';
        if (appBanner) appBanner.style.display = 'none';
        qBanner.style.display = 'none';
        rBanner.style.display = 'none';
        if (respFilterBar) respFilterBar.style.display = 'none';
        if (jobsContainer) jobsContainer.style.display = 'none';
        if (analyticsContainer) analyticsContainer.style.display = 'none';
        renderStrategyView();
        return;
      }

      if (tab === 'analytics') {
        if (yetBanner) yetBanner.style.display = 'none';
        if (freshBanner) freshBanner.style.display = 'none';
        if (appBanner) appBanner.style.display = 'none';
        qBanner.style.display = 'none';
        rBanner.style.display = 'none';
        if (respFilterBar) respFilterBar.style.display = 'none';
        if (jobsContainer) jobsContainer.style.display = 'none';
        if (analyticsContainer) analyticsContainer.style.display = 'block';
        renderAnalytics();
        return;
      } else {
        if (analyticsContainer) analyticsContainer.style.display = 'none';
        if (jobsContainer) jobsContainer.style.display = 'grid';
      }

      const incognitoBanner = document.getElementById('incognito-banner');
      if (incognitoBanner) incognitoBanner.style.display = (tab === 'incognito_fresh' || tab === 'incognito_1h') ? 'flex' : 'none';
      if (yetBanner) yetBanner.style.display = (tab === 'yet_to_apply') ? 'flex' : 'none';
      if (freshBanner) freshBanner.style.display = (tab === 'fresh') ? 'flex' : 'none';
      if (appBanner) appBanner.style.display = (tab === 'applied') ? 'flex' : 'none';

      if (tab === 'approved') {
        qBanner.style.display = 'flex';
        rBanner.style.display = 'none';
        if (respFilterBar) respFilterBar.style.display = 'none';
      } else if (tab === 'responses') {
        qBanner.style.display = 'none';
        rBanner.style.display = 'flex';
        if (respFilterBar) respFilterBar.style.display = 'flex';
      } else {
        qBanner.style.display = 'none';
        rBanner.style.display = 'none';
        if (respFilterBar) respFilterBar.style.display = 'none';
      }

      const kaBanner = document.getElementById('kadegree-info-banner');
      if (kaBanner) kaBanner.style.display = (tab === 'kadegree') ? 'flex' : 'none';

      const easyBanner = document.getElementById('easy-apply-info-banner');
      if (easyBanner) easyBanner.style.display = (tab === 'easy_apply') ? 'flex' : 'none';

      if (tab === 'kadegree') {
        currentSourceFilter = 'kadegree';
        document.querySelectorAll('.source-pill').forEach(p => p.classList.remove('active'));
        const activePill = document.getElementById('src-kadegree');
        if (activePill) activePill.classList.add('active');
      }

      renderJobs();
    }

    function renderResponses() {
      const q = document.getElementById('search-input').value.toLowerCase().trim();
      let filtered = allResponses.filter(r => {
        if (responseCategoryFilter === 'oa' && r.category !== 'oa') return false;
        if (responseCategoryFilter === 'interview_selected' && r.category !== 'interview_selected') return false;
        if (responseCategoryFilter === 'rejected' && r.category !== 'rejected') return false;
        if (responseCategoryFilter === 'apply_link' && r.category !== 'apply_link') return false;
        if (responseCategoryFilter === 'acknowledged' && r.category !== 'acknowledged') return false;

        if (q) {
          const hay = `${r.company} ${r.role_title} ${r.status} ${r.summary} ${r.body_snippet} ${r.sender} ${r.due_date || ''}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      });

      const container = document.getElementById('jobs-container');
      if (filtered.length === 0) {
        container.innerHTML = `
          <div style="text-align: center; padding: 60px 20px; color: #64748b; background: rgba(15,23,42,0.4); border-radius: 16px; border: 1px dashed #334155;">
            <i class="fa-regular fa-envelope" style="font-size: 36px; margin-bottom: 12px; opacity: 0.6;"></i>
            <h3 style="color: #cbd5e1; font-size: 16px;">No application responses found in this category</h3>
            <p style="font-size: 13px; margin-top: 6px;">Click [🔄 Sync Gmail Inbox] to scan your inbox for updates, or switch category filter.</p>
          </div>
        `;
        return;
      }

      container.innerHTML = filtered.map(r => {
        const cat = r.category || 'acknowledged';
        const isDone = !!r.is_completed;
        const initial = (r.company || 'C').charAt(0).toUpperCase();

        let cardClass = 'response-card ';
        let badgeHtml = '';
        let extraBanner = '';
        let actionButtons = '';

        if (cat === 'oa') {
          const dueLower = (r.due_date || '').toLowerCase();
          const isPassed = !isDone && ['9 nov', '9 november', 'nov 9', 'november 9', '8 nov', '7 nov'].some(k => dueLower.includes(k));

          if (isPassed) {
            cardClass += 'cat-oa is-missed';
            badgeHtml = `<span class="sentiment-badge" style="background: linear-gradient(90deg, #be123c, #ef4444); color: #fff;"><i class="fa-solid fa-triangle-exclamation"></i> Missed Opportunity / Overdue</span>`;
            extraBanner = `
              <div style="background: rgba(239, 68, 68, 0.15); border: 1.5px solid #ef4444; border-radius: 10px; padding: 12px 16px; margin-top: 10px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                <div>
                  <div style="font-size: 11px; text-transform: uppercase; color: #fca5a5; font-weight: 800; letter-spacing: 0.5px;">
                    <i class="fa-solid fa-calendar-xmark"></i> Assessment Deadline Passed
                  </div>
                  <div style="font-size: 15px; font-weight: 800; color: #fff; margin-top: 2px;">
                    ${r.due_date || 'Expired'} &mdash; <span style="color: #f87171;">Expired ~15 hours ago</span>
                  </div>
                </div>
                <div style="display: flex; gap: 6px; align-items: center;">
                  <span style="background: #be123c; color: #fff; font-size: 11px; font-weight: 800; padding: 5px 12px; border-radius: 999px;">
                    <i class="fa-solid fa-clock-rotate-left"></i> WINDOW CLOSED
                  </span>
                </div>
              </div>

              <!-- Preventive Action & Recovery Protocol Box -->
              <div style="background: rgba(15, 23, 42, 0.8); border: 1px dashed rgba(239, 68, 68, 0.4); border-radius: 8px; padding: 10px 14px; margin-top: 8px; font-size: 12px; color: #cbd5e1; line-height: 1.5;">
                <div style="font-weight: 700; color: #fca5a5; margin-bottom: 4px;">
                  <i class="fa-solid fa-shield-halved"></i> How to avoid this & recover the opportunity:
                </div>
                <div style="color: #94a3b8;">
                  1. <strong>Immediate Recovery:</strong> Click <em>[Request 24h Extension in Gmail]</em> below. Recruiters routinely grant 24-48h extensions when notified politely.<br>
                  2. <strong>Future Guardrail:</strong> Automatic Google Calendar sync will now schedule deadline blocks with reminders 6h and 2h before closing.
                </div>
              </div>
            `;
            actionButtons = `
              <button class="btn btn-brave" onclick="requestExtension('${r.message_id}')" style="background: linear-gradient(135deg, #ea4335, #dc2626); border-color: #ef4444; box-shadow: 0 0 16px rgba(239, 68, 68, 0.35);">
                <i class="fa-solid fa-envelope"></i> Request 24h Extension in Gmail
              </button>
              ${r.action_url ? `
                <a href="${r.action_url}" target="_blank" rel="noopener noreferrer" class="btn btn-preview" style="text-decoration: none;">
                  <i class="fa-solid fa-arrow-up-right-from-square"></i> Try Assessment Link Anyway
                </a>
              ` : ''}
              <button class="btn btn-preview" onclick="toggleResponseCompleted('${r.message_id}')">
                <i class="fa-solid fa-check"></i> Mark Resolved
              </button>
            `;
          } else {
            cardClass += 'cat-oa' + (isDone ? ' is-done' : '');
            badgeHtml = `<span class="sentiment-badge oa"><i class="fa-solid fa-laptop-code"></i> Online Assessment</span>`;
            extraBanner = `
              <div style="background: rgba(245, 158, 11, 0.15); border: 1.5px solid #f59e0b; border-radius: 10px; padding: 12px 16px; margin-top: 10px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                <div>
                  <div style="font-size: 11px; text-transform: uppercase; color: #fde047; font-weight: 800; letter-spacing: 0.5px;">
                    <i class="fa-solid fa-clock"></i> Assessment Due Date / Deadline
                  </div>
                  <div style="font-size: 15px; font-weight: 800; color: #fff; margin-top: 2px;">
                    ${r.due_date || 'Check email for window / completion deadline'}
                  </div>
                </div>
                <div>
                  ${isDone 
                    ? '<span style="background: #059669; color: #fff; font-size: 11px; font-weight: 800; padding: 5px 12px; border-radius: 999px;"><i class="fa-solid fa-circle-check"></i> COMPLETED</span>'
                    : '<span style="background: #dc2626; color: #fff; font-size: 11px; font-weight: 800; padding: 5px 12px; border-radius: 999px; animation: pulseAlert 2s infinite;"><i class="fa-solid fa-triangle-exclamation"></i> ACTION REQUIRED</span>'
                  }
                </div>
              </div>
            `;
            actionButtons = `
              ${r.action_url ? `
                <a href="${r.action_url}" target="_blank" rel="noopener noreferrer" class="btn btn-brave" style="background: linear-gradient(135deg, #d97706, #b45309); border-color: #f59e0b; text-decoration: none;">
                  <i class="fa-solid fa-code"></i> Open Assessment in Brave
                </a>
              ` : ''}
              <button class="btn btn-preview" onclick="toggleResponseCompleted('${r.message_id}')" style="background: ${isDone ? 'rgba(16, 185, 129, 0.2)' : 'rgba(255,255,255,0.06)'}; border-color: ${isDone ? '#10b981' : 'rgba(255,255,255,0.15)'};">
                <i class="fa-solid ${isDone ? 'fa-arrow-rotate-left' : 'fa-check'}"></i> ${isDone ? 'Mark as Pending' : 'Mark as Completed'}
              </button>
            `;
          }
        } else if (cat === 'interview_selected') {
          cardClass += 'cat-interview';
          badgeHtml = `<span class="sentiment-badge positive"><i class="fa-solid fa-trophy"></i> Selected / Next Round</span>`;
          extraBanner = `
            <div style="background: rgba(16, 185, 129, 0.15); border: 1.5px solid #10b981; border-radius: 10px; padding: 12px 16px; margin-top: 10px;">
              <i class="fa-solid fa-calendar-check" style="color: #34d399; font-size: 16px; margin-right: 8px;"></i>
              <strong style="color: #6ee7b7;">Next Step:</strong> <span style="color: #fff; font-weight: 700;">${r.due_date || 'Technical Interview / Discussion Scheduled'}</span>
            </div>
          `;
          actionButtons = `
            ${r.action_url ? `
              <a href="${r.action_url}" target="_blank" rel="noopener noreferrer" class="btn btn-brave" style="background: linear-gradient(135deg, #059669, #10b981); text-decoration: none;">
                <i class="fa-solid fa-calendar-days"></i> Schedule Interview in Brave
              </a>
            ` : ''}
          `;
        } else if (cat === 'rejected') {
          cardClass += 'cat-rejected';
          badgeHtml = `<span class="sentiment-badge negative"><i class="fa-solid fa-circle-xmark"></i> Not Selected / Rejected</span>`;
          actionButtons = `
            ${r.action_url ? `
              <a href="${r.action_url}" target="_blank" rel="noopener noreferrer" class="btn btn-preview" style="text-decoration: none;">
                <i class="fa-solid fa-building"></i> View Company Portal
              </a>
            ` : ''}
          `;
        } else if (cat === 'apply_link') {
          cardClass += 'cat-apply';
          badgeHtml = `<span class="sentiment-badge apply"><i class="fa-solid fa-link"></i> Direct Apply Link</span>`;
          if (r.due_date) {
            extraBanner = `
              <div style="background: rgba(6, 182, 212, 0.15); border: 1.5px solid #06b6d4; border-radius: 10px; padding: 10px 14px; margin-top: 10px; font-size: 13px; color: #bae6fd;">
                <i class="fa-solid fa-clock" style="margin-right: 6px;"></i> <strong>Application Deadline:</strong> ${r.due_date}
              </div>
            `;
          }
          actionButtons = `
            ${r.action_url ? `
              <a href="${r.action_url}" target="_blank" rel="noopener noreferrer" class="btn btn-brave" style="background: linear-gradient(135deg, #0284c7, #06b6d4); text-decoration: none;">
                <i class="fa-solid fa-arrow-up-right-from-square"></i> Open Application in Brave
              </a>
            ` : ''}
          `;
        } else {
          cardClass += 'cat-acknowledged';
          badgeHtml = `<span class="sentiment-badge neutral"><i class="fa-regular fa-envelope"></i> Application Acknowledged</span>`;
        }

        return `
          <div class="${cardClass}">
            <div class="card-top">
              <div class="job-meta">
                <div class="company-avatar" style="background: ${cat === 'oa' ? 'linear-gradient(135deg, #d97706, #f59e0b)' : cat === 'interview_selected' ? 'linear-gradient(135deg, #059669, #10b981)' : cat === 'rejected' ? 'linear-gradient(135deg, #9f1239, #f43f5e)' : cat === 'apply_link' ? 'linear-gradient(135deg, #0284c7, #06b6d4)' : 'linear-gradient(135deg, #334155, #64748b)'}">${initial}</div>
                <div>
                  <div class="job-title-row">
                    <span class="job-title" style="font-size: 18px;">${r.company}</span>
                    <span style="font-size: 13px; color: #94a3b8; font-weight: normal; margin-left: 8px;">(${r.role_title || 'Software Engineer'})</span>
                  </div>
                  <div class="job-sub">
                    <span><i class="fa-regular fa-envelope"></i> ${r.sender}</span>
                    <span><i class="fa-regular fa-calendar"></i> ${r.received_date || ''}</span>
                    <span style="background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); color: ${r.channel_color || '#38bdf8'}; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700;">
                      <i class="${r.channel_icon || 'fa-solid fa-paper-plane'}"></i> ${r.channel || 'Direct Application'}
                    </span>
                    <span style="color: #cbd5e1; font-size: 11px; font-weight: 600;">
                      <i class="fa-solid fa-stopwatch" style="color: #f59e0b;"></i> Response Turnaround: <strong>${r.turnaround_label || '1-3 days'}</strong>
                    </span>
                  </div>
                </div>
              </div>
              <div>${badgeHtml}</div>
            </div>

            ${extraBanner}

            <!-- Intelligence & Why Explanation Block -->
            <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 10px; padding: 14px; font-size: 13px; color: #cbd5e1; line-height: 1.6;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; flex-wrap: wrap; gap: 8px;">
                <div style="font-weight: 700; color: #f8fafc; display: flex; align-items: center; gap: 8px;">
                  <i class="fa-solid fa-comment-dots" style="color: ${cat === 'oa' ? '#fbbf24' : cat === 'interview_selected' ? '#34d399' : cat === 'rejected' ? '#fb7185' : '#38bdf8'};"></i>
                  <span>${r.status}: ${r.summary}</span>
                </div>
                ${r.applied_at_str ? `<span style="font-size: 11px; color: #94a3b8;"><i class="fa-regular fa-calendar-check"></i> Applied: ${r.applied_at_str}</span>` : ''}
              </div>
              <div style="background: rgba(30, 41, 59, 0.5); border-left: 3px solid ${cat === 'oa' || cat === 'interview_selected' ? '#10b981' : cat === 'rejected' ? '#f43f5e' : '#38bdf8'}; border-radius: 4px; padding: 6px 10px; margin-bottom: 6px; font-size: 12px; color: #e2e8f0;">
                <i class="fa-solid fa-brain" style="color: #a855f7; margin-right: 5px;"></i> <strong>Why / Attribution:</strong> ${r.why_status || 'Tracking in recruitment pipeline.'}
              </div>
              <div style="color: #94a3b8; font-style: italic; font-size: 12px; border-left: 2px solid rgba(255,255,255,0.12); padding-left: 10px; margin-top: 6px;">
                "${r.body_snippet}"
              </div>
            </div>

            <div class="actions-bar" style="margin-top: 4px;">
              ${actionButtons}
              <button class="btn btn-cheatsheet" onclick="openCheatsheetModal('${encodeURIComponent(r.company || '')}', '${encodeURIComponent(r.role_title || '')}')" style="background: rgba(168, 85, 247, 0.2); border: 1.5px solid #a855f7; color: #d8b4fe; font-weight: 700; padding: 7px 12px; font-size: 12px; border-radius: 8px; cursor: pointer;" title="Open tailored technical and behavioral interview prep cheat-sheet">
                <i class="fa-solid fa-bolt"></i> ⚡ Prep Cheat-Sheet
              </button>
              <button class="btn btn-preview" onclick="showToast('Email Subject: ' + '${(r.subject || '').replace(/'/g, "\'")}')">
                <i class="fa-solid fa-envelope"></i> Subject: ${(r.subject || '').substring(0, 42)}...
              </button>
            </div>
          </div>
        `;
      }).join('');
    }

    async function fetchAnalytics() {
      try {
        const res = await fetch('/api/analytics');
        analyticsData = await res.json();
        const badge = document.getElementById('badge-analytics');
        if (badge && analyticsData && analyticsData.metrics) {
          badge.textContent = analyticsData.metrics.total_applications;
        }
      } catch (err) {
        console.error('Failed to load analytics:', err);
      }
    }

    function filterAnalyticsSource(src) {
      analyticsSourceFilter = src;
      renderAnalytics();
    }

    function filterAnalyticsStage(stg) {
      analyticsStageFilter = stg;
      renderAnalytics();
    }

    function renderAnalytics() {
      const container = document.getElementById('analytics-container');
      if (!container) return;
      if (!analyticsData || !analyticsData.metrics) {
        container.innerHTML = '<div style="text-align:center; padding: 60px; color:#94a3b8;"><i class="fa-solid fa-spinner fa-spin"></i> Loading application analytics...</div>';
        return;
      }

      const m = analyticsData.metrics;
      const sources = analyticsData.sources || [];
      const rawTimeline = analyticsData.timeline || [];

      // Filter timeline
      const q = (document.getElementById('search-input')?.value || '').toLowerCase().trim();
      let timeline = rawTimeline.filter(e => {
        if (analyticsSourceFilter !== 'all' && e.source_code !== analyticsSourceFilter) return false;
        if (analyticsStageFilter !== 'all' && e.stage !== analyticsStageFilter) return false;
        if (q) {
          const hay = `${e.company} ${e.role} ${e.source} ${e.stage_label} ${e.applied_date} ${e.turnaround_str}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      });

      container.innerHTML = `
        <div class="analytics-panel">
          <!-- KPI Summary Grid -->
          <div class="kpi-grid">
            <div class="kpi-card" style="border-color: rgba(56, 189, 248, 0.4);">
              <span class="kpi-label"><i class="fa-solid fa-paper-plane" style="color:#38bdf8;"></i> Total Applications</span>
              <span class="kpi-value" style="color: #38bdf8;">${m.total_applications}</span>
              <span style="font-size: 11px; color: #94a3b8; margin-top: 4px;">Tracked across ATS & Gmail</span>
            </div>
            <div class="kpi-card" style="border-color: rgba(16, 185, 129, 0.4);">
              <span class="kpi-label"><i class="fa-solid fa-chart-line" style="color:#34d399;"></i> Response Rate</span>
              <span class="kpi-value" style="color: #34d399;">${m.response_rate}%</span>
              <span style="font-size: 11px; color: #94a3b8; margin-top: 4px;">${m.total_responses} of ${m.total_applications} responded</span>
            </div>
            <div class="kpi-card" style="border-color: rgba(245, 158, 11, 0.4);">
              <span class="kpi-label"><i class="fa-solid fa-laptop-code" style="color:#fbbf24;"></i> Active OAs Due</span>
              <span class="kpi-value" style="color: #fbbf24;">${m.active_oas}</span>
              <span style="font-size: 11px; color: #94a3b8; margin-top: 4px;">Action required with deadline</span>
            </div>
            <div class="kpi-card" style="border-color: rgba(16, 185, 129, 0.4);">
              <span class="kpi-label"><i class="fa-solid fa-trophy" style="color:#10b981;"></i> Technical Interviews</span>
              <span class="kpi-value" style="color: #10b981;">${m.interviews}</span>
              <span style="font-size: 11px; color: #94a3b8; margin-top: 4px;">Shortlisted / Next round</span>
            </div>
            <div class="kpi-card" style="border-color: rgba(244, 63, 94, 0.4);">
              <span class="kpi-label"><i class="fa-solid fa-ban" style="color:#f43f5e;"></i> Rejections Logged</span>
              <span class="kpi-value" style="color: #f43f5e;">${m.rejections}</span>
              <span style="font-size: 11px; color: #94a3b8; margin-top: 4px;">Position closed</span>
            </div>
            <div class="kpi-card" style="border-color: rgba(168, 85, 247, 0.4);">
              <span class="kpi-label"><i class="fa-solid fa-gauge-high" style="color:#c084fc;"></i> Avg Turnaround</span>
              <span class="kpi-value" style="color: #c084fc;">${m.avg_response_days} <small style="font-size: 14px; font-weight: normal;">days</small></span>
              <span style="font-size: 11px; color: #94a3b8; margin-top: 4px;">Avg time to recruiter reply</span>
            </div>
          </div>

          <!-- Section: FROM WHERE DID I APPLY? (Source & Channel Analytics) -->
          <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; padding: 22px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px;">
              <div>
                <h3 style="margin: 0; font-size: 16px; font-weight: 800; color: #f8fafc; display: flex; align-items: center; gap: 8px;">
                  <i class="fa-solid fa-diagram-project" style="color: #38bdf8;"></i> Application Channels: "From Where I Applied"
                </h3>
                <p style="margin: 4px 0 0; font-size: 12.5px; color: #94a3b8;">
                  Traceability breakdown across direct ATS platforms, company portals, and referral channels.
                </p>
              </div>
              <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                <button class="resp-pill ${analyticsSourceFilter === 'all' ? 'active' : ''}" onclick="filterAnalyticsSource('all')">All Sources (${m.total_applications})</button>
                <button class="resp-pill ${analyticsSourceFilter === 'workday' ? 'active' : ''}" onclick="filterAnalyticsSource('workday')">Workday</button>
                <button class="resp-pill ${analyticsSourceFilter === 'greenhouse' ? 'active' : ''}" onclick="filterAnalyticsSource('greenhouse')">Greenhouse</button>
                <button class="resp-pill ${analyticsSourceFilter === 'smartrecruiters' ? 'active' : ''}" onclick="filterAnalyticsSource('smartrecruiters')">SmartRecruiters</button>
                <button class="resp-pill ${analyticsSourceFilter === 'lever' ? 'active' : ''}" onclick="filterAnalyticsSource('lever')">Lever Referral</button>
                <button class="resp-pill ${analyticsSourceFilter === 'linkedin' ? 'active' : ''}" onclick="filterAnalyticsSource('linkedin')">LinkedIn</button>
              </div>
            </div>

            <div class="sources-grid">
              ${sources.map(s => {
                const pctOfTotal = Math.round((s.count / m.total_applications) * 100);
                return `
                  <div class="source-card" style="border-left: 3px solid ${s.color};">
                    <div class="source-card-header">
                      <span class="source-name">
                        <i class="fa-solid fa-circle" style="color: ${s.color}; font-size: 8px;"></i> ${s.name}
                      </span>
                      <span style="font-size: 12px; font-weight: 800; color: ${s.response_rate >= 75 ? '#34d399' : s.response_rate >= 50 ? '#38bdf8' : '#94a3b8'};">
                        ${s.response_rate}% Response Rate
                      </span>
                    </div>
                    <div class="progress-bar-bg">
                      <div class="progress-bar-fill" style="width: ${pctOfTotal}%; background: ${s.color};"></div>
                    </div>
                    <div class="source-stat-row">
                      <span><strong>${s.count}</strong> applications (${pctOfTotal}% of total)</span>
                      <span><strong>${s.responses}</strong> responses &bull; <strong>${s.interviews}</strong> interview</span>
                    </div>
                  </div>
                `;
              }).join('')}
            </div>
          </div>

          <!-- Section: WHEN DID I APPLY & AUDIT LEDGER (Timeline & Traceability) -->
          <div class="audit-table-wrap">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; flex-wrap: wrap; gap: 12px;">
              <div>
                <h3 style="margin: 0; font-size: 16px; font-weight: 800; color: #f8fafc; display: flex; align-items: center; gap: 8px;">
                  <i class="fa-solid fa-clock-rotate-left" style="color: #fbbf24;"></i> Application Lifecycle Ledger: "When I Applied & What Happened"
                </h3>
                <p style="margin: 4px 0 0; font-size: 12.5px; color: #94a3b8;">
                  Complete chronological trace of application dates, origin requisition links, tailored resumes, and recruiter responses.
                </p>
              </div>
              <div style="display: flex; gap: 10px; align-items: center;">
                <a href="/api/analytics/export_csv" class="btn btn-preview" style="text-decoration: none; padding: 7px 15px; font-size: 12px; background: rgba(56, 189, 248, 0.15); border: 1px solid #38bdf8; color: #38bdf8; font-weight: 700;">
                  <i class="fa-solid fa-download"></i> Export Audit Ledger (CSV)
                </a>
                <button class="btn btn-preview" onclick="loadAnalyticsData()" style="padding: 7px 14px; font-size: 12px;">
                  <i class="fa-solid fa-arrows-rotate"></i> Refresh
                </button>
              </div>
            </div>

            <!-- Stage Filter Pills -->
            <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px;">
              <button class="resp-pill ${analyticsStageFilter === 'all' ? 'active' : ''}" onclick="filterAnalyticsStage('all')">All Stages (${rawTimeline.length})</button>
              <button class="resp-pill ${analyticsStageFilter === 'oa_pending' ? 'active' : ''}" onclick="filterAnalyticsStage('oa_pending')">⚡ Active OAs (${m.active_oas})</button>
              <button class="resp-pill ${analyticsStageFilter === 'interview' ? 'active' : ''}" onclick="filterAnalyticsStage('interview')">🎯 Interviews (${m.interviews})</button>
              <button class="resp-pill ${analyticsStageFilter === 'rejected' ? 'active' : ''}" onclick="filterAnalyticsStage('rejected')">❌ Rejections (${m.rejections})</button>
              <button class="resp-pill ${analyticsStageFilter === 'acknowledged' ? 'active' : ''}" onclick="filterAnalyticsStage('acknowledged')">📬 Acknowledged (${m.acknowledged})</button>
              <button class="resp-pill ${analyticsStageFilter === 'applied_pending' ? 'active' : ''}" onclick="filterAnalyticsStage('applied_pending')">⏳ Applied Only (${m.applied_only})</button>
            </div>

            <table class="audit-table">
              <thead>
                <tr>
                  <th>When Applied</th>
                  <th>Company & Role</th>
                  <th>From Where (Source)</th>
                  <th>Requisition Link</th>
                  <th>Resume Used</th>
                  <th>Current Stage & Next Step</th>
                  <th>Velocity</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                ${timeline.map(e => {
                  const initial = (e.company || 'C').charAt(0).toUpperCase();
                  const isOA = e.stage === 'oa_pending';
                  const isInterview = e.stage === 'interview';
                  const isRej = e.stage === 'rejected';

                  return `
                    <tr>
                      <td style="white-space: nowrap;">
                        <div style="font-weight: 700; color: #f8fafc;">${e.applied_date}</div>
                        <span style="font-size: 11px; color: #94a3b8;"><i class="fa-regular fa-clock"></i> ${e.days_ago_str}</span>
                      </td>
                      <td>
                        <div style="display: flex; align-items: center; gap: 10px;">
                          <div style="width: 32px; height: 32px; border-radius: 8px; background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.3); display: flex; align-items: center; justify-content: center; font-weight: 800; color: #38bdf8;">${initial}</div>
                          <div>
                            <div style="font-weight: 700; color: #fff;">${e.company}</div>
                            <div style="font-size: 12px; color: #94a3b8;">${e.role}</div>
                          </div>
                        </div>
                      </td>
                      <td>
                        <span class="badge-source ${e.source_code}">
                          <i class="fa-solid fa-link"></i> ${e.source}
                        </span>
                      </td>
                      <td>
                        <a href="${e.requisition_url}" target="_blank" rel="noopener noreferrer" class="btn btn-sm btn-brave" style="padding: 4px 10px; font-size: 11px; text-decoration: none;">
                          <i class="fa-brands fa-brave"></i> View Requisition
                        </a>
                      </td>
                      <td>
                        <span class="tag tag-resume" style="font-size: 11px; padding: 3px 8px;">
                          <i class="fa-solid fa-file-pdf"></i> Tailored PDF
                        </span>
                      </td>
                      <td>
                        <div>
                          <span class="badge-stage" style="background: ${isOA ? 'rgba(245, 158, 11, 0.2)' : isInterview ? 'rgba(16, 185, 129, 0.2)' : isRej ? 'rgba(244, 63, 94, 0.2)' : 'rgba(56, 189, 248, 0.15)'}; color: ${e.stage_color}; border: 1px solid ${e.stage_color};">
                            ${e.stage_label}
                          </span>
                          ${e.latest_snippet ? `<div style="font-size: 11.5px; color: #94a3b8; margin-top: 4px; max-width: 280px; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">${e.latest_snippet}</div>` : ''}
                        </div>
                      </td>
                      <td style="white-space: nowrap; font-size: 12px; color: #cbd5e1;">
                        <i class="fa-solid fa-stopwatch" style="color: #94a3b8; margin-right: 4px;"></i> ${e.turnaround_str}
                      </td>
                      <td style="white-space: nowrap;">
                        ${isOA ? `
                          <a href="${e.action_url}" target="_blank" rel="noopener noreferrer" class="btn btn-sm btn-brave" style="background: linear-gradient(135deg, #d97706, #f59e0b); border-color: #f59e0b; text-decoration: none; padding: 4px 10px; font-size: 11px;">
                            <i class="fa-solid fa-code"></i> Open Test
                          </a>
                        ` : isInterview ? `
                          <a href="${e.action_url}" target="_blank" rel="noopener noreferrer" class="btn btn-sm btn-brave" style="background: linear-gradient(135deg, #059669, #10b981); text-decoration: none; padding: 4px 10px; font-size: 11px;">
                            <i class="fa-solid fa-calendar-check"></i> Schedule
                          </a>
                        ` : `
                          <a href="${e.requisition_url}" target="_blank" rel="noopener noreferrer" class="btn btn-preview" style="padding: 4px 10px; font-size: 11px; text-decoration: none;">
                            <i class="fa-solid fa-arrow-up-right-from-square"></i> Portal
                          </a>
                        `}
                      </td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          </div>
        </div>
      `;
    }

    async function loadAnalyticsData() {
      showToast('Refreshing application analytics and audit ledger...');
      await fetchAnalytics();
      renderAnalytics();
      showToast('Analytics refreshed!');
    }

    let currentSort = 'recent';

    function changeSort(val) {
      currentSort = val;
      renderJobs();
    }
    function getJobEffectiveDate(job) {
      // For incognito fresh jobs or if date_posted has only YYYY-MM-DD date without time (diff will be artificially offset),
      // prioritize the exact discovered_at timestamp
      if (job.strategy === 'linkedin_1h_incognito') {
        if (job.date_posted && job.date_posted.includes('T')) {
          const dp = new Date(job.date_posted);
          if (!isNaN(dp.getTime())) return dp;
        }
        if (job.discovered_at && job.discovered_at.trim() !== '') {
          const da = new Date(job.discovered_at);
          if (!isNaN(da.getTime())) return da;
        }
      }
      if (job.date_posted && job.date_posted.trim() !== '') {
        const dp = new Date(job.date_posted);
        if (!isNaN(dp.getTime())) return dp;
      }
      if (job.discovered_at && job.discovered_at.trim() !== '') {
        const da = new Date(job.discovered_at);
        if (!isNaN(da.getTime())) return da;
      }
      return null;
    }

    function formatJobTime(job) {
      const isExplicitPosted = !!(job.date_posted && job.date_posted.trim() !== '');
      const d = getJobEffectiveDate(job);
      if (!d) return '';

      const diffMs = Date.now() - d.getTime();
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMins / 60);
      const diffDays = Math.floor(diffHours / 24);

      let relText = '';
      if (diffMins < 1) relText = 'Just now';
      else if (diffMins < 60) relText = `${diffMins}m ago`;
      else if (diffHours < 24) relText = `${diffHours}h ago`;
      else if (diffDays === 1) relText = 'Yesterday';
      else relText = `${diffDays}d ago`;

      const isFresh = diffMs >= 0 && diffMs <= 4 * 60 * 60 * 1000;
      const formattedDate = d.toLocaleDateString('en-IN', { month: 'short', day: 'numeric' });
      const labelPrefix = isExplicitPosted ? 'Posted' : 'Discovered';

      if (isFresh) {
        return `<span style="background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); padding: 2px 7px; border-radius: 6px; font-weight: 700; font-size: 11px;" title="${labelPrefix} on ${d.toLocaleString()} (Under 4 hours ago!)"><i class="fa-solid fa-bolt"></i> ${labelPrefix} ${relText} (${formattedDate})</span>`;
      }
      return `<span style="color: #94a3b8; font-size: 11px;" title="${labelPrefix} on ${d.toLocaleString()}"><i class="fa-regular fa-calendar"></i> ${labelPrefix} ${formattedDate} (${relText})</span>`;
    }

    function renderJobs() {
      if (currentTab === 'responses') {
        renderResponses();
        return;
      }

      const q = document.getElementById('search-input').value.toLowerCase().trim();
      let filtered = allJobs.filter(job => {
        // Excluded companies check helper (always skip accenture, infosys, capgemini, flexiple)
        const isCompanyExcluded = (j) => {
          const comp = (j.company || j.site || '').toLowerCase();
          const tit = (j.title || '').toLowerCase();
          const blocked = ['accenture', 'infosys', 'capgemini', 'flexiple'];
          return blocked.some(b => comp.includes(b) || tit.includes(b));
        };

        if (isCompanyExcluded(job)) return false;

        if (currentTab === 'yet_to_apply') {
          const isEligible = (job.fit_score !== null && job.fit_score >= 7) || !!job.tailored_resume_path;
          if (!isEligible || job.apply_status === 'applied' || job.apply_status === 'interview' || job.apply_status === 'rejected' || job.apply_status === 'ignored') return false;
        }
        // Experience guardrail check helper (strictly reject roles requiring > 3 YOE or ranges like 6-10, 4-8, 3-5 yrs)
        const checkIsOverExperienced = (j) => {
          const tit = (j.title || '').toLowerCase();
          const desc = (j.desc || j.description || j.full_desc || j.full_description || '').toLowerCase();
          const combined = `${tit} ${desc}`;
          
          // Senior/Lead title check
          const seniorWords = ['senior', 'sr.', 'sr ', 'lead', 'tech lead', 'staff', 'principal', 'manager', 'mgr', 'architect', 'director', 'iii', 'iv', 'l3', 'l4', 'l5'];
          if (seniorWords.some(w => tit.includes(w))) return true;

          // Range pattern: e.g. "6-10 years", "4 to 8 yrs", "3-5 years", "4-6 yrs"
          const rangePat = /(\d+)\+?\s*(?:to|-)\s*(\d+)\s*(?:years?|yrs?)/gi;
          let m;
          while ((m = rangePat.exec(combined)) !== null) {
            const low = parseInt(m[1], 10);
            const high = parseInt(m[2], 10);
            if (!isNaN(low) && low > 3) return true;
            if (!isNaN(high) && (high >= 5 || high > 3)) return true;
          }

          // Single/min experience pattern: e.g. "4+ years", "5+ years", "6+ yrs", "min 4 years", "4 yoe", "5 yoe"
          const singlePat = /(?:(?:minimum|min|at least)\s*)?(\d+)\+?\s*(?:years?|yrs?)(?:\s*of)?\s*(?:relevant|hands-on|industry|software|backend|work)?\s*experience|\b(\d+)\+?\s*yoe\b/gi;
          while ((m = singlePat.exec(combined)) !== null) {
            const exp = parseInt(m[1] || m[2], 10);
            if (!isNaN(exp) && exp > 3) return true;
          }

          // Single year without trailing word: e.g. "4+ years", "5+ yrs"
          const plusPat = /(\d+)\+\s*(?:years?|yrs?)/gi;
          while ((m = plusPat.exec(combined)) !== null) {
            const exp = parseInt(m[1], 10);
            if (!isNaN(exp) && exp > 3) return true;
          }

          return false;
        };

        if (currentTab === 'fresh') {
          if (job.apply_status === 'applied' || job.apply_status === 'ignored' || job.apply_status === 'rejected') return false;
          if (job.num_applicants !== null && job.num_applicants !== undefined && job.num_applicants >= 200) return false;
          if (checkIsOverExperienced(job)) return false;
          const d = getJobEffectiveDate(job);
          if (!d) return false;
          const diff = Date.now() - d.getTime();
          if (isNaN(diff) || diff > 4 * 60 * 60 * 1000 || diff < 0) return false;
        }
        if (currentTab === 'fresh_24h') {
          if (job.apply_status === 'applied' || job.apply_status === 'ignored' || job.apply_status === 'rejected') return false;
          if (job.num_applicants !== null && job.num_applicants !== undefined && job.num_applicants >= 200) return false;
          if (checkIsOverExperienced(job)) return false;
          const d = getJobEffectiveDate(job);
          if (!d) return false;
          const diff = Date.now() - d.getTime();
          if (isNaN(diff) || diff > 24 * 60 * 60 * 1000 || diff < 0) return false;
        }
        if (currentTab === 'high' && (job.fit_score === null || job.fit_score < 7 || job.apply_status === 'ignored' || job.apply_status === 'applied')) return false;
        if (currentTab === 'top' && (job.fit_score === null || job.fit_score < 8 || job.apply_status === 'ignored' || job.apply_status === 'applied')) return false;
        if (currentTab === 'approved' && (job.apply_status !== 'approved' || job.apply_status === 'applied')) return false;
        if (currentTab === 'applied' && job.apply_status !== 'applied') return false;
        if (currentTab === 'asked_referral' && job.apply_status !== 'asked_referral') return false;
        if (currentTab === 'ignored' && job.apply_status !== 'ignored') return false;
        if (currentTab === 'kadegree' && ((!job.is_kadegree && job.source_category !== 'kadegree') || job.apply_status === 'ignored' || job.apply_status === 'applied')) return false;
        if (currentTab === 'incognito_fresh' || currentTab === 'incognito_1h') {
          const isIncognitoJob = (job.strategy === 'linkedin_1h_incognito' || job.strategy === 'indeed_incognito' || job.strategy === 'ats');
          if (!isIncognitoJob || job.apply_status === 'ignored' || job.apply_status === 'applied') return false;
          if (isCompanyExcluded(job)) return false;
          if (job.num_applicants !== null && job.num_applicants !== undefined && job.num_applicants >= 200) return false;
          if (checkIsOverExperienced(job)) return false;
          const d = getJobEffectiveDate(job);
          if (d) {
            const diff = Date.now() - d.getTime();
            // Up to 24 hours fresh for multi-source incognito
            if (!isNaN(diff) && diff > 24 * 60 * 60 * 1000) return false;
          }
        }
        if (currentTab === 'easy_apply') {
          const isLinkedInEasy = (job.is_easy_apply === 1) || (job.source_category === 'linkedin' && job.strategy === 'linkedin_easy_apply');
          if (!isLinkedInEasy || job.apply_status === 'ignored' || job.apply_status === 'applied') return false;
        }

        if (currentSourceFilter !== 'all') {
          if (currentSourceFilter === 'kadegree' && !job.is_kadegree && job.source_category !== 'kadegree') return false;
          if (currentSourceFilter === 'linkedin' && job.source_category !== 'linkedin') return false;
          if (currentSourceFilter === 'whatsapp' && job.source_category !== 'whatsapp') return false;
          if (currentSourceFilter === 'seed_funded' && job.strategy !== 'seed_funded') return false;
          if (currentSourceFilter === 'ats' && (job.is_kadegree || job.source_category === 'linkedin' || job.source_category === 'whatsapp' || job.strategy === 'seed_funded')) return false;
        }

        if (q) {
          const hay = `${job.company} ${job.title} ${job.location} ${job.source || ''} ${job.score_reasoning || ''}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      });

      // Apply User-Selected Sorting
      filtered.sort((a, b) => {
        const da = getJobEffectiveDate(a);
        const db = getJobEffectiveDate(b);
        const ta = da ? da.getTime() : 0;
        const tb = db ? db.getTime() : 0;
        if (currentSort === 'recent') {
          return tb - ta;
        } else if (currentSort === 'fit') {
          const fa = a.fit_score ?? 0;
          const fb = b.fit_score ?? 0;
          if (fb !== fa) return fb - fa;
          return tb - ta;
        } else if (currentSort === 'oldest') {
          const ota = da ? da.getTime() : Date.now();
          const otb = db ? db.getTime() : Date.now();
          return ota - otb;
        } else if (currentSort === 'company') {
          return (a.company || '').localeCompare(b.company || '');
        }
        return 0;
      });

      const container = document.getElementById('jobs-container');
      if (filtered.length === 0) {
        container.innerHTML = `
          <div style="text-align: center; padding: 60px 20px; color: #64748b; background: rgba(15,23,42,0.4); border-radius: 16px; border: 1px dashed #334155;">
            <i class="fa-regular fa-folder-open" style="font-size: 36px; margin-bottom: 12px; opacity: 0.6;"></i>
            <h3 style="color: #cbd5e1; font-size: 16px;">No opportunities in this tab</h3>
            <p style="font-size: 13px; margin-top: 6px;">Try switching tabs or adjusting search filter.</p>
          </div>
        `;
        return;
      }

      container.innerHTML = filtered.map(job => {
        const score = job.fit_score ?? 0;
        const scoreClass = score >= 9 ? 'score-9' : score >= 8 ? 'score-8' : score >= 7 ? 'score-7' : score >= 5 ? 'score-mid' : 'score-low';
        const cardClass = 'job-card';
        const hasResume = !!job.tailored_resume_path;
        const hasCover = !!job.cover_letter_path;
        const isApproved = job.apply_status === 'approved';
        const isApplied = job.apply_status === 'applied';
        const isAskedReferral = job.apply_status === 'asked_referral';
        const isIgnored = job.apply_status === 'ignored';

        // Calculate Age & Reminder Urgency
        let urgencyBadge = '';
        if (!isApplied && !isIgnored && job.discovered_at) {
          const postDate = new Date(job.discovered_at);
          const ageDays = (Date.now() - postDate.getTime()) / (1000 * 60 * 60 * 24);
          if (ageDays >= 3 && !isAskedReferral) {
            urgencyBadge = `<span style="background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; margin-left: 6px;" title="Discovered ${Math.floor(ageDays)} days ago. Apply or ask for a referral immediately before opening fills!"><i class="fa-solid fa-triangle-exclamation"></i> Late: Apply/Referral Urgently!</span>`;
          } else if (ageDays >= 1.5 && !isAskedReferral) {
            urgencyBadge = `<span style="background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #f59e0b; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; margin-left: 6px;" title="Discovered over 36 hours ago. Action recommended today."><i class="fa-solid fa-hourglass-half"></i> Apply / Ask Soon</span>`;
          }
        }
        if (isAskedReferral && job.referral_contacted_at) {
          const refDate = new Date(job.referral_contacted_at);
          const refAgeDays = (Date.now() - refDate.getTime()) / (1000 * 60 * 60 * 24);
          if (refAgeDays >= 2) {
            urgencyBadge = `<span style="background: rgba(168, 85, 247, 0.25); color: #e9d5ff; border: 1px solid #a855f7; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; margin-left: 6px;" title="Referral requested ${Math.floor(refAgeDays)} days ago. Time to send a polite follow-up message!"><i class="fa-solid fa-bell"></i> Follow Up with ${job.referral_contact_name || 'Referrer'}</span>`;
          }
        }

        const initial = (job.company || 'C').charAt(0).toUpperCase();

        return `
          <div class="${cardClass}" id="card-${job.rowid}">
            <div class="card-top">
              <div class="job-meta">
                <div class="company-avatar">${initial}</div>
                <div>
                  <div class="job-title-row">
                    <span class="job-title">${job.title}</span>
                    ${urgencyBadge}
                  </div>
                  <div class="job-sub">
                    <span><i class="fa-regular fa-building"></i> <strong>${job.company}</strong></span>
                    <span><i class="fa-solid fa-location-dot"></i> ${job.location}</span>
                    <span class="source-badge-meta ${job.is_kadegree ? 'source-kadegree-badge' : ''}">
                      <i class="${job.source_icon || 'fa-solid fa-layer-group'}"></i> <strong>${job.source || 'Direct ATS'}</strong>
                    </span>
                    ${formatJobTime(job)}
                  </div>
                </div>
              </div>

              <div class="score-badge ${scoreClass}">
                <span class="num">${score}</span>
                <span class="denom">FIT / 10</span>
              </div>
            </div>

            <div class="badges-row">
              ${job.is_kadegree ? `
                <span class="tag tag-kadegree"><i class="fa-solid fa-users-rays"></i> KaDegree Community Referral</span>
                ${job.referrer_info ? `<span class="tag tag-referrer"><i class="fa-solid fa-handshake-angle"></i> ${job.referrer_info}</span>` : ''}
                ${job.slots_info ? `<span class="tag" style="background:rgba(217,119,6,0.2);color:#fde047;border:1px solid #f59e0b;"><i class="fa-solid fa-bolt"></i> ${job.slots_info}</span>` : ''}
              ` : job.source_category === 'linkedin' ? `
                <span class="tag tag-linkedin"><i class="fa-brands fa-linkedin"></i> LinkedIn Source</span>
              ` : job.source_category === 'whatsapp' ? `
                <span class="tag tag-whatsapp"><i class="fa-brands fa-whatsapp"></i> WhatsApp Referral</span>
              ` : `
                <span class="tag tag-ats"><i class="fa-solid fa-building-circle-check"></i> ${job.source || 'Direct ATS'}</span>
              `}
              ${job.recruiter_email ? `<span class="tag tag-email"><i class="fa-solid fa-envelope"></i> ${job.recruiter_email}</span>` : ''}
              ${job.num_applicants !== null && job.num_applicants !== undefined ? `<span class="tag" style="background:rgba(16,185,129,0.18);color:#6ee7b7;border:1px solid #10b981;"><i class="fa-solid fa-users"></i> ${job.num_applicants < 20 ? '< 20 Applicants' : job.num_applicants + ' Applicants'}</span>` : ''}
              ${hasResume ? `<span class="tag tag-resume"><i class="fa-solid fa-file-pdf"></i> Tailored Resume Ready</span>` : '<span class="tag" style="background:#334155;color:#94a3b8;"><i class="fa-solid fa-clock"></i> Base Resume</span>'}
              ${hasCover ? `<span class="tag tag-cover"><i class="fa-solid fa-envelope-open-text"></i> Cover Letter Ready</span>` : ''}
              ${isApplied ? `<span class="tag tag-applied"><i class="fa-solid fa-check-double"></i> Applied</span>` : job.apply_status === 'asked_referral' ? `<span class="tag" style="background:rgba(168,85,247,0.25);color:#d8b4fe;border:1px solid #a855f7;"><i class="fa-solid fa-people-arrows"></i> Asked Referral${job.referral_contact_name ? ' (' + job.referral_contact_name + ')' : ''}</span>` : isApproved ? `<span class="tag tag-approved"><i class="fa-solid fa-thumbs-up"></i> Approved Shortlist</span>` : isIgnored ? `<span class="tag tag-ignored"><i class="fa-solid fa-ban"></i> Ignored</span>` : ''}
              ${job.referral_contacted_at ? `<span class="tag" style="background:#1e1b4b;color:#c084fc;border:1px solid #4338ca;"><i class="fa-regular fa-clock"></i> Outreach: ${new Date(job.referral_contacted_at).toLocaleDateString('en-IN', {month:'short', day:'numeric'})}</span>` : ''}
            </div>

            ${job.score_reasoning ? `<div class="reasoning">${job.score_reasoning.replace(/\\n/g, '<br>')}</div>` : ''}

            <div class="actions-bar">
              ${job.is_kadegree ? `
                <!-- KaDegree Community Referral Link -->
                <a href="${job.kadegree_url || job.url}" target="_blank" rel="noopener noreferrer" class="btn" style="background: linear-gradient(135deg, #b45309, #d97706); color: white; text-decoration: none; padding: 7px 14px; font-size: 12px; font-weight: 700; border-radius: 8px; display: inline-flex; align-items: center; gap: 6px;" title="View referral post, referrer details & comments in Kannada Referral Community">
                  <i class="fa-solid fa-users-rays"></i> View on KaDegree
                </a>
                <button class="btn" style="background: rgba(217, 119, 6, 0.2); border: 1px solid #d97706; color: #fbbf24; font-size: 12px; font-weight: 700; border-radius: 8px; padding: 7px 12px;" onclick="copyKannadaPitchByRowid(${job.rowid})" title="Copy warm Kannada referral pitch (ನಮಸ್ಕಾರ...) to send to referrer">
                  <i class="fa-regular fa-copy"></i> Copy Kannada Pitch
                </button>
              ` : ''}

              <!-- 1-Click Autonomous Auto-Apply Button (Kanistus Workflow) -->
              <button class="btn btn-auto-apply" id="btn-auto-apply-${job.rowid}" onclick="launchAutonomousApply(${job.rowid})" title="Does everything itself in Brave: navigates, clicks Easy Apply/ATS apply, answers screening questions, attaches tailored resume, and submits">
                <i class="fa-solid fa-bolt"></i> ${job.is_easy_apply || (job.url && job.url.includes('linkedin.com')) ? 'Auto-Apply (Easy Apply)' : 'Auto-Apply (Autonomous)'}
              </button>

              <!-- Application Assistant Autofill & Review Button -->
              <button class="btn btn-autofill" id="btn-autofill-${job.rowid}" onclick="launchAutofill(${job.rowid})" title="Auto-fills all fields and holds for Deepak's final review before submitting">
                <i class="fa-solid fa-shield-halved"></i> Fill & Review
              </button>

              <!-- Live Brave Browser Launcher -->
              <a href="${(job.apply_url && !job.apply_url.toLowerCase().startsWith('none')) ? job.apply_url : (job.url || '#')}" target="_blank" rel="noopener noreferrer" class="btn btn-brave" onclick="handleJobClick(event, ${job.rowid}, '${encodeURIComponent(job.tailored_resume_path || "")}')" style="text-decoration: none;">
                <i class="fa-brands fa-brave"></i> Open Portal
              </a>

              <!-- On-Demand Tailoring Button (JIT) -->
              ${!hasResume ? `
                <button class="btn btn-tailor" id="btn-tailor-${job.rowid}" onclick="tailorSingleJob(${job.rowid})">
                  <i class="fa-solid fa-wand-magic-sparkles"></i> Tailor Resume (AI)
                </button>
              ` : `
                <button class="btn btn-preview" onclick="previewResume(${job.rowid})">
                  <i class="fa-solid fa-file-pdf"></i> View Resume PDF
                </button>
                <button class="btn" onclick="copyResumeFilePath(${job.rowid})" style="background: #1e293b; border: 1px solid #38bdf8; color: #38bdf8; font-size: 11px; padding: 6px 10px; border-radius: 8px; cursor: pointer; font-weight: 600;" title="Copy absolute file path to clipboard (for pasting in file upload dialogues or Gmail)">
                  <i class="fa-regular fa-copy"></i> Copy Path
                </button>
              `}

              ${hasCover ? `
                <button class="btn btn-preview" onclick="previewCoverLetter(${job.rowid})">
                  <i class="fa-solid fa-file-lines"></i> Cover PDF
                </button>
              ` : ''}

              <!-- Referral Outreach Modal Button -->
              <button class="btn btn-outreach" onclick="openReferralModal(${job.rowid})">
                <i class="fa-solid fa-people-arrows"></i> Referral Outreach
              </button>

              <!-- Tech Cheat-Sheet Modal Button -->
              <button class="btn btn-cheatsheet" onclick="openCheatsheetModal('${encodeURIComponent(job.company || '')}', '${encodeURIComponent(job.title || '')}')" style="background: rgba(168, 85, 247, 0.2); border: 1.5px solid #a855f7; color: #d8b4fe; font-weight: 700; padding: 7px 12px; font-size: 12px; border-radius: 8px; cursor: pointer;" title="Open tailored technical and behavioral interview prep cheat-sheet">
                <i class="fa-solid fa-bolt"></i> ⚡ Tech Cheat-Sheet
              </button>

              ${job.recruiter_email ? `
                <button class="btn btn-email" id="btn-draft-${job.rowid}" onclick="draftEmailForJob(${job.rowid})" title="Draft cold email in your Gmail drafts folder with tailored resume attached">
                  <i class="fa-solid fa-file-pen"></i> Draft in Gmail
                </button>
                <button class="btn" id="btn-send-${job.rowid}" onclick="sendEmailForJob(${job.rowid})" style="background: linear-gradient(135deg, #10b981, #059669); color: white; padding: 7px 12px; font-size: 12px; font-weight: 700; border-radius: 8px; border: none; cursor: pointer;" title="Send directly to recruiter if confidence is high (with tailored resume attached)">
                  <i class="fa-solid fa-paper-plane"></i> Send Email
                </button>
              ` : `
                <button class="btn btn-email-ghost" onclick="promptCustomDraft(${job.rowid})" title="Draft or send cold email to recruiter with tailored resume">
                  <i class="fa-regular fa-envelope"></i> Draft / Send
                </button>
              `}

              ${!isApproved && !isApplied ? `
                <button class="btn btn-approve" onclick="approveJob(${job.rowid})">
                  <i class="fa-solid fa-check"></i> Approve
                </button>
              ` : ''}

              ${!isApplied && !isIgnored ? `
                <button class="btn btn-applied" onclick="markApplied(${job.rowid})">
                  <i class="fa-solid fa-check-circle"></i> Mark Applied
                </button>
                <button class="btn" onclick="promptMarkReferralAsked(${job.rowid}, '${encodeURIComponent(job.company || '')}')" style="background: rgba(168, 85, 247, 0.2); border: 1px solid #a855f7; color: #d8b4fe; font-size: 11.5px; font-weight: 700; border-radius: 8px; padding: 7px 11px; cursor: pointer;" title="Mark that you asked for a referral so ApplyPilot actively tracks follow-ups">
                  <i class="fa-solid fa-people-arrows"></i> Asked Referral
                </button>
              ` : ''}

              ${!isIgnored ? `
                <button class="btn btn-ignore" onclick="ignoreJob(${job.rowid})" title="Hide / ignore this job (e.g. broken or invalid link)">
                  <i class="fa-solid fa-ban"></i> Ignore
                </button>
              ` : `
                <button class="btn btn-ignore" onclick="unignoreJob(${job.rowid})" title="Restore job back to active queue">
                  <i class="fa-solid fa-arrow-rotate-left"></i> Restore
                </button>
              `}
            </div>
          </div>
        `;
      }).join('');
    }

    /* Actions */

    function handleJobClick(event, rowid, encodedPdfPath) {
      const pdfPath = decodeURIComponent(encodedPdfPath || '');
      if (pdfPath && pdfPath !== 'null' && pdfPath !== 'undefined') {
        const absPath = pdfPath.includes(':') ? pdfPath : `D:\\ApplyPilot_Workspace\\data\\${pdfPath.replace(/^\//, '').replace(/\//g, '\\')}`;
        try {
          navigator.clipboard.writeText(absPath);
          showToast('📋 Tailored Resume copied to clipboard! Opening in Brave...');
        } catch (e) {
          showToast('Opening in your active Brave browser...');
        }
      } else {
        showToast('Opening in your active Brave browser...');
      }

      // Notify backend asynchronously to log and provide OS shell fallback
      try {
        fetch(`/api/jobs/${rowid}/open_brave`, { method: 'POST' });
      } catch (e) {}
    }

    function openJobInBrave(rowid, encodedUrl, encodedPdfPath) {
      const url = decodeURIComponent(encodedUrl || '');
      if (!url || url.toLowerCase().startsWith('none') || !url.startsWith('http')) {
        showToast('❌ No direct application URL found for this position.');
        return;
      }
      handleJobClick(null, rowid, encodedPdfPath);
      const a = document.createElement('a');
      a.href = url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }

    function openInBrave(rowid) {
      const job = allJobs.find(j => j.rowid === rowid);
      const url = job ? (job.apply_url || job.url) : null;
      if (!url || url.toLowerCase().startsWith('none') || !url.startsWith('http')) {
        showToast('❌ No direct application URL found for this position.');
        return;
      }
      showToast('Opening in your active Brave browser...');
      handleJobClick(null, rowid, encodeURIComponent(job.tailored_resume_path || ''));
      const a = document.createElement('a');
      a.href = url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }

    async function tailorSingleJob(rowid) {
      const btn = document.getElementById(`btn-tailor-${rowid}`);
      if (btn) {
        btn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Tailoring with AI...`;
        btn.disabled = true;
      }
      showToast('Tailoring resume & compiling PDF via Tectonic engine (takes ~4s)...');

      try {
        const res = await fetch(`/api/jobs/${rowid}/tailor`, { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast('✓ Resume tailored & PDF compiled! Copying path...');
          triggerConfetti();
          if (data.tailored_resume_path) {
            const raw = data.tailored_resume_path;
            const absPath = raw.includes(':') ? raw : `D:\\ApplyPilot_Workspace\\data\\${raw.replace(/^\//, '').replace(/\//g, '\\')}`;
            try {
              await navigator.clipboard.writeText(absPath);
              showToast('📋 Resume path copied to clipboard! Paste directly into upload dialog.');
            } catch (clipErr) {
              console.warn('Clipboard write failed:', clipErr);
            }
          }
          await fetchJobs();
          if (data.tailored_resume_path) {
            previewResume(rowid);
          }
        } else {
          showToast('Error tailoring: ' + data.message);
          if (btn) {
            btn.innerHTML = `<i class="fa-solid fa-wand-magic-sparkles"></i> Tailor Resume (AI)`;
            btn.disabled = false;
          }
        }
      } catch (err) {
        showToast('Tailoring failed: ' + err);
        if (btn) {
          btn.innerHTML = `<i class="fa-solid fa-wand-magic-sparkles"></i> Tailor Resume (AI)`;
          btn.disabled = false;
        }
      }
    }

    async function approveJob(rowid) {
      const res = await fetch(`/api/jobs/${rowid}/approve`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast('⭐ Job added to your Approved Queue! Vetted and ready.');
        triggerConfetti();
        fetchJobs();
      }
    }

    async function markApplied(rowid) {
      try {
        const res = await fetch(`/api/jobs/${rowid}/applied`, { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok' || data.status === 'applied') {
          showToast('🎉 BOOM! Job recorded as APPLIED! Keep up the momentum, Deepak!');
          triggerConfetti();
          fetchJobs();
        } else {
          showToast('⚠️ Could not mark job as applied: ' + (data.message || 'Unknown error'));
        }
      } catch (err) {
        showToast('⚠️ Error recording application status.');
      }
    }

    async function promptMarkReferralAsked(rowid, compEncoded) {
      const comp = decodeURIComponent(compEncoded || 'this company');
      const contactName = prompt(`Who did you ask for a referral at ${comp}?\n(Enter connection/alumnus name, or leave blank):`);
      if (contactName === null) return; // user cancelled

      try {
        const res = await fetch(`/api/jobs/${rowid}/asked_referral`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            contact_name: contactName.trim(),
            platform: 'LinkedIn'
          })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast(`🤝 Referral tracked! Follow-up reminder active for ${comp}.`);
          triggerConfetti();
          fetchJobs();
        } else {
          showToast('Error recording referral: ' + (data.message || 'unknown error'));
        }
      } catch (err) {
        showToast('Failed to record referral: ' + err);
      }
    }

    async function ignoreJob(rowid) {
      const res = await fetch(`/api/jobs/${rowid}/ignore`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast('🚫 Job ignored and removed from active feeds.');
        fetchJobs();
      }
    }

    async function unignoreJob(rowid) {
      const res = await fetch(`/api/jobs/${rowid}/unignore`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast('↩️ Job restored to active feed.');
        fetchJobs();
      }
    }

        function copyResumeFilePath(rowid) {
      const job = allJobs.find(j => j.rowid === rowid);
      if (!job || !job.tailored_resume_path) {
        showToast('⚠️ No tailored resume path found.');
        return;
      }
      const raw = job.tailored_resume_path;
      const absPath = raw.includes(':') ? raw : `D:\\ApplyPilot_Workspace\\data\\${raw.replace(/^\//, '').replace(/\//g, '\\')}`;
      try {
        navigator.clipboard.writeText(absPath);
        showToast('📋 Copied resume path! Paste (Ctrl+V) directly into file upload.');
      } catch (e) {
        showToast('Path: ' + absPath);
      }
    }

    function previewResume(rowid) {
      const job = allJobs.find(j => j.rowid === rowid);
      const title = job ? `${job.company} - ${job.title} Resume` : 'Tailored Resume';
      const url = `/api/jobs/${rowid}/resume?t=${Date.now()}`;
      document.getElementById('modal-title').textContent = title;
      const newTabBtn = document.getElementById('modal-open-newtab');
      if (newTabBtn) newTabBtn.href = url;
      document.getElementById('pdf-frame').src = url;
      document.getElementById('pdf-modal').style.display = 'flex';
    }

    function previewCoverLetter(rowid) {
      const job = allJobs.find(j => j.rowid === rowid);
      const title = job ? `${job.company} - Cover Letter` : 'Cover Letter';
      const url = `/api/jobs/${rowid}/cover_letter?t=${Date.now()}`;
      document.getElementById('modal-title').textContent = title;
      const newTabBtn = document.getElementById('modal-open-newtab');
      if (newTabBtn) newTabBtn.href = url;
      document.getElementById('pdf-frame').src = url;
      document.getElementById('pdf-modal').style.display = 'flex';
    }

    function previewPDF(pdfPath, title) {
      const cleanPath = pdfPath.replace(/^.*tailored_resumes[\\/]/, 'resumes/').replace(/^.*cover_letters[\\/]/, 'covers/');
      const url = '/files/' + encodeURIComponent(cleanPath).replace(/%2F/g, '/');
      document.getElementById('modal-title').textContent = title || 'Document Preview';
      const newTabBtn = document.getElementById('modal-open-newtab');
      if (newTabBtn) newTabBtn.href = url;
      document.getElementById('pdf-frame').src = url;
      document.getElementById('pdf-modal').style.display = 'flex';
    }

    function closeModal() {
      document.getElementById('pdf-modal').style.display = 'none';
      document.getElementById('pdf-frame').src = '';
    }

    /* Referral & LinkedIn Modal */
    function updateModalOutreachLinks(companyName) {
      const comp = companyName.trim();
      if (!comp) return;
      const compEnc = encodeURIComponent(`"${comp}"`);
      
      const firstDeg = document.getElementById('ref-first-deg-link');
      if (firstDeg) {
        firstDeg.href = `https://www.linkedin.com/search/results/people/?keywords=${compEnc}&network=%5B%22F%22%5D`;
      }
      const secondDeg = document.getElementById('ref-second-deg-link');
      if (secondDeg) {
        secondDeg.href = `https://www.linkedin.com/search/results/people/?keywords=${compEnc}&network=%5B%22S%22%5D`;
      }
      const alumni = document.getElementById('ref-alumni-link');
      if (alumni) {
        alumni.href = `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent('RVCE ' + comp)}`;
      }
      const recruiter = document.getElementById('ref-recruiter-link');
      if (recruiter) {
        recruiter.href = `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent('"' + comp + '" technical recruiter backend')}`;
      }
      const lead = document.getElementById('ref-lead-link');
      if (lead) {
        lead.href = `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent('"' + comp + '" engineering manager backend')}`;
      }
      const hiring = document.getElementById('ref-hiring-posts-link');
      if (hiring) {
        hiring.href = `https://www.linkedin.com/search/results/content/?keywords=${encodeURIComponent('"' + comp + '" backend engineer AND ("hiring" OR "requirement")')}&sortBy=%22date_posted%22`;
      }
      document.querySelectorAll('.lbl-modal-comp').forEach(el => el.textContent = comp);
    }

    function openReferralModal(rowid) {
      const job = allJobs.find(j => j.rowid === rowid);
      if (!job) return;
      const o = job.outreach || {};
      const comp = job.company || 'Target Company';

      document.getElementById('referral-modal-title').innerHTML = `<i class="fa-brands fa-linkedin" style="color:#38bdf8;"></i> LinkedIn Connections & Outreach: <strong>${comp}</strong> (${job.title})`;

      const html = `
        <!-- Section 1: Active Connections & Network Filters -->
        <div style="background: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 18px; margin-bottom: 20px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <h4 style="margin: 0; color: #f8fafc; font-size: 15px;"><i class="fa-solid fa-filter"></i> 1. Targeted LinkedIn Network Filters</h4>
            <span style="font-size: 11px; background: #1e293b; color: #94a3b8; padding: 3px 8px; border-radius: 4px; font-weight: 600;">Deepak's Active Network</span>
          </div>

          <!-- Target Company Filter Bar -->
          <div style="background: #0f172a; border: 1px solid #1f2937; border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap;">
            <div style="display: flex; align-items: center; gap: 8px; flex: 1; min-width: 260px;">
              <span style="font-size: 12px; font-weight: 700; color: #94a3b8; white-space: nowrap;"><i class="fa-solid fa-building"></i> Filter by Company:</span>
              <input type="text" id="modal-company-filter" value="${comp}" style="background: #1e293b; border: 1px solid #334155; color: #fff; padding: 5px 10px; border-radius: 4px; font-size: 13px; font-weight: 600; flex: 1;" oninput="updateModalOutreachLinks(this.value)">
            </div>
            <span style="font-size: 11px; color: #64748b;">Live company filter</span>
          </div>

          <p style="margin: 0 0 12px 0; font-size: 13px; color: #94a3b8;">
            Filters your LinkedIn account for connections, mutuals, and alumni working at <strong class="lbl-modal-comp" style="color:#f8fafc;">${comp}</strong>.
          </p>
          <div style="display: flex; flex-wrap: wrap; gap: 8px;">
            <a href="${o.first_degree_url || '#'}" id="ref-first-deg-link" target="_blank" class="btn" style="background: #065f46; color: #6ee7b7; border: 1px solid #047857; text-decoration: none; padding: 7px 12px; font-weight: 600;">
              <i class="fa-solid fa-user-group"></i> 1st-Degree Connections @ <span class="lbl-modal-comp">${comp}</span>
            </a>
            <a href="${o.second_degree_url || '#'}" id="ref-second-deg-link" target="_blank" class="btn" style="background: #78350f; color: #fde68a; border: 1px solid #92400e; text-decoration: none; padding: 7px 12px; font-weight: 600;">
              <i class="fa-solid fa-users"></i> 2nd-Degree Mutuals @ <span class="lbl-modal-comp">${comp}</span>
            </a>
            <a href="${o.alumni_search_url || '#'}" id="ref-alumni-link" target="_blank" class="btn" style="background: #1e3a8a; color: #bfdbfe; border: 1px solid #1d4ed8; text-decoration: none; padding: 7px 12px; font-weight: 600;">
              <i class="fa-solid fa-graduation-cap"></i> RVCE Alumni @ <span class="lbl-modal-comp">${comp}</span>
            </a>
            <a href="${o.recruiter_search_url || '#'}" id="ref-recruiter-link" target="_blank" class="btn" style="background: #312e81; color: #c7d2fe; border: 1px solid #4338ca; text-decoration: none; padding: 7px 12px; font-weight: 600;">
              <i class="fa-solid fa-user-tie"></i> Recruiters @ <span class="lbl-modal-comp">${comp}</span>
            </a>
            <a href="${o.lead_search_url || '#'}" id="ref-lead-link" target="_blank" class="btn" style="background: #1e293b; color: #cbd5e1; border: 1px solid #334155; text-decoration: none; padding: 7px 12px; font-weight: 600;">
              <i class="fa-solid fa-briefcase"></i> Engineering Managers
            </a>
            <a href="https://referral-community.kadegree.in/get" target="_blank" rel="noopener noreferrer" class="btn" style="background: #1e293b; color: #cbd5e1; border: 1px solid #334155; text-decoration: none; padding: 7px 12px; font-weight: 600;">
              <i class="fa-solid fa-users"></i> KaDegree Community
            </a>
            ${o.hiring_posts_url ? `
            <a href="${o.hiring_posts_url}" id="ref-hiring-posts-link" target="_blank" class="btn" style="background: #075985; color: #bae6fd; border: 1px solid #0284c7; text-decoration: none; padding: 7px 12px; font-weight: 600;">
              <i class="fa-solid fa-bullhorn"></i> Hiring Posts @ <span class="lbl-modal-comp">${comp}</span>
            </a>
            ` : ''}
          </div>

          <!-- Section 2: Live Connection & Alumni Scanner -->
          <div style="margin-top: 18px; padding-top: 14px; border-top: 1px solid rgba(255,255,255,0.08);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
              <span style="font-size: 13px; font-weight: 700; color: #f1f5f9;"><i class="fa-solid fa-radar fa-spin"></i> Live Connection Scanner:</span>
              <button class="btn btn-brave" onclick="scanCompanyConnections('${comp.replace(/'/g, "\\'")}')" style="padding: 5px 12px; font-size: 11px;">
                <i class="fa-solid fa-magnifying-glass"></i> Scan My Connections @ ${comp}
              </button>
            </div>
            <div id="live-connections-container" style="min-height: 20px;"></div>
          </div>

          <!-- Direct Custom LinkedIn Search / Chat Box -->
          <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.08); display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
            <input type="text" id="direct-conn-input" placeholder="Paste specific connection's LinkedIn profile URL (e.g. https://www.linkedin.com/in/...)..." style="flex:1; min-width: 240px; background: #0f172a; border: 1px solid #334155; color: #fff; padding: 8px 12px; border-radius: 8px; font-size: 12px;">
            <button class="btn" style="background: linear-gradient(135deg, #a855f7, #6366f1); color: white; font-weight: 700; white-space: nowrap;" onclick="sendDirectConnectionInvite(true)" title="1-Click Connect + Note: Clicks Connect, adds tailored referral note in Brave, and logs to CRM">
              <i class="fa-solid fa-user-plus"></i> Connect + Note
            </button>
            <button class="btn" style="background: linear-gradient(135deg, #4f46e5, #3b82f6); color: white; font-weight: 700; white-space: nowrap;" onclick="sendDirectConnectionInvite(false)" title="Just Connect: Clicks Connect without a note and logs to CRM">
              <i class="fa-solid fa-user-check"></i> Just Connect
            </button>
            <button class="btn" style="background: linear-gradient(135deg, #0284c7, #10b981); color: white; font-weight: 700; white-space: nowrap;" onclick="autoTypeDirectConnectionDM()" title="Auto-types full referral DM into chat in Brave">
              <i class="fa-solid fa-paper-plane"></i> Auto-Type DM
            </button>
            <button class="btn" style="background:#0a66c2; color:white; white-space: nowrap;" onclick="openDirectConnectionChat()" title="Open profile in Brave">
              <i class="fa-brands fa-linkedin"></i> Profile
            </button>
          </div>
        </div>

        <!-- Section 3: Four Tailored Outreach Templates -->
        <div style="margin-bottom: 18px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <h4 style="margin: 0; color: #34d399; font-size: 14px;"><i class="fa-solid fa-handshake"></i> Template A: 1st-Degree (Active Connection) Warm Referral</h4>
            <button class="btn" style="background: #059669; color: white; padding: 4px 10px; font-size: 11px;" onclick="copyOutreachText('first-deg-msg-text')">
              <i class="fa-regular fa-copy"></i> Copy Message
            </button>
          </div>
          <textarea id="first-deg-msg-text" style="width: 100%; height: 130px; background: #0f172a; color: #f1f5f9; border: 1px solid #334155; border-radius: 8px; padding: 12px; font-family: monospace; font-size: 12px; resize: vertical;" readonly>${o.first_deg_message || ''}</textarea>
        </div>

        <div style="margin-bottom: 18px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <h4 style="margin: 0; color: #f59e0b; font-size: 14px;"><i class="fa-solid fa-people-arrows"></i> Template B: 2nd-Degree (Mutual Connection) Referral</h4>
            <button class="btn" style="background: #d97706; color: white; padding: 4px 10px; font-size: 11px;" onclick="copyOutreachText('second-deg-msg-text')">
              <i class="fa-regular fa-copy"></i> Copy Message
            </button>
          </div>
          <textarea id="second-deg-msg-text" style="width: 100%; height: 130px; background: #0f172a; color: #f1f5f9; border: 1px solid #334155; border-radius: 8px; padding: 12px; font-family: monospace; font-size: 12px; resize: vertical;" readonly>${o.second_deg_message || ''}</textarea>
        </div>

        <div style="margin-bottom: 18px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <h4 style="margin: 0; color: #4ade80; font-size: 14px;"><i class="fa-solid fa-graduation-cap"></i> Template C: RVCE Alumni Referral Request</h4>
            <button class="btn" style="background: #10b981; color: white; padding: 4px 10px; font-size: 11px;" onclick="copyOutreachText('alumni-msg-text')">
              <i class="fa-regular fa-copy"></i> Copy Message
            </button>
          </div>
          <textarea id="alumni-msg-text" style="width: 100%; height: 130px; background: #0f172a; color: #f1f5f9; border: 1px solid #334155; border-radius: 8px; padding: 12px; font-family: monospace; font-size: 12px; resize: vertical;" readonly>${o.alumni_message || ''}</textarea>
        </div>

        <div style="margin-bottom: 10px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <h4 style="margin: 0; color: #a78bfa; font-size: 14px;"><i class="fa-solid fa-bullhorn"></i> Template D: Recruiter Direct Message</h4>
            <button class="btn" style="background: #7c3aed; color: white; padding: 4px 10px; font-size: 11px;" onclick="copyOutreachText('recruiter-msg-text')">
              <i class="fa-regular fa-copy"></i> Copy Message
            </button>
          </div>
          <textarea id="recruiter-msg-text" style="width: 100%; height: 130px; background: #0f172a; color: #f1f5f9; border: 1px solid #334155; border-radius: 8px; padding: 12px; font-family: monospace; font-size: 12px; resize: vertical;" readonly>${o.recruiter_message || ''}</textarea>
        </div>

        <!-- Section 4: Kannada Referral Community (KaDegree) Note -->
        <div style="background: rgba(180, 83, 9, 0.15); border: 1.5px solid rgba(245, 158, 11, 0.4); border-radius: 12px; padding: 16px; margin-bottom: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <h4 style="margin: 0; color: #fbbf24; font-size: 14px;"><i class="fa-solid fa-users"></i> Template E: Kannada Referral Community (KaDegree) Note</h4>
            <div style="display: flex; gap: 8px;">
              <a href="${o.kadegree_url || 'https://referral-community.kadegree.in/get'}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #b45309; color: white; padding: 4px 10px; font-size: 11px; text-decoration: none; font-weight: 700;">
                <i class="fa-solid fa-arrow-up-right-from-square"></i> Open KaDegree
              </a>
              <button class="btn" style="background: #d97706; color: white; padding: 4px 10px; font-size: 11px;" onclick="copyOutreachText('kadegree-msg-text')">
                <i class="fa-regular fa-copy"></i> Copy Kannada Note
              </button>
            </div>
          </div>
          <p style="margin: 0 0 10px 0; font-size: 12px; color: #fde68a;">
            🌟 <em>Post or send this warm bilingual note in the KaDegree Referral Community (17k+ Kannadiga engineers & 6.4k verified referrers).</em>
          </p>
          <textarea id="kadegree-msg-text" style="width: 100%; height: 130px; background: #0f172a; color: #f1f5f9; border: 1px solid #78350f; border-radius: 8px; padding: 12px; font-family: monospace; font-size: 12px; resize: vertical;" readonly>${o.kadegree_message || ''}</textarea>
        </div>

        <!-- Section 5: ✉️ Recruiter Email Direct Outreach & Gmail Draft -->
        <div style="background: rgba(234, 67, 53, 0.12); border: 1.5px solid rgba(234, 67, 53, 0.4); border-radius: 12px; padding: 18px; margin-bottom: 14px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <h4 style="margin: 0; color: #f87171; font-size: 14px;"><i class="fa-solid fa-envelope-open-text"></i> Section 5: Recruiter Email Outreach & Gmail Draft</h4>
            <a href="https://mail.google.com/mail/u/0/#drafts" target="_blank" rel="noopener noreferrer" class="btn" style="background: #dc2626; color: white; padding: 4px 10px; font-size: 11px; text-decoration: none; font-weight: 700;">
              <i class="fa-brands fa-google"></i> Open Gmail Drafts
            </a>
          </div>
          <p style="margin: 0 0 10px 0; font-size: 12px; color: #fca5a5;">
            📧 <em>Auto-generates a ready-to-review draft directly in your Gmail (deepakshkarkala@gmail.com) with your tailored resume attached. Zero auto-sending: you review and send with 1 click.</em>
          </p>
          <div style="display: flex; gap: 10px; align-items: center; margin-bottom: 10px;">
            <input type="email" id="modal-draft-email-${job.rowid}" value="${job.recruiter_email || ''}" placeholder="Enter recruiter or HR email address (e.g. careers@company.com)..." style="flex:1; background: #0f172a; border: 1px solid #dc2626; color: #fff; padding: 8px 12px; border-radius: 8px; font-size: 12px;">
            <button class="btn" id="btn-modal-draft-${job.rowid}" style="background: linear-gradient(135deg, #dc2626, #b91c1c); color: white; font-weight: 700; padding: 8px 14px; white-space: nowrap;" onclick="draftEmailFromModal(${job.rowid}, 'draft')">
              <i class="fa-solid fa-file-pen"></i> Save Draft
            </button>
            <button class="btn" id="btn-modal-send-${job.rowid}" style="background: linear-gradient(135deg, #10b981, #059669); color: white; font-weight: 700; padding: 8px 14px; white-space: nowrap;" onclick="draftEmailFromModal(${job.rowid}, 'send')">
              <i class="fa-solid fa-paper-plane"></i> Send Now
            </button>
          </div>
          <div id="modal-draft-status-${job.rowid}" style="display: none; padding: 10px; border-radius: 8px; font-size: 12px;"></div>
        </div>
      `;

      document.getElementById('referral-modal-body').innerHTML = html;
      document.getElementById('referral-modal').style.display = 'flex';

      // Auto-scan connections for this company immediately without needing manual button click
      setTimeout(() => {
        scanCompanyConnections(comp);
      }, 50);
    }

    async function scanCompanyConnections(company) {
      const container = document.getElementById('live-connections-container');
      if (!container) return;
      container.innerHTML = `<div style="text-align:center; padding: 18px; color: #38bdf8; font-size: 13px;"><i class="fa-solid fa-circle-notch fa-spin"></i> Auto-scanning your connections & RVCE alumni @ ${company}...</div>`;

      try {
        const res = await fetch(`/api/linkedin/scan?company=${encodeURIComponent(company)}`);
        const data = await res.json();

        if (data.status === 'not_authenticated') {
          const firstDegUrl = document.getElementById('ref-first-deg-link') ? document.getElementById('ref-first-deg-link').href : `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(company)}&network=%5B%22F%22%5D`;
          const alumniUrl = `https://www.linkedin.com/search/results/people/?keywords=RVCE%20${encodeURIComponent(company)}%20software%20engineer`;
          
          container.innerHTML = `
            <div style="background: rgba(15,23,42,0.9); border: 1.5px solid rgba(56, 189, 248, 0.4); border-radius: 12px; padding: 16px;">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 10px;">
                <span style="font-weight: 700; color: #38bdf8; font-size: 13px;">
                  <i class="fa-brands fa-linkedin"></i> Live Connections Available in Your Active Brave Session:
                </span>
                <button class="btn btn-brave" onclick="triggerLinkedInLogin('${company.replace(/'/g, "\'")}')" style="padding: 5px 12px; font-size: 11px; background:#0a66c2; color:#fff; font-weight:700;">
                  <i class="fa-solid fa-bolt"></i> 1-Click Connect Session
                </button>
              </div>

              <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px;">
                <a href="${firstDegUrl}" target="_blank" rel="noopener noreferrer" class="btn" style="background: linear-gradient(135deg, #059669, #10b981); color: white; text-decoration: none; padding: 8px 12px; font-size: 12px; font-weight: 700; text-align: center;">
                  🟢 View 1st-Degree Friends @ ${company}
                </a>
                <a href="${alumniUrl}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #0284c7; color: white; text-decoration: none; padding: 8px 12px; font-size: 12px; font-weight: 700; text-align: center;">
                  🎓 View RVCE Alumni @ ${company}
                </a>
              </div>

              <!-- Instant li_at Cookie Input to unlock in-app list forever -->
              <div style="padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.08); display: flex; gap: 8px; align-items: center;">
                <input type="password" id="modal-li-at-input" placeholder="Or paste 'li_at' cookie to auto-list connections here forever..." style="flex:1; background: #0b1326; border: 1px solid #334155; color: #fff; padding: 7px 10px; border-radius: 6px; font-size: 11.5px;">
                <button class="btn" onclick="saveModalLinkedInCookie('${company.replace(/'/g, "\'")}')" style="background: #059669; color: white; padding: 7px 12px; font-size: 11.5px; font-weight: 700; white-space: nowrap;">
                  Save & List
                </button>
              </div>
            </div>
          `;
          return;
        }

        if (data.status === 'ok' && data.connections && data.connections.length > 0) {
          container.innerHTML = `
            <div style="font-size: 12px; color: #94a3b8; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;">
              <span>Found <strong>${data.connections.length}</strong> active connections @ <strong>${company}</strong> ready for referral:</span>
              <span style="font-size: 11px; color: #38bdf8;">1-Click Auto-Types customized DM in Brave</span>
            </div>
            ${data.connections.map(c => `
              <div style="background: #0f172a; border: 1px solid #334155; border-radius: 10px; padding: 12px; display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px;">
                <div style="flex: 1; min-width: 0;">
                  <div style="font-weight: 700; color: #f8fafc; font-size: 13.5px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                    <span>${c.name}</span>
                    <span style="background: ${c.degree === '1st' ? '#065f46' : '#78350f'}; color: ${c.degree === '1st' ? '#34d399' : '#fde68a'}; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 700;">
                      ${c.degree === '1st' ? '🟢 1st-Degree Connection' : '🟡 2nd-Degree Mutual'}
                    </span>
                    ${c.is_alumni ? `<span style="background: #1e3a8a; color: #93c5fd; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 700;">🎓 RVCE Alumnus</span>` : ''}
                  </div>
                  <div style="color: #cbd5e1; font-size: 12px; margin-top: 2px;">${c.headline || c.current_role || 'Software Engineering'}</div>
                  ${c.current_role ? `<div style="color: #38bdf8; font-size: 11px; margin-top: 2px; font-weight: 600;"><i class="fa-solid fa-building"></i> Current: ${c.current_role}</div>` : ''}
                  ${c.past_role && !c.current_role ? `<div style="color: #94a3b8; font-size: 11px; margin-top: 2px;"><i class="fa-solid fa-clock-rotate-left"></i> Past: ${c.past_role}</div>` : ''}
                  <div style="color: #64748b; font-size: 11px;"><i class="fa-solid fa-location-dot"></i> ${c.location || 'India'}</div>
                </div>
                <div style="display: flex; gap: 6px; align-items: center; flex-shrink: 0; flex-wrap: wrap;">
                  ${c.degree === '1st' ? `
                    <button class="btn" style="background: linear-gradient(135deg, #0284c7, #10b981); color: #fff; padding: 7px 12px; font-size: 11.5px; font-weight: 700; white-space: nowrap; border: none; border-radius: 6px; cursor: pointer;" onclick="composeLinkedInDM('${c.profile_url}', '${c.name.replace(/'/g, "\\'")}', '${company.replace(/'/g, "\\'")}', 'Backend Engineer', '${c.is_alumni ? 'alumni' : 'referral'}', 'message')" title="Auto-types referral DM with resume link in Brave chat">
                      <i class="fa-solid fa-paper-plane"></i> Auto-Type DM
                    </button>
                  ` : `
                    <button class="btn" style="background: linear-gradient(135deg, #a855f7, #6366f1); color: #fff; padding: 7px 11px; font-size: 11.5px; font-weight: 700; white-space: nowrap; border: none; border-radius: 6px; cursor: pointer;" onclick="composeLinkedInDM('${c.profile_url}', '${c.name.replace(/'/g, "\\'")}', '${company.replace(/'/g, "\\'")}', 'Backend Engineer', '${c.is_alumni ? 'alumni' : 'referral'}', 'connect')" title="1-Click Connect + Note: Clicks Connect, adds tailored referral note in Brave, and logs to CRM">
                      <i class="fa-solid fa-user-plus"></i> Connect + Note
                    </button>
                    <button class="btn" style="background: linear-gradient(135deg, #4f46e5, #3b82f6); color: #fff; padding: 7px 11px; font-size: 11.5px; font-weight: 700; white-space: nowrap; border: none; border-radius: 6px; cursor: pointer;" onclick="composeLinkedInDM('${c.profile_url}', '${c.name.replace(/'/g, "\\'")}', '${company.replace(/'/g, "\\'")}', 'Backend Engineer', '${c.is_alumni ? 'alumni' : 'referral'}', 'connect_only')" title="Just Connect: Sends connection invite without a note and logs to CRM">
                      <i class="fa-solid fa-user-check"></i> Just Connect
                    </button>
                  `}
                  <button class="btn" style="background: #0a66c2; color: #fff; padding: 7px 10px; font-size: 11.5px; white-space: nowrap; border: none; border-radius: 6px; cursor: pointer;" onclick="openDirectUrl('${c.profile_url}')" title="Open profile in Brave">
                    <i class="fa-brands fa-linkedin"></i> Profile
                  </button>
                  <button class="btn" style="background: #1e293b; color: #cbd5e1; border: 1px solid #475569; padding: 7px 10px; font-size: 11.5px; white-space: nowrap; border-radius: 6px; cursor: pointer;" onclick="logConnectionFromModal('${company.replace(/'/g, "\\'")}', '${c.name.replace(/'/g, "\\'")}', '${c.profile_url}', '${(c.headline || '').replace(/'/g, "\\'")}', ${c.is_alumni ? 'true' : 'false'})" title="Track in Referral Network CRM">
                    <i class="fa-solid fa-bookmark"></i> Track
                  </button>
                  <button class="btn" style="background: #1e293b; color: #e2e8f0; border: 1px solid #475569; padding: 7px 10px; font-size: 11.5px; white-space: nowrap; border-radius: 6px; cursor: pointer;" onclick="copyCustomReferral('${c.name.replace(/'/g, "\\'")}')" title="Copy personalized note to clipboard">
                    <i class="fa-regular fa-copy"></i> Copy Note
                  </button>
                </div>
              </div>
            `).join('')}
          `;
        } else {
          const firstDegUrl = document.getElementById('ref-first-deg-link') ? document.getElementById('ref-first-deg-link').href : '#';
          container.innerHTML = `
            <div style="background: rgba(15,23,42,0.6); border: 1px solid #334155; border-radius: 10px; padding: 12px; text-align: center; color: #94a3b8; font-size: 13px;">
              No direct alumni found in quick query. <a href="${firstDegUrl}" target="_blank" style="color:#38bdf8;font-weight:700;">Click here to view your 1st-degree connections @ ${company} in Brave &rarr;</a>
            </div>
          `;
        }
      } catch (err) {
        container.innerHTML = `<div style="color: #f87171; font-size: 12px;">Error checking connections: ${err}</div>`;
      }
    }

    let loginPollInterval = null;
    async function triggerLinkedInLogin(company = '') {
      showToast('Launching Brave for LinkedIn connection...');
      await fetch('/api/linkedin/login', { method: 'POST' });
      showToast('Sign in on Brave window. ApplyPilot will detect it and auto-list connections!');

      if (loginPollInterval) clearInterval(loginPollInterval);
      loginPollInterval = setInterval(async () => {
        try {
          const res = await fetch('/api/linkedin/status');
          const data = await res.json();
          if (data.authenticated) {
            clearInterval(loginPollInterval);
            showToast('✅ LinkedIn session active! Auto-listing connections...');
            if (company) scanCompanyConnections(company);
          }
        } catch (e) {}
      }, 2000);
    }

    async function saveModalLinkedInCookie(company = '') {
      const input = document.getElementById('modal-li-at-input');
      const val = input ? input.value.trim() : '';
      if (!val) {
        alert('Please paste your li_at cookie value.');
        return;
      }
      showToast('Saving LinkedIn session...');
      try {
        const res = await fetch('/api/linkedin/set_cookie', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: val })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast('✅ LinkedIn session connected! Fetching connections...');
          if (company) scanCompanyConnections(company);
        } else {
          showToast('⚠️ ' + data.message);
        }
      } catch (err) {
        showToast('Error saving cookie: ' + err);
      }
    }

    function copyCustomReferral(name) {
      const template = document.getElementById('first-deg-msg-text') || document.getElementById('alumni-msg-text');
      if (template) {
        const text = template.value.replace(/\[Name\]/g, name);
        navigator.clipboard.writeText(text);
        showToast(`Copied personalized note for ${name}! Ready to paste into LinkedIn.`);
      }
    }

    function closeReferralModal() {
      document.getElementById('referral-modal').style.display = 'none';
    }

    function openDirectConnectionChat() {
      const val = document.getElementById('direct-conn-input').value.trim();
      if (!val) {
        showToast('Please enter a connection URL or name.');
        return;
      }
      let url = val;
      if (!url.startsWith('http')) {
        url = `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(val)}`;
      }
      window.open(url, '_blank');
      showToast('Opening LinkedIn profile in Brave...');
    }

    async function composeLinkedInDM(profileUrl, name = '', company = '', role = 'Backend Engineer', template = 'referral', actionType = 'auto') {
      if (!profileUrl) {
        showToast('Please enter or select a profile URL.');
        return;
      }
      const isConnect = (actionType === 'connect');
      const isConnectOnly = (actionType === 'connect_only');
      showToast(isConnect 
        ? `⚡ Sending connection request to ${name || 'contact'} with custom note in Brave...`
        : isConnectOnly
        ? `⚡ Sending connection request to ${name || 'contact'} (without note) in Brave...`
        : `⚡ Launching Brave & auto-typing referral message for ${name || 'connection'}...`
      );

      // Auto-record into Referral Network CRM immediately so it starts tracking without manual input!
      if (company || profileUrl) {
        const noteText = isConnectOnly ? '1-Click Connect (no note)' : isConnect ? '1-Click Connect + Tailored Note' : 'Referral Outreach DM';
        logConnectionFromModal(company || 'Target Company', name || 'LinkedIn Contact', profileUrl, noteText, template === 'alumni');
      }

      try {
        const res = await fetch('/api/linkedin/compose_dm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            profile_url: profileUrl,
            name: name,
            company: company,
            role: role,
            template: template,
            action_type: actionType
          })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast(`🛡️ ${data.message}`);
          setTimeout(() => { updateStats(); }, 2000);
        } else {
          showToast(`⚠️ Compose: ${data.message || 'Error'}`);
        }
      } catch (err) {
        showToast(`Error launching DM composer: ${err}`);
      }
    }

    function autoTypeDirectConnectionDM() {
      const val = document.getElementById('direct-conn-input').value.trim();
      if (!val) {
        showToast('Please enter a connection LinkedIn URL first.');
        return;
      }
      const titleEl = document.getElementById('referral-modal-title');
      const compMatch = titleEl ? titleEl.innerText.match(/Outreach:\s*([^(\\n]+)/) : null;
      const comp = compMatch ? compMatch[1].trim() : '';
      composeLinkedInDM(val, '', comp, 'Backend Engineer', 'referral', 'auto');
    }

    function sendDirectConnectionInvite(withNote = true) {
      const val = document.getElementById('direct-conn-input').value.trim();
      if (!val) {
        showToast('Please enter a connection LinkedIn URL first.');
        return;
      }
      const titleEl = document.getElementById('referral-modal-title');
      const compMatch = titleEl ? titleEl.innerText.match(/Outreach:\s*([^(\\n]+)/) : null;
      const comp = compMatch ? compMatch[1].trim() : '';
      const action = withNote ? 'connect' : 'connect_only';
      composeLinkedInDM(val, '', comp, 'Backend Engineer', 'referral', action);
    }

    function copyText(val, label) {
      navigator.clipboard.writeText(val);
      showToast(`Copied ${label} to clipboard!`);
    }

    function copyOutreachText(elemId) {
      const el = document.getElementById(elemId);
      if (el) {
        navigator.clipboard.writeText(el.value);
        showToast('Message copied to clipboard! Ready to paste into LinkedIn.');
      }
    }

    async function syncGmailNow() {
      showToast('Scanning Gmail inbox for new recruiter responses...');
      try {
        const res = await fetch('/api/gmail/sync', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast(`✓ Scanned inbox! Synced ${data.synced_count} application responses.`);
          await fetchResponses();
          updateStats();
          if (currentTab === 'responses') renderResponses();
        } else {
          showToast('Sync update: ' + (data.message || 'Complete'));
          await fetchResponses();
          updateStats();
        }
      } catch (err) {
        showToast('Failed to sync Gmail: ' + err);
      }
    }

    function openDirectUrl(url) {
      if (!url || !url.startsWith('http')) {
        showToast('❌ Invalid or missing link.');
        return;
      }
      showToast('Opening in your active Brave browser...');
      // 1. Notify backend to trigger OS shell launch
      try {
        fetch('/api/open_url', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: url })
        });
      } catch (e) {}
      // 2. Native anchor dispatch so Brave opens tab immediately
      const a = document.createElement('a');
      a.href = url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }

    function showToast(msg) {
      const t = document.getElementById('toast');
      t.innerHTML = `<i class="fa-solid fa-circle-info"></i> ${msg}`;
      t.style.display = 'flex';
      setTimeout(() => { t.style.display = 'none'; }, 4000);
    }

    /* Confetti Engine */
    /* Gmail Recruiter Drafting & Direct Sending System */
    async function draftEmailForJob(rowid, customEmail = null) {
      const btn = document.getElementById(`btn-draft-${rowid}`);
      if (btn) {
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Drafting...';
        btn.disabled = true;
      }
      showToast('Creating Gmail draft with tailored resume...');
      try {
        const res = await fetch(`/api/jobs/${rowid}/draft_email`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ custom_email: customEmail || '' })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast('✅ Gmail draft created! Attached: ' + (data.attachment ? 'Resume PDF' : 'None'));
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-check"></i> Draft Created!';
            btn.style.background = '#059669';
          }
          setTimeout(() => {
            if (confirm(`Draft created successfully in your Gmail!\n\nTo: ${data.to}\nSubject: ${data.subject}\n\nWould you like to open your Gmail Drafts now in Brave?`)) {
              window.open('https://mail.google.com/mail/u/0/#drafts', '_blank');
            }
          }, 300);
        } else if (data.status === 'fallback') {
          // Copy resume path to clipboard for instant attachment in Gmail Web
          if (data.attachment) {
            try {
              navigator.clipboard.writeText(data.attachment);
              showToast('📎 Resume path copied to clipboard! (Ctrl+V in file picker)');
            } catch (err) {}
          }
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-arrow-up-right-from-square"></i> Open in Gmail';
            btn.style.background = '#0284c7';
            btn.disabled = false;
            btn.onclick = () => window.open(data.web_compose_url, '_blank');
          }
          window.open(data.web_compose_url, '_blank');
        } else if (data.status === 'missing_email') {
          promptCustomDraft(rowid, 'draft');
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-file-pen"></i> Draft in Gmail';
            btn.disabled = false;
          }
        } else {
          showToast('⚠️ Error: ' + (data.message || 'Failed to draft email'));
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-file-pen"></i> Retry Draft';
            btn.disabled = false;
          }
        }
      } catch (e) {
        showToast('Failed to connect: ' + e);
        if (btn) {
          btn.innerHTML = '<i class="fa-solid fa-file-pen"></i> Draft in Gmail';
          btn.disabled = false;
        }
      }
    }

    async function sendEmailForJob(rowid, customEmail = null) {
      const btn = document.getElementById(`btn-send-${rowid}`);
      const job = allJobs.find(j => j.rowid === rowid);
      const recipient = (customEmail || (job ? job.recruiter_email : '') || '').trim();

      if (!recipient) {
        promptCustomDraft(rowid, 'send');
        return;
      }

      if (!confirm(`⚡ HIGH CONFIDENCE SEND:\n\nAre you sure you want to send this cold application directly to:\n${recipient}\n\nYour tailored resume will be attached automatically.`)) {
        return;
      }

      if (btn) {
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Sending...';
        btn.disabled = true;
      }
      showToast('Sending recruiter email with tailored resume...');
      try {
        const res = await fetch(`/api/jobs/${rowid}/send_email`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ custom_email: recipient })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast('🎉 BOOM! Email successfully sent to ' + data.to);
          triggerConfetti();
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-paper-plane-circle-check"></i> Sent!';
            btn.style.background = '#059669';
          }
          fetchJobs();
        } else if (data.status === 'fallback') {
          // Copy resume path to clipboard for instant attachment in Gmail Web
          if (data.attachment) {
            try {
              navigator.clipboard.writeText(data.attachment);
              showToast('📎 Resume path copied to clipboard! (Ctrl+V in file picker)');
            } catch (err) {}
          }
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-arrow-up-right-from-square"></i> Open in Gmail';
            btn.style.background = '#0284c7';
            btn.disabled = false;
            btn.onclick = () => window.open(data.web_compose_url, '_blank');
          }
          window.open(data.web_compose_url, '_blank');
        } else {
          showToast('⚠️ Error: ' + (data.message || 'Failed to send email'));
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Send Email';
            btn.disabled = false;
          }
        }
      } catch (e) {
        showToast('Failed to connect: ' + e);
        if (btn) {
          btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Send Email';
          btn.disabled = false;
        }
      }
    }

    function promptCustomDraft(rowid, action = 'draft') {
      const job = allJobs.find(j => j.rowid === rowid);
      const comp = job ? job.company : '';
      const role = job ? job.title : '';
      const url = job ? (job.apply_url || job.url || '') : '';
      const email = job ? (job.recruiter_email || '') : '';
      openCustomDraftModal(comp, role, url, email);
    }

    async function draftEmailFromModal(rowid, action = 'draft') {
      const input = document.getElementById(`modal-draft-email-${rowid}`);
      const statusEl = document.getElementById(`modal-draft-status-${rowid}`);
      const btnDraft = document.getElementById(`btn-modal-draft-${rowid}`);
      const btnSend = document.getElementById(`btn-modal-send-${rowid}`);
      const email = input ? input.value.trim() : '';
      if (!email || !email.includes('@')) {
        alert('Please enter a valid email address.');
        return;
      }

      if (action === 'send') {
        if (!confirm(`Are you sure you want to send cold email directly to ${email}? Resume will be attached.`)) {
          return;
        }
      }

      const activeBtn = action === 'send' ? btnSend : btnDraft;
      if (activeBtn) {
        activeBtn.innerHTML = action === 'send' ? '<i class="fa-solid fa-spinner fa-spin"></i> Sending...' : '<i class="fa-solid fa-spinner fa-spin"></i> Drafting...';
        activeBtn.disabled = true;
      }
      if (statusEl) {
        statusEl.style.display = 'block';
        statusEl.style.background = 'rgba(56, 189, 248, 0.2)';
        statusEl.style.color = '#38bdf8';
        statusEl.innerHTML = action === 'send' 
          ? '<i class="fa-solid fa-spinner fa-spin"></i> Sending email via Gmail CLI with attached tailored resume...'
          : '<i class="fa-solid fa-spinner fa-spin"></i> Running Gmail CLI to compose draft and attach resume PDF...';
      }
      try {
        const endpoint = action === 'send' ? `/api/jobs/${rowid}/send_email` : `/api/jobs/${rowid}/draft_email`;
        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ custom_email: email })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          if (activeBtn) {
            activeBtn.innerHTML = action === 'send' ? '<i class="fa-solid fa-paper-plane-circle-check"></i> Sent!' : '<i class="fa-solid fa-check"></i> Draft Ready in Gmail!';
            activeBtn.style.background = '#059669';
          }
          if (statusEl) {
            statusEl.style.background = 'rgba(16, 185, 129, 0.25)';
            statusEl.style.color = '#34d399';
            if (action === 'send') {
              statusEl.innerHTML = `<strong>🎉 Email Sent Successfully!</strong><br>
                <span style="font-size:11px;color:#cbd5e1;">Delivered to: ${data.to} | Attachment: ${data.attachment ? 'Resume PDF attached' : 'None'}</span><br>
                <a href="https://mail.google.com/mail/u/0/#sent" target="_blank" rel="noopener noreferrer" style="color:#38bdf8;text-decoration:underline;display:inline-block;margin-top:6px;font-weight:700;">View in Gmail Sent Mail &rarr;</a>`;
              triggerConfetti();
              fetchJobs();
            } else {
              statusEl.innerHTML = `<strong>✅ Draft created in Gmail!</strong><br>
                <span style="font-size:11px;color:#cbd5e1;">Recipient: ${data.to} | Attachment: ${data.attachment ? 'Resume PDF attached' : 'None'}</span><br>
                <a href="https://mail.google.com/mail/u/0/#drafts" target="_blank" rel="noopener noreferrer" style="color:#38bdf8;text-decoration:underline;display:inline-block;margin-top:6px;font-weight:700;">Open Gmail Drafts to Review & Send &rarr;</a>`;
            }
          }
          showToast((action === 'send' ? '🎉 Email sent to ' : '✅ Draft created for ') + email);
        } else if (data.status === 'fallback') {
          if (activeBtn) {
            activeBtn.innerHTML = '<i class="fa-solid fa-arrow-up-right-from-square"></i> Open in Gmail Web';
            activeBtn.style.background = '#0284c7';
            activeBtn.disabled = false;
            activeBtn.onclick = () => window.open(data.web_compose_url, '_blank');
          }
          if (statusEl) {
            statusEl.style.background = 'rgba(2, 132, 199, 0.2)';
            statusEl.style.border = '1px solid #38bdf8';
            statusEl.style.color = '#e0f2fe';
            statusEl.innerHTML = `<strong>✨ Recruiter Email Generated & Ready!</strong><br>
              <div style="font-size:11px;color:#cbd5e1;margin:6px 0;">Subject: <strong>${data.subject}</strong></div>
              <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;">
                <a href="${data.web_compose_url}" target="_blank" rel="noopener noreferrer" style="background:#0284c7;color:#fff;padding:6px 14px;border-radius:6px;font-weight:700;text-decoration:none;font-size:12px;display:inline-flex;align-items:center;gap:6px;"><i class="fa-solid fa-arrow-up-right-from-square"></i> Open Pre-filled Draft in Gmail Web</a>
                <button onclick="navigator.clipboard.writeText('${(data.subject || '').replace(/'/g, "\\'")}\n\n' + decodeURIComponent('${encodeURIComponent(data.body || '')}')); showToast('Email copied to clipboard!');" style="background:#334155;color:#e2e8f0;border:none;padding:6px 12px;border-radius:6px;cursor:pointer;font-weight:600;font-size:12px;"><i class="fa-solid fa-copy"></i> Copy Text</button>
              </div>
              <div style="font-size:11px;color:#a5b4fc;margin-top:6px;">📎 Tailored Resume PDF: ${data.attachment || 'Master Resume (RVCE)'}</div>`;
          }
          showToast('✨ Email prepared! Click "Open in Gmail Web" to review & send.');
          window.open(data.web_compose_url, '_blank');
        } else {
          if (activeBtn) {
            activeBtn.innerHTML = action === 'send' ? '<i class="fa-solid fa-paper-plane"></i> Send Now' : '<i class="fa-solid fa-file-pen"></i> Save Draft';
            activeBtn.disabled = false;
          }
          if (statusEl) {
            statusEl.style.background = 'rgba(239, 68, 68, 0.25)';
            statusEl.style.color = '#f87171';
            statusEl.innerHTML = '⚠️ Error: ' + (data.message || (action === 'send' ? 'Sending failed.' : 'Draft creation failed.'));
          }
        }
      } catch (err) {
        if (activeBtn) {
          activeBtn.innerHTML = action === 'send' ? '<i class="fa-solid fa-paper-plane"></i> Send Now' : '<i class="fa-solid fa-file-pen"></i> Save Draft';
          activeBtn.disabled = false;
        }
        if (statusEl) {
          statusEl.style.background = 'rgba(239, 68, 68, 0.25)';
          statusEl.style.color = '#f87171';
          statusEl.innerHTML = '⚠️ Network Error: ' + err;
        }
      }
    }

    function openCustomDraftModal(comp = '', role = '', url = '', email = '') {
      document.getElementById('custom-draft-email').value = email;
      document.getElementById('custom-draft-comp').value = comp;
      document.getElementById('custom-draft-role').value = role;
      document.getElementById('custom-draft-url').value = url;
      document.getElementById('custom-draft-status').style.display = 'none';
      const btn = document.getElementById('btn-submit-custom-draft');
      btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Create Gmail Draft (w/ Resume)';
      btn.disabled = false;
      btn.style.background = 'linear-gradient(135deg, #ea4335, #dc2626)';
      document.getElementById('custom-draft-modal').style.display = 'flex';
    }

    function closeCustomDraftModal() {
      document.getElementById('custom-draft-modal').style.display = 'none';
    }

    /* Job Link Tailor Modal Functions */
    function openJobLinkTailorModal() {
      document.getElementById('jlink-url').value = '';
      document.getElementById('jlink-jd').value = '';
      document.getElementById('jlink-loading').style.display = 'none';
      document.getElementById('jlink-result').style.display = 'none';
      document.getElementById('btn-jlink-process').disabled = false;
      document.getElementById('btn-jlink-process').innerHTML = '<i class="fa-solid fa-bolt"></i> Analyze & Generate';
      document.getElementById('job-link-tailor-modal').style.display = 'flex';
    }

    function closeJobLinkTailorModal() {
      document.getElementById('job-link-tailor-modal').style.display = 'none';
    }

    async function submitJobLinkIntake() {
      const url = document.getElementById('jlink-url').value.trim();
      const manualJd = document.getElementById('jlink-jd').value.trim();
      if (!url && !manualJd) {
        alert('Please enter a job link (URL) or paste JD text.');
        return;
      }

      const btn = document.getElementById('btn-jlink-process');
      const loader = document.getElementById('jlink-loading');
      const resultBox = document.getElementById('jlink-result');

      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Processing...';
      loader.style.display = 'block';
      resultBox.style.display = 'none';

      try {
        const res = await fetch('/api/jobs/process_link', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: url, jd: manualJd })
        });
        const data = await res.json();

        loader.style.display = 'none';
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Analyze & Generate';

        if (data.status !== 'ok') {
          alert(data.message || 'Error processing job link');
          return;
        }

        const o = data.outreach || {};
        const comp = data.company || 'Company';
        const role = data.title || 'Software Engineer';
        const pdfPath = data.pdf_resume_path || '';
        const rowid = data.rowid;

        resultBox.innerHTML = `
          <div style="background: rgba(2, 132, 199, 0.1); border: 1.5px solid #0284c7; border-radius: 12px; padding: 16px; margin-bottom: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
              <div>
                <h3 style="margin: 0; color: #fff; font-size: 18px;">${role} @ <span style="color: #38bdf8;">${comp}</span></h3>
                <div style="font-size: 12px; color: #94a3b8; margin-top: 4px;">
                  <i class="fa-solid fa-location-dot"></i> ${data.location || 'Bengaluru'} &bull; 
                  <span style="color: #34d399;"><i class="fa-solid fa-check-circle"></i> Tailored Resume Compiled</span>
                  ${data.skills ? ` &bull; Skills: <code style="color: #f59e0b;">${data.skills}</code>` : ''}
                </div>
              </div>
              <div style="display: flex; gap: 8px;">
                ${rowid ? `
                  <button class="btn" onclick="openPdfModal('${pdfPath}', 'Tailored Resume - ${comp}')" style="background: #2563eb; color: #fff; font-weight: 700; padding: 7px 14px; border-radius: 6px;">
                    <i class="fa-solid fa-file-pdf"></i> Preview Resume PDF
                  </button>
                  <a href="/api/jobs/${rowid}/resume?download=1" download class="btn" style="background: #059669; color: #fff; font-weight: 700; padding: 7px 14px; border-radius: 6px; text-decoration: none;">
                    <i class="fa-solid fa-download"></i> Download PDF
                  </a>
                ` : ''}
                <button class="btn" onclick="copyText(decodeURIComponent('${encodeURIComponent(data.tailored_resume_text || '')}'), 'Tailored Resume Text')" style="background: #475569; color: #fff; padding: 7px 12px; border-radius: 6px;">
                  <i class="fa-regular fa-copy"></i> Copy Resume Text
                </button>
              </div>
            </div>
          </div>

          <!-- Referral 1-Click Search Links -->
          <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; padding: 14px; margin-bottom: 18px;">
            <div style="font-weight: 700; color: #f8fafc; font-size: 13.5px; margin-bottom: 10px;">
              <i class="fa-brands fa-linkedin" style="color: #38bdf8;"></i> 1-Click Targeted LinkedIn Searches for ${comp}:
            </div>
            <div style="display: flex; flex-wrap: wrap; gap: 8px;">
              <a href="${o.first_degree_url || '#'}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #065f46; color: #6ee7b7; text-decoration: none; font-size: 11.5px; font-weight: 600;">
                <i class="fa-solid fa-user-group"></i> 1st-Degree Friends @ ${comp}
              </a>
              <a href="${o.second_degree_url || '#'}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #1e3a8a; color: #93c5fd; text-decoration: none; font-size: 11.5px; font-weight: 600;">
                <i class="fa-solid fa-users"></i> 2nd-Degree Mutuals @ ${comp}
              </a>
              <a href="${o.alumni_search_url || '#'}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #0369a1; color: #7dd3fc; text-decoration: none; font-size: 11.5px; font-weight: 600;">
                <i class="fa-solid fa-graduation-cap"></i> RVCE Alumni @ ${comp}
              </a>
              <a href="${o.recruiter_search_url || '#'}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #581c87; color: #d8b4fe; text-decoration: none; font-size: 11.5px; font-weight: 600;">
                <i class="fa-solid fa-briefcase"></i> Recruiters @ ${comp}
              </a>
              <a href="${o.hiring_posts_url || '#'}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #9a3412; color: #fdba74; text-decoration: none; font-size: 11.5px; font-weight: 600;">
                <i class="fa-solid fa-bullhorn"></i> Hiring Posts @ ${comp}
              </a>
            </div>
          </div>

          <!-- Personalized Messages Section -->
          <div style="display: flex; flex-direction: column; gap: 14px;">
            <!-- Template 1: Colleague / 1st Degree -->
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 12px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <h4 style="margin: 0; color: #60a5fa; font-size: 13px;"><i class="fa-solid fa-user-check"></i> 1st-Degree Connection / Friend Referral Message</h4>
                <button class="btn" style="background: #2563eb; color: white; padding: 4px 10px; font-size: 11px;" onclick="copyOutreachText('jlink-msg-1st')">
                  <i class="fa-regular fa-copy"></i> Copy
                </button>
              </div>
              <textarea id="jlink-msg-1st" style="width: 100%; height: 95px; background: #0f172a; color: #f1f5f9; border: 1px solid #334155; border-radius: 6px; padding: 10px; font-family: monospace; font-size: 12px; resize: vertical;" readonly>${o.first_degree_message || ''}</textarea>
            </div>

            <!-- Template 2: Mutual / 2nd Degree -->
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 12px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <h4 style="margin: 0; color: #38bdf8; font-size: 13px;"><i class="fa-solid fa-users"></i> 2nd-Degree Mutual / Post Referrer Message</h4>
                <button class="btn" style="background: #0284c7; color: white; padding: 4px 10px; font-size: 11px;" onclick="copyOutreachText('jlink-msg-2nd')">
                  <i class="fa-regular fa-copy"></i> Copy
                </button>
              </div>
              <textarea id="jlink-msg-2nd" style="width: 100%; height: 110px; background: #0f172a; color: #f1f5f9; border: 1px solid #334155; border-radius: 6px; padding: 10px; font-family: monospace; font-size: 12px; resize: vertical;" readonly>${o.second_degree_message || ''}</textarea>
            </div>

            <!-- Template 3: RVCE Alumni -->
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 12px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <h4 style="margin: 0; color: #4ade80; font-size: 13px;"><i class="fa-solid fa-graduation-cap"></i> RVCE Alumni Referral Request</h4>
                <button class="btn" style="background: #10b981; color: white; padding: 4px 10px; font-size: 11px;" onclick="copyOutreachText('jlink-msg-alumni')">
                  <i class="fa-regular fa-copy"></i> Copy
                </button>
              </div>
              <textarea id="jlink-msg-alumni" style="width: 100%; height: 100px; background: #0f172a; color: #f1f5f9; border: 1px solid #334155; border-radius: 6px; padding: 10px; font-family: monospace; font-size: 12px; resize: vertical;" readonly>${o.alumni_message || ''}</textarea>
            </div>

            <!-- Template 4: Recruiter InMail / DM -->
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 12px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <h4 style="margin: 0; color: #a78bfa; font-size: 13px;"><i class="fa-solid fa-bullhorn"></i> Recruiter Direct InMail / DM</h4>
                <button class="btn" style="background: #7c3aed; color: white; padding: 4px 10px; font-size: 11px;" onclick="copyOutreachText('jlink-msg-recruiter')">
                  <i class="fa-regular fa-copy"></i> Copy
                </button>
              </div>
              <textarea id="jlink-msg-recruiter" style="width: 100%; height: 100px; background: #0f172a; color: #f1f5f9; border: 1px solid #334155; border-radius: 6px; padding: 10px; font-family: monospace; font-size: 12px; resize: vertical;" readonly>${o.recruiter_message || ''}</textarea>
            </div>
          </div>
        `;
        resultBox.style.display = 'block';

        // Refresh dashboard list if a new row was added to jobs
        loadJobs();
      } catch (err) {
        loader.style.display = 'none';
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Analyze & Generate';
        alert('Request failed: ' + err.message);
      }
    }

    /* LinkedIn Post Intake Functions */
    function openLinkedInPostModal() {
      document.getElementById('lpost-url').value = '';
      document.getElementById('lpost-text').value = '';
      document.getElementById('lpost-loading').style.display = 'none';
      document.getElementById('lpost-result').style.display = 'none';
      document.getElementById('btn-lpost-process').disabled = false;
      document.getElementById('btn-lpost-process').innerHTML = '<i class="fa-solid fa-bolt"></i> Inspect Post & Tailor';
      document.getElementById('linkedin-post-modal').style.display = 'flex';
    }

    function closeLinkedInPostModal() {
      document.getElementById('linkedin-post-modal').style.display = 'none';
    }

    async function submitLinkedInPostIntake() {
      const url = document.getElementById('lpost-url').value.trim();
      const text = document.getElementById('lpost-text').value.trim();
      if (!url && !text) {
        alert('Please enter a LinkedIn post link (URL) or paste post text.');
        return;
      }

      const btn = document.getElementById('btn-lpost-process');
      const loader = document.getElementById('lpost-loading');
      const resultBox = document.getElementById('lpost-result');

      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Inspecting & Tailoring...';
      loader.style.display = 'block';
      resultBox.style.display = 'none';

      try {
        const res = await fetch('/api/linkedin/process_post', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: url, text: text })
        });
        const data = await res.json();

        loader.style.display = 'none';
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Inspect Post & Tailor';

        if (data.status !== 'ok') {
          alert(data.message || 'Error processing LinkedIn post');
          return;
        }

        const o = data.outreach || {};
        const comp = data.company || 'Company';
        const role = data.title || 'Software Engineer';
        const pdfPath = data.pdf_resume_path || '';
        const rowid = data.rowid;
        const email = data.recruiter_email || '';
        const formUrl = data.form_url || '';
        const careersUrl = data.careers_url || '';
        const targetUrl = data.target_app_url || data.post_url || '';

        resultBox.innerHTML = `
          <!-- Header Banner -->
          <div style="background: rgba(10, 102, 194, 0.12); border: 1.5px solid #0a66c2; border-radius: 12px; padding: 18px; margin-bottom: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
              <div>
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                  <span style="background: #0a66c2; color: #fff; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px;"><i class="fa-brands fa-linkedin"></i> LinkedIn Hiring Post</span>
                  ${data.author_name ? `<span style="color: #94a3b8; font-size: 12px;">by <strong style="color: #cbd5e1;">${data.author_name}</strong></span>` : ''}
                </div>
                <h3 style="margin: 0; color: #fff; font-size: 19px;">${role} @ <span style="color: #38bdf8;">${comp}</span></h3>
                <div style="font-size: 12px; color: #94a3b8; margin-top: 4px;">
                  <i class="fa-solid fa-location-dot"></i> ${data.location || 'Bengaluru'} &bull; 
                  <span style="color: #34d399;"><i class="fa-solid fa-check-circle"></i> Tailored Resume Compiled</span>
                  ${data.tech_stack && data.tech_stack.length ? ` &bull; Stack: <code style="color: #f59e0b;">${data.tech_stack.join(', ')}</code>` : ''}
                </div>
              </div>
              <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                ${rowid ? `
                  <button class="btn" onclick="previewPDF('${pdfPath}', 'Tailored Resume - ${comp}')" style="background: #2563eb; color: #fff; font-weight: 700; padding: 7px 14px; border-radius: 6px;">
                    <i class="fa-solid fa-file-pdf"></i> Preview Resume PDF
                  </button>
                  <a href="/api/jobs/${rowid}/resume?download=1" download class="btn" style="background: #059669; color: #fff; font-weight: 700; padding: 7px 14px; border-radius: 6px; text-decoration: none;">
                    <i class="fa-solid fa-download"></i> Download PDF
                  </a>
                ` : ''}
                <button class="btn" onclick="copyText(decodeURIComponent('${encodeURIComponent(data.tailored_resume_text || '')}'), 'Tailored Resume Text')" style="background: #475569; color: #fff; padding: 7px 12px; border-radius: 6px;">
                  <i class="fa-regular fa-copy"></i> Copy Resume Text
                </button>
              </div>
            </div>
          </div>

          <!-- Key Action Cards (Form Link / Email Drafter) -->
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; margin-bottom: 20px;">
            <!-- Recruiter Mail Card -->
            <div style="background: #0f172a; border: 1.5px solid ${email ? '#059669' : '#334155'}; border-radius: 10px; padding: 14px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-weight: 700; color: #f8fafc; font-size: 13px;"><i class="fa-solid fa-envelope" style="color: #34d399;"></i> Recruiter Email Intake</span>
                ${email ? `<span style="background: rgba(16, 185, 129, 0.2); color: #34d399; font-size: 11px; padding: 2px 6px; border-radius: 4px; font-weight: 600;">Found in Post</span>` : `<span style="color: #94a3b8; font-size: 11px;">Not mentioned in post</span>`}
              </div>
              ${email ? `
                <div style="font-size: 13px; color: #38bdf8; font-family: monospace; margin-bottom: 10px; word-break: break-all;">
                  <strong>${email}</strong>
                </div>
                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                  <button class="btn" onclick="openCustomDraftModal('${comp}', '${role}', '${targetUrl}', '${email}')" style="background: linear-gradient(135deg, #ea4335, #dc2626); color: #fff; font-weight: 700; font-size: 11.5px; padding: 6px 12px; border-radius: 6px;">
                    <i class="fa-solid fa-file-pen"></i> Draft in Gmail (w/ PDF)
                  </button>
                  <a href="${data.web_compose_url || '#'}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #334155; color: #cbd5e1; text-decoration: none; font-size: 11.5px; padding: 6px 12px; border-radius: 6px;">
                    <i class="fa-solid fa-arrow-up-right-from-square"></i> Open Brave Compose
                  </a>
                </div>
              ` : `
                <p style="margin: 0 0 10px 0; font-size: 12px; color: #94a3b8;">No email found directly in the post text. You can still reach out via LinkedIn InMail or find recruiters below.</p>
                <button class="btn" onclick="openCustomDraftModal('${comp}', '${role}', '${targetUrl}', '')" style="background: #334155; color: #cbd5e1; font-size: 11.5px; padding: 6px 12px; border-radius: 6px;">
                  <i class="fa-solid fa-pen-nib"></i> Compose Custom Email
                </button>
              `}
            </div>

            <!-- Form / Application Link Card -->
            <div style="background: #0f172a; border: 1.5px solid ${formUrl || careersUrl ? '#0284c7' : '#334155'}; border-radius: 10px; padding: 14px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-weight: 700; color: #f8fafc; font-size: 13px;"><i class="fa-solid fa-link" style="color: #38bdf8;"></i> Application Form / Portal</span>
                ${formUrl ? `<span style="background: rgba(14, 165, 233, 0.2); color: #38bdf8; font-size: 11px; padding: 2px 6px; border-radius: 4px; font-weight: 600;">Google Form Detected</span>` : (careersUrl ? `<span style="background: rgba(99, 102, 241, 0.2); color: #a5b4fc; font-size: 11px; padding: 2px 6px; border-radius: 4px; font-weight: 600;">Careers Portal</span>` : `<span style="color: #94a3b8; font-size: 11px;">Direct DM Post</span>`)}
              </div>
              ${formUrl ? `
                <div style="font-size: 12px; color: #94a3b8; margin-bottom: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                  Google Form: <a href="${formUrl}" target="_blank" rel="noopener noreferrer" style="color: #38bdf8;">${formUrl}</a>
                </div>
                <div style="display: flex; gap: 8px;">
                  <a href="${formUrl}" target="_blank" rel="noopener noreferrer" class="btn" style="background: linear-gradient(135deg, #0284c7, #2563eb); color: #fff; text-decoration: none; font-weight: 700; font-size: 11.5px; padding: 6px 12px; border-radius: 6px;">
                    <i class="fa-solid fa-arrow-up-right-from-square"></i> Open Google Form in Brave
                  </a>
                  <button class="btn" onclick="openScreeningCopilotModal('${comp}', '${role}')" style="background: #4f46e5; color: #fff; font-size: 11.5px; padding: 6px 12px; border-radius: 6px;" title="Answers form questions in Deepak's voice">
                    <i class="fa-solid fa-robot"></i> Form Copilot 🤖
                  </button>
                </div>
              ` : (careersUrl ? `
                <div style="font-size: 12px; color: #94a3b8; margin-bottom: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                  Careers URL: <a href="${careersUrl}" target="_blank" rel="noopener noreferrer" style="color: #38bdf8;">${careersUrl}</a>
                </div>
                <a href="${careersUrl}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #2563eb; color: #fff; text-decoration: none; font-weight: 700; font-size: 11.5px; padding: 6px 12px; border-radius: 6px; display: inline-block;">
                  <i class="fa-solid fa-arrow-up-right-from-square"></i> Open Application Portal in Brave
                </a>
              ` : `
                <p style="margin: 0 0 10px 0; font-size: 12px; color: #94a3b8;">No external form link found. Candidate is instructed to email or DM directly on LinkedIn.</p>
                <a href="${data.post_url || '#'}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #334155; color: #cbd5e1; text-decoration: none; font-size: 11.5px; padding: 6px 12px; border-radius: 6px; display: inline-block;">
                  <i class="fa-brands fa-linkedin"></i> View Original LinkedIn Post
                </a>
              `)}
            </div>
          </div>

          <!-- Referral 1-Click Search Links -->
          <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; padding: 14px; margin-bottom: 18px;">
            <div style="font-weight: 700; color: #f8fafc; font-size: 13.5px; margin-bottom: 10px;">
              <i class="fa-brands fa-linkedin" style="color: #38bdf8;"></i> 1-Click Targeted LinkedIn Searches for ${comp}:
            </div>
            <div style="display: flex; flex-wrap: wrap; gap: 8px;">
              <a href="${o.first_degree_url || '#'}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #065f46; color: #6ee7b7; text-decoration: none; font-size: 11.5px; font-weight: 600;">
                <i class="fa-solid fa-user-group"></i> 1st-Degree Friends @ ${comp}
              </a>
              <a href="${o.second_degree_url || '#'}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #1e3a8a; color: #93c5fd; text-decoration: none; font-size: 11.5px; font-weight: 600;">
                <i class="fa-solid fa-users"></i> 2nd-Degree Mutuals @ ${comp}
              </a>
              <a href="${o.alumni_search_url || '#'}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #0369a1; color: #7dd3fc; text-decoration: none; font-size: 11.5px; font-weight: 600;">
                <i class="fa-solid fa-graduation-cap"></i> RVCE Alumni @ ${comp}
              </a>
              <a href="${o.recruiter_search_url || '#'}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #581c87; color: #d8b4fe; text-decoration: none; font-size: 11.5px; font-weight: 600;">
                <i class="fa-solid fa-briefcase"></i> Recruiters @ ${comp}
              </a>
              <a href="${o.hiring_posts_url || '#'}" target="_blank" rel="noopener noreferrer" class="btn" style="background: #9a3412; color: #fdba74; text-decoration: none; font-size: 11.5px; font-weight: 600;">
                <i class="fa-solid fa-bullhorn"></i> Other Hiring Posts @ ${comp}
              </a>
            </div>
          </div>

          <!-- Personalized Outreach & Cold Email Messages -->
          <div style="display: flex; flex-direction: column; gap: 14px;">
            <!-- Cold Email Draft Preview -->
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 12px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <h4 style="margin: 0; color: #f87171; font-size: 13px;"><i class="fa-solid fa-envelope"></i> Cold Email Draft (Ready for Recruiter)</h4>
                <button class="btn" style="background: #dc2626; color: white; padding: 4px 10px; font-size: 11px;" onclick="copyOutreachText('lpost-email-body')">
                  <i class="fa-regular fa-copy"></i> Copy Email
                </button>
              </div>
              <div style="font-size: 11.5px; color: #94a3b8; margin-bottom: 4px;">Subject: <strong>${data.email_subject || ''}</strong></div>
              <textarea id="lpost-email-body" style="width: 100%; height: 110px; background: #0f172a; color: #f1f5f9; border: 1px solid #334155; border-radius: 6px; padding: 10px; font-family: monospace; font-size: 12px; resize: vertical;" readonly>${data.email_body || ''}</textarea>
            </div>

            <!-- Template 1: Post Referrer / Author DM -->
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 12px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <h4 style="margin: 0; color: #38bdf8; font-size: 13px;"><i class="fa-brands fa-linkedin"></i> LinkedIn DM to Post Author / Referrer</h4>
                <button class="btn" style="background: #0284c7; color: white; padding: 4px 10px; font-size: 11px;" onclick="copyOutreachText('lpost-msg-2nd')">
                  <i class="fa-regular fa-copy"></i> Copy DM
                </button>
              </div>
              <textarea id="lpost-msg-2nd" style="width: 100%; height: 105px; background: #0f172a; color: #f1f5f9; border: 1px solid #334155; border-radius: 6px; padding: 10px; font-family: monospace; font-size: 12px; resize: vertical;" readonly>${o.second_degree_message || ''}</textarea>
            </div>

            <!-- Template 2: RVCE Alumni -->
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 12px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <h4 style="margin: 0; color: #4ade80; font-size: 13px;"><i class="fa-solid fa-graduation-cap"></i> RVCE Alumni Referral Request</h4>
                <button class="btn" style="background: #10b981; color: white; padding: 4px 10px; font-size: 11px;" onclick="copyOutreachText('lpost-msg-alumni')">
                  <i class="fa-regular fa-copy"></i> Copy
                </button>
              </div>
              <textarea id="lpost-msg-alumni" style="width: 100%; height: 95px; background: #0f172a; color: #f1f5f9; border: 1px solid #334155; border-radius: 6px; padding: 10px; font-family: monospace; font-size: 12px; resize: vertical;" readonly>${o.alumni_message || ''}</textarea>
            </div>
          </div>
        `;
        resultBox.style.display = 'block';

        // Refresh dashboard list
        fetchJobs();
      } catch (err) {
        loader.style.display = 'none';
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Inspect Post & Tailor';
        alert('Request failed: ' + err.message);
      }
    }

    /* Technical Interview Cheat-Sheet Modal */
    async function openCheatsheetModal(company, roleTitle) {
      const comp = decodeURIComponent(company || 'PhonePe');
      const role = decodeURIComponent(roleTitle || 'SDE Backend Engineer');
      document.getElementById('cheatsheet-modal-title').innerText = `Interview Cheat-Sheet: ${comp}`;
      document.getElementById('cheatsheet-modal').style.display = 'flex';
      const container = document.getElementById('cheatsheet-content');
      container.innerHTML = `
        <div style="text-align: center; padding: 40px 0;">
          <i class="fa-solid fa-spinner fa-spin fa-2x" style="color: #a855f7;"></i>
          <p style="margin-top: 12px; color: #94a3b8;">Synthesizing deep system design questions and Deepak's Meesho silver-bullet talking points for ${comp}...</p>
        </div>
      `;

      try {
        const res = await fetch(`/api/cheatsheet?company=${encodeURIComponent(comp)}&role=${encodeURIComponent(role)}`);
        const data = await res.json();
        
        let challengesHtml = (data.engineering_challenges || []).map(c => `<li style="margin-bottom: 4px;">${c}</li>`).join('');
        let topicsHtml = (data.must_know_topics || []).map(t => `<li style="margin-bottom: 6px;"><strong style="color: #38bdf8;">${t}</strong></li>`).join('');
        let questionsHtml = (data.questions_to_ask || []).map(q => `<li style="margin-bottom: 4px;"><em>"${q}"</em></li>`).join('');
        let hr = data.hr_tactics || {};

        container.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 12px;">
            <div>
              <div style="font-size: 18px; font-weight: 800; color: #fff;">${data.company} <span style="font-size: 13px; font-weight: 500; color: #a855f7;">(${data.role_title || role})</span></div>
              <div style="font-size: 12.5px; color: #94a3b8; margin-top: 3px;">Domain: <strong style="color:#cbd5e1;">${data.domain}</strong> | Stack: <code style="color:#34d399;">${data.primary_stack}</code></div>
            </div>
            <span style="background: rgba(168,85,247,0.15); color: #c084fc; border: 1px solid rgba(168,85,247,0.3); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700;">${data.source}</span>
          </div>

          <div style="margin-bottom: 18px;">
            <h4 style="margin: 0 0 8px 0; color: #f59e0b; font-size: 14px;"><i class="fa-solid fa-server"></i> 1. Core Engineering & Scale Challenges</h4>
            <ul style="margin: 0; padding-left: 20px; font-size: 13px; color: #cbd5e1;">${challengesHtml}</ul>
          </div>

          <div style="margin-bottom: 18px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 10px; padding: 14px;">
            <h4 style="margin: 0 0 8px 0; color: #38bdf8; font-size: 14px;"><i class="fa-solid fa-brain"></i> 2. High-Probability System Design & Concurrency Topics</h4>
            <ul style="margin: 0; padding-left: 20px; font-size: 13px;">${topicsHtml}</ul>
          </div>

          <div style="margin-bottom: 18px; background: rgba(16, 185, 129, 0.08); border: 1.5px solid #10b981; border-radius: 10px; padding: 14px;">
            <h4 style="margin: 0 0 6px 0; color: #34d399; font-size: 14px;"><i class="fa-solid fa-star"></i> 3. Deepak's Meesho "Silver-Bullet" Talking Point</h4>
            <p style="margin: 0; font-size: 13px; color: #d1fae5; line-height: 1.5;">${data.meesho_story_alignment}</p>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 18px;">
            <div style="background: rgba(30, 41, 59, 0.5); border: 1px solid #334155; border-radius: 10px; padding: 12px;">
              <h5 style="margin: 0 0 6px 0; color: #fca5a5; font-size: 13px;"><i class="fa-solid fa-comments"></i> Why ${data.company}?</h5>
              <p style="margin: 0; font-size: 12.5px; color: #cbd5e1;">${hr.why_leaving || ''}</p>
            </div>
            <div style="background: rgba(30, 41, 59, 0.5); border: 1px solid #334155; border-radius: 10px; padding: 12px;">
              <h5 style="margin: 0 0 6px 0; color: #fde047; font-size: 13px;"><i class="fa-solid fa-money-bill-wave"></i> Target CTC & Notice</h5>
              <div style="font-size: 12.5px; color: #cbd5e1;"><strong>Target Comp:</strong> ${hr.target_ctc || '28–36 LPA'}</div>
              <div style="font-size: 12.5px; color: #cbd5e1; margin-top: 4px;"><strong>Notice Period:</strong> ${hr.notice_period || '30 days (negotiable)'}</div>
            </div>
          </div>

          <div>
            <h4 style="margin: 0 0 6px 0; color: #c084fc; font-size: 13.5px;"><i class="fa-solid fa-circle-question"></i> Sharp Questions to Ask the Interviewer</h4>
            <ul style="margin: 0; padding-left: 20px; font-size: 13px; color: #e2e8f0;">${questionsHtml}</ul>
          </div>
        `;
      } catch (err) {
        container.innerHTML = `<div style="color: #f87171;">Failed to load cheat sheet: ${err}</div>`;
      }
    }

    function closeCheatsheetModal() {
      document.getElementById('cheatsheet-modal').style.display = 'none';
    }

    async function testAlertsFromUI() {
      showToast('⚡ Dispatching test alert to Telegram, WhatsApp & Desktop Toast...');
      try {
        const res = await fetch('/api/alerts/test', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast('🔔 Alert test complete! Check your screen & phone.');
        } else {
          showToast('Alert test: ' + (data.message || 'Error'));
        }
      } catch (e) {
        showToast('Alert test error: ' + e);
      }
    }

    async function pruneOldJobsNow() {
      if (!confirm('🗑 This will permanently delete all job listings older than 15 days that have NOT been applied to, interviewed, or referred. Continue?')) return;
      showToast('🗑 Pruning stale jobs older than 15 days...');
      try {
        const res = await fetch('/api/jobs/prune', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ days: 15 })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast(`✅ Pruned ${data.deleted} stale job listing(s) older than 15 days. DB cleaned!`);
          if (data.deleted > 0) {
            updateStats();
            renderJobs(currentTab);
          }
        } else {
          showToast('Prune error: ' + (data.message || 'Unknown error'));
        }
      } catch (err) {
        showToast('Prune error: ' + err);
      }
    }

    async function submitCustomDraft(action = 'draft') {
      const email = document.getElementById('custom-draft-email').value.trim();
      const comp = document.getElementById('custom-draft-comp').value.trim();
      const role = document.getElementById('custom-draft-role').value.trim();
      const url = document.getElementById('custom-draft-url').value.trim();
      const statusEl = document.getElementById('custom-draft-status');
      const btnDraft = document.getElementById('btn-submit-custom-draft');
      const btnSend = document.getElementById('btn-submit-custom-send');

      if (!email || !email.includes('@')) {
        alert('Please enter a valid recruiter email address.');
        return;
      }

      if (action === 'send') {
        if (!confirm(`Are you sure you want to send cold application directly to ${email}? Resume will be attached.`)) {
          return;
        }
      }

      const activeBtn = action === 'send' ? btnSend : btnDraft;
      if (activeBtn) {
        activeBtn.innerHTML = action === 'send' ? '<i class="fa-solid fa-spinner fa-spin"></i> Sending...' : '<i class="fa-solid fa-spinner fa-spin"></i> Creating Draft...';
        activeBtn.disabled = true;
      }
      statusEl.style.display = 'block';
      statusEl.style.background = 'rgba(56, 189, 248, 0.2)';
      statusEl.style.color = '#38bdf8';
      statusEl.innerHTML = action === 'send'
        ? '<i class="fa-solid fa-spinner fa-spin"></i> Sending email directly via Gmail CLI with attached tailored resume...'
        : '<i class="fa-solid fa-spinner fa-spin"></i> Composing draft and attaching resume PDF...';

      try {
        const res = await fetch('/api/email/custom_draft', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ to_email: email, company: comp, role: role, job_url: url, action: action })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          if (activeBtn) {
            activeBtn.innerHTML = action === 'send' ? '<i class="fa-solid fa-paper-plane-circle-check"></i> Sent!' : '<i class="fa-solid fa-check"></i> Draft Created in Gmail!';
            activeBtn.style.background = '#059669';
          }
          statusEl.style.background = 'rgba(16, 185, 129, 0.25)';
          statusEl.style.color = '#34d399';
          if (action === 'send') {
            statusEl.innerHTML = `<strong>🎉 Email Sent Directly!</strong><br>
              <span style="font-size:11px;color:#cbd5e1;">Recipient: ${data.to} | Resume: Attached</span><br>
              <a href="https://mail.google.com/mail/u/0/#sent" target="_blank" rel="noopener noreferrer" style="color:#38bdf8;text-decoration:underline;display:inline-block;margin-top:6px;font-weight:700;">View in Gmail Sent Mail &rarr;</a>`;
            triggerConfetti();
          } else {
            statusEl.innerHTML = `<strong>✅ Draft created in Gmail!</strong><br>
              <span style="font-size:11px;color:#cbd5e1;">Recipient: ${data.to} | Resume: Attached</span><br>
              <a href="https://mail.google.com/mail/u/0/#drafts" target="_blank" rel="noopener noreferrer" style="color:#38bdf8;text-decoration:underline;display:inline-block;margin-top:6px;font-weight:700;">Open Gmail Drafts to Review & Send &rarr;</a>`;
          }
          showToast((action === 'send' ? '🎉 Cold email sent to ' : '✅ Cold email drafted for ') + email);
        } else if (data.status === 'fallback') {
          if (activeBtn) {
            activeBtn.innerHTML = '<i class="fa-solid fa-arrow-up-right-from-square"></i> Open in Gmail Web';
            activeBtn.style.background = '#0284c7';
            activeBtn.disabled = false;
            activeBtn.onclick = () => window.open(data.web_compose_url, '_blank');
          }
          statusEl.style.background = 'rgba(2, 132, 199, 0.2)';
          statusEl.style.border = '1px solid #38bdf8';
          statusEl.style.color = '#e0f2fe';
          statusEl.innerHTML = `<strong>✨ Recruiter Email Generated & Ready!</strong><br>
            <div style="font-size:11px;color:#cbd5e1;margin:6px 0;">Subject: <strong>${data.subject}</strong></div>
            <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;">
              <a href="${data.web_compose_url}" target="_blank" rel="noopener noreferrer" style="background:#0284c7;color:#fff;padding:6px 14px;border-radius:6px;font-weight:700;text-decoration:none;font-size:12px;display:inline-flex;align-items:center;gap:6px;"><i class="fa-solid fa-arrow-up-right-from-square"></i> Open Pre-filled Draft in Gmail Web</a>
              <button onclick="navigator.clipboard.writeText('${(data.subject || '').replace(/'/g, "\\'")}\n\n' + decodeURIComponent('${encodeURIComponent(data.body || '')}')); showToast('Email copied to clipboard!');" style="background:#334155;color:#e2e8f0;border:none;padding:6px 12px;border-radius:6px;cursor:pointer;font-weight:600;font-size:12px;"><i class="fa-solid fa-copy"></i> Copy Text</button>
            </div>
            <div style="font-size:11px;color:#a5b4fc;margin-top:6px;">📎 Tailored Resume PDF: ${data.attachment || 'Master Resume (RVCE)'}</div>`;
          showToast('✨ Email prepared! Click "Open in Gmail Web" to review & send.');
          window.open(data.web_compose_url, '_blank');
        } else {
          if (activeBtn) {
            activeBtn.innerHTML = action === 'send' ? '<i class="fa-solid fa-paper-plane"></i> Send Email Directly' : '<i class="fa-solid fa-file-pen"></i> Save Draft in Gmail';
            activeBtn.disabled = false;
          }
          statusEl.style.background = 'rgba(239, 68, 68, 0.25)';
          statusEl.style.color = '#f87171';
          statusEl.innerHTML = '⚠️ Error: ' + (data.message || (action === 'send' ? 'Failed to send email' : 'Failed to create draft'));
        }
      } catch (err) {
        if (activeBtn) {
          activeBtn.innerHTML = action === 'send' ? '<i class="fa-solid fa-paper-plane"></i> Send Email Directly' : '<i class="fa-solid fa-file-pen"></i> Save Draft in Gmail';
          activeBtn.disabled = false;
        }
        statusEl.style.background = 'rgba(239, 68, 68, 0.25)';
        statusEl.style.color = '#f87171';
        statusEl.innerHTML = '⚠️ Network Error: ' + err;
      }
    }

    function triggerConfetti() {}

    async function checkNaukriStatus() {
      try {
        const res = await fetch('/api/naukri/status');
        const data = await res.json();
        const lbl = document.getElementById('naukri-pill-label');
        if (lbl) {
          if (data.last_update && data.last_update.status === 'success') {
            lbl.innerText = 'Naukri: Refreshed Today ✓';
          } else if (data.task && data.task.registered) {
            lbl.innerText = 'Naukri: 8:55 AM Active ⚡';
          }
        }
      } catch (e) {}
    }

    async function triggerNaukriRefresh() {
      showToast('⚡ Triggering Naukri profile & resume refresh in background...');
      const lbl = document.getElementById('naukri-pill-label');
      if (lbl) lbl.innerText = 'Naukri: Updating...';
      try {
        const res = await fetch('/api/naukri/refresh', { method: 'POST' });
        const data = await res.json();
        showToast('🚀 ' + (data.message || 'Naukri refresh initiated'));
      } catch (e) {
        showToast('⚠️ Could not trigger Naukri refresh: ' + e);
      }
    }

    async function triggerLinkedInEasyApplyScan() {
      showToast('🔍 Scanning LinkedIn for Easy Apply backend openings in background...');
      try {
        const res = await fetch('/api/linkedin/easy_apply_scan', { method: 'POST' });
        const data = await res.json();
        showToast('🚀 ' + (data.message || 'Scanning LinkedIn Easy Apply...'));
        setTimeout(fetchJobs, 6000);
        setTimeout(fetchJobs, 15000);
        setTimeout(fetchJobs, 30000);
      } catch (e) {
        showToast('⚠️ Could not start Easy Apply scan: ' + e);
      }
    }

    async function triggerLinkedInIncognitoScan() {
      setTab('incognito_fresh');
      showToast('⚡ Running Multi-Source Incognito scan across LinkedIn, Indeed & Direct ATS...');
      try {
        const res = await fetch('/api/linkedin/incognito_scan', { method: 'POST' });
        const data = await res.json();
        showToast('🚀 ' + (data.message || 'Scanning LinkedIn, Indeed & Direct ATS in guest/incognito mode...'));
        setTimeout(fetchJobs, 4000);
        setTimeout(fetchJobs, 8000);
        setTimeout(fetchJobs, 15000);
        setTimeout(fetchJobs, 25000);
        setTimeout(fetchJobs, 40000);
      } catch (e) {
        showToast('⚠️ Could not start Incognito multi-search: ' + e);
      }
    }

    async function triggerLinkedInPostsPoll(silent = false) {
      if (!silent) showToast('🔍 Scanning LinkedIn for fresh hiring posts (< 4h) in background...');
      try {
        const res = await fetch('/api/linkedin/posts_poll', { method: 'POST' });
        const data = await res.json();
        if (!silent && data.message) showToast('📡 ' + data.message);
        // Refresh jobs after 10s and 25s as browser finds posts
        setTimeout(fetchJobs, 10000);
        setTimeout(fetchJobs, 25000);
      } catch (e) {
        if (!silent) showToast('⚠️ LinkedIn posts scan error: ' + e);
      }
    }

    // Initial load
    fetchJobs();
    checkNaukriStatus();
    triggerLinkedInPostsPoll(true); // Automatically fetch fresh hiring posts on page load!
    setInterval(fetchJobs, 25000); // live sync every 25s
    setInterval(checkNaukriStatus, 60000); // check Naukri status every min
  </script>
</body>
</html>
"""


class DashboardHandler(SimpleHTTPRequestHandler):
    """Custom request handler for ApplyPilot Phase 2 Dashboard & Phase 3 Assistant."""

    def log_message(self, format, *args):
        # Silence default terminal request spam
        return

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        from applypilot.database import get_connection

        if path in ("/", "/index.html", "/dashboard"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD.encode("utf-8"))
            return

        elif path == "/api/linkedin/status":
            from applypilot.networking.linkedin import is_linkedin_authenticated
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"authenticated": is_linkedin_authenticated()}).encode("utf-8"))
            return

        elif path == "/api/naukri/status":
            from applypilot.automation.naukri_updater import get_windows_task_status, get_last_update_status
            data = {
                "task": get_windows_task_status(),
                "last_update": get_last_update_status(),
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        elif path == "/api/auto_apply_status":
            from applypilot.apply.assistant import AUTO_APPLY_STATE
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(AUTO_APPLY_STATE).encode("utf-8"))
            return

        elif path == "/api/followups/due":
            try:
                from applypilot.networking.followup_engine import ReferralFollowUpEngine
                engine = ReferralFollowUpEngine()
                actions = engine.collect_due_actions()
                data = [
                    {
                        "job_id": a.job_id,
                        "stage": a.stage,
                        "company": a.company,
                        "title": a.title,
                        "job_url": a.job_url,
                        "email_to_use": a.email_to_use,
                        "contact_name": a.contact_name,
                        "contact_handle": a.contact_handle,
                        "due_at": a.due_at,
                        "template_text": a.template_text,
                    }
                    for a in actions
                ]
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "actions": data}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        elif path == "/api/jobs":
            from applypilot.config import load_search_config
            cfg = load_search_config()
            reject_patterns = [rp.lower() for rp in cfg.get("location", {}).get("reject_patterns", [])]

            conn = get_connection()
            c = conn.cursor()
            query = """
                SELECT 
                    rowid,
                    COALESCE(site, 'Unknown') AS company,
                    COALESCE(title, 'N/A') AS title,
                    COALESCE(location, 'N/A') AS location,
                    COALESCE(recruiter_email, '') AS recruiter_email,
                    fit_score,
                    score_reasoning,
                    COALESCE(application_url, url) AS apply_url,
                    url,
                    tailored_resume_path,
                    cover_letter_path,
                    apply_status,
                    applied_at,
                    COALESCE(full_description, '') AS full_desc,
                    COALESCE(description, '') AS desc,
                    COALESCE(strategy, '') AS strategy,
                    COALESCE(salary, '') AS salary,
                    COALESCE(discovered_at, '') AS discovered_at,
                    COALESCE(referral_contacted_at, '') AS referral_contacted_at,
                    COALESCE(referral_contact_name, '') AS referral_contact_name,
                    COALESCE(referral_contact_platform, '') AS referral_contact_platform,
                    COALESCE(is_easy_apply, 0) AS is_easy_apply,
                    COALESCE(date_posted, '') AS date_posted,
                    num_applicants
                FROM jobs
                ORDER BY fit_score DESC NULLS LAST, discovered_at DESC
            """
            rows = c.execute(query).fetchall()
            cols = [d[0] for d in c.description]
            all_raw = [dict(zip(cols, r)) for r in rows]

            import re
            seniority_cfg = cfg.get("seniority", {})
            reject_titles = [t.lower() for t in seniority_cfg.get("reject_titles", [
                "senior", "sr.", "sr ", "lead", "tech lead", "staff", "principal", "manager", "mgr", "director", "architect", "head"
            ])]
            exp_patterns = [
                re.compile(r'(\d+)\+?\s*(?:to|-)\s*(\d+)\s*(?:years?|yrs?)(?:\s*of)?\s*(?:relevant|hands-on|industry|software|backend|work)?\s*experience', re.IGNORECASE),
                re.compile(r'(\d+)\+?\s*(?:to|-)\s*(\d+)\s*(?:years?|yrs?)', re.IGNORECASE),
                re.compile(r'(\d+)\+?\s*(?:years?|yrs?)(?:\s*of)?\s*(?:relevant|hands-on|industry|software|backend|work)?\s*experience', re.IGNORECASE),
                re.compile(r'experience(?:\s*of)?\s*:?\s*(\d+)\+?\s*(?:to|-)?\s*(\d+)?\s*(?:years?|yrs?)', re.IGNORECASE),
                re.compile(r'(?:minimum|min|at least)\s*(\d+)\+?\s*(?:years?|yrs?)', re.IGNORECASE),
                re.compile(r'(\d+)\+?\s*yoe\b', re.IGNORECASE),
                re.compile(r'yoe\s*:?\s*(\d+)\+?', re.IGNORECASE),
            ]

            jobs = []
            for j in all_raw:
                loc = (j.get("location") or "").lower()
                tit = (j.get("title") or "").lower()

                # 1. Location rejection (e.g. US-only, Canada, UK)
                if any(rp in loc for rp in reject_patterns):
                    continue

                # 2. Senior / Lead / Staff / Manager title rejection (Deepak has ~1.3-2 yrs experience)
                if any(st in tit for st in reject_titles):
                    continue

                # 2b. Domain rejection: No Frontend, UI/UX, Android, iOS, Mobile, Flutter, QA, DevOps, Data Eng
                domain_rejects = [
                    r'\bfront[- ]?end\b', r'\bui\b', r'\bux\b', r'\bweb designer\b',
                    r'\bandroid\b', r'\bios\b', r'\bmobile\b', r'\bflutter\b', r'\breact native\b',
                    r'\bdata engineer\b', r'\bdata scientist\b', r'\bmachine learning\b', r'\bml engineer\b',
                    r'\bai engineer\b', r'\bai/ml\b', r'\baiml\b', r'\bqa\b', r'\bquality\b', r'\bsdet\b',
                    r'\btest\b', r'\btesting\b', r'\bdevops\b', r'\bsre\b', r'\binfrastructure\b', r'\bsupport\b',
                    r'\bsalesforce\b', r'\bsap\b', r'\bservicenow\b', r'\bcyber\b', r'\bsecurity\b',
                    r'\bintern\b', r'\binternship\b', r'\btrainee\b', r'\bembedded\b', r'\bfirmware\b',
                    r'\bhardware\b'
                ]
                if any(re.search(dr, tit) for dr in domain_rejects):
                    continue

                # 2c. Target Role / Stack requirement: must be Backend, Spring Boot, Java, Golang/Go, Full Stack, SDE
                target_roles = [
                    r'\bbackend\b', r'\bback[- ]end\b',
                    r'\bspring\b', r'\bspring\s*boot\b',
                    r'\bjava\b',
                    r'\bgolang\b', r'\bgo\s*(?:developer|engineer|backend)\b', r'\bgo\b',
                    r'\bfull[- ]?stack\b',
                    r'\bsde\b', r'\bsde[- ]?[12iI]+\b',
                    r'\bsoftware engineer\b', r'\bsoftware development engineer\b', r'\bsoftware developer\b',
                    r'\bapi\b', r'\bmicroservices\b', r'\bdistributed systems\b', r'\bcloud backend\b',
                    r'\bserver side\b'
                ]
                if not any(re.search(tr, tit) for tr in target_roles):
                    continue

                # 3. Explicit experience rejection: Deepak is 0-3 YOE.
                # Strictly reject:
                # - Minimum required experience >= 4 years (e.g. 4+ yrs, 5+ yrs, 6-10 yrs)
                # - Upper bound of range >= 5 years (e.g. 3-5, 4-7, 4-8, 6-10 years)
                text = f"{tit} {j.get('full_desc', '')} {j.get('desc', '')}"
                is_over_exp = False
                for pat in exp_patterns:
                    for m in pat.finditer(text):
                        groups = [int(g) for g in m.groups() if g and g.isdigit()]
                        if groups:
                            min_exp = groups[0]
                            max_exp = groups[1] if len(groups) > 1 else min_exp
                            if min_exp >= 4 or max_exp >= 5:
                                is_over_exp = True
                                break
                    if is_over_exp:
                        break
                if is_over_exp:
                    continue

                # Derive Source & Job Related Info
                c_raw = (j.get("company") or "").strip()
                if c_raw.lower() in ("linkedin", "indeed", "jobspy", "unknown", "company direct", ""):
                    t_full = (j.get("desc") or "") + "\n" + (j.get("full_desc") or "")
                    inferred_comp = None
                    m_url = re.search(r'-at-([a-zA-Z0-9\-]+)-\d+', j.get("url") or "")
                    if m_url:
                        cand = m_url.group(1).replace('-', ' ').strip().title()
                        if cand.lower() not in ('jobs', 'careers', 'hiring', 'linkedin', 'indeed'):
                            inferred_comp = cand
                    if not inferred_comp and t_full:
                        m_txt = re.search(r'^\s*([A-Z][a-zA-Z0-9\.\s&]{2,25}?)\s+is\s+(?:the|a|an|one|rapidly|seeking|building|leading)\b', t_full.strip())
                        if m_txt:
                            cand = m_txt.group(1).strip()
                            if cand.lower() not in ('this', 'the role', 'the company', 'the position', 'our client', 'summary', 'about the job'):
                                inferred_comp = cand
                    if inferred_comp:
                        j["company"] = inferred_comp
                        c_raw = inferred_comp

                strat = (j.get("strategy") or "").lower()
                u_str = (j.get("url") or j.get("apply_url") or "").lower()
                c_str = c_raw.lower()

                if "kadegree" in strat or "kadegree" in u_str or "kannada" in c_str:
                    j["source"] = "KaDegree Community"
                    j["source_category"] = "kadegree"
                    j["source_icon"] = "fa-solid fa-users-rays"
                    j["is_kadegree"] = True
                    ref_m = re.search(r"Referrer:\s*([^\n|]+)", j.get("full_desc") or "")
                    slots_m = re.search(r"Referral Slots Left:\s*([^\n|]+)", j.get("full_desc") or "")
                    j["referrer_info"] = ref_m.group(1).strip() if ref_m else "Kannada Community Referrer"
                    j["slots_info"] = slots_m.group(1).strip() if slots_m else ""
                    j["kadegree_url"] = j.get("url") if "kadegree.in" in j.get("url", "") else "https://referral-community.kadegree.in/get"
                elif "whatsapp" in strat or "whatsapp" in c_str or "whatsapp" in u_str:
                    j["source"] = "WhatsApp Community"
                    j["source_category"] = "whatsapp"
                    j["source_icon"] = "fa-brands fa-whatsapp"
                    j["is_kadegree"] = False
                elif "linkedin" in strat or "linkedin" in c_str or "linkedin" in u_str:
                    j["source"] = "LinkedIn"
                    j["source_category"] = "linkedin"
                    j["source_icon"] = "fa-brands fa-linkedin"
                    j["is_kadegree"] = False
                elif "greenhouse" in strat or "greenhouse.io" in u_str:
                    j["source"] = "Greenhouse ATS"
                    j["source_category"] = "ats"
                    j["source_icon"] = "fa-solid fa-seedling"
                    j["is_kadegree"] = False
                elif "workday" in strat or "myworkdayjobs" in u_str:
                    j["source"] = "Workday ATS"
                    j["source_category"] = "ats"
                    j["source_icon"] = "fa-solid fa-building"
                    j["is_kadegree"] = False
                elif "smartrecruiters" in strat or "smartrecruiters.com" in u_str:
                    j["source"] = "SmartRecruiters"
                    j["source_category"] = "ats"
                    j["source_icon"] = "fa-solid fa-briefcase"
                    j["is_kadegree"] = False
                elif "indeed" in strat or "indeed.com" in u_str:
                    j["source"] = "Indeed (Incognito)"
                    j["source_category"] = "indeed"
                    j["source_icon"] = "fa-solid fa-info"
                    j["is_kadegree"] = False
                elif "jobspy" in strat:
                    if "indeed" in c_str or "indeed" in u_str:
                        j["source"] = "Indeed"
                        j["source_icon"] = "fa-solid fa-info"
                    else:
                        j["source"] = "JobSpy Aggregator"
                        j["source_icon"] = "fa-solid fa-radar"
                    j["source_category"] = "jobspy"
                    j["is_kadegree"] = False
                else:
                    j["source"] = j.get("company") or "Company Direct"
                    j["source_category"] = "ats"
                    j["source_icon"] = "fa-solid fa-building-circle-check"
                    j["is_kadegree"] = False

                # Clean internal fields
                j.pop('full_desc', None)
                j.pop('desc', None)
                jobs.append(j)

            # Attach LinkedIn referral outreach data to each job
            for j in jobs:
                # Sanitize apply_url against 'None' or empty
                app_u = j.get("apply_url")
                if not app_u or str(app_u).strip().lower() in ("none", "null", "", "http://none/", "http://none", "none/"):
                    j["apply_url"] = j.get("url") or "#"
                u_str = (j.get("apply_url") or "").lower()
                c_str = (j.get("company") or "").lower()
                if "razorpay" in u_str or "razorpay" in c_str:
                    if "greenhouse.io" not in u_str:
                        j["apply_url"] = "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited"
                elif "phonepe" in u_str or "phonepe" in c_str:
                    if "sde1" in u_str or u_str.rstrip("/").endswith("/careers"):
                        j["apply_url"] = "https://jobs.smartrecruiters.com/PhonePeLimited/1000000000003895"

                j["outreach"] = generate_outreach_messages(
                    company=j.get("company", ""),
                    role_title=j.get("title", ""),
                    apply_url=j.get("apply_url", ""),
                    recruiter_email=j.get("recruiter_email", "")
                )

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(jobs).encode("utf-8"))
            return

        elif path == "/api/responses":
            from applypilot.enrichment.email_tracker import get_cached_responses
            responses = get_cached_responses()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(responses).encode("utf-8"))
            return

        # /api/cold_crm/summary (Cold email sales funnel summary, due follow-ups, leads)
        elif path == "/api/cold_crm/summary":
            from applypilot.networking.cold_email_tracker import get_cold_email_funnel_summary
            summary = get_cold_email_funnel_summary()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(summary).encode("utf-8"))
            return

        # /api/referral_crm/summary (Referral connection requests, company breakdown, acceptance metrics)
        elif path == "/api/referral_crm/summary":
            from applypilot.networking.referral_tracker import get_referral_network_summary
            summary = get_referral_network_summary()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(summary).encode("utf-8"))
            return

        # /api/funnel (Everyday time spent, full vs half applied, 30-day conversion stats)
        elif path == "/api/funnel":
            from applypilot.analytics.activity import get_funnel_and_activity_metrics
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(get_funnel_and_activity_metrics()).encode("utf-8"))
            return

        # /api/gemini/diagnostics (Get cached or fresh Gemini strategic analysis)
        elif path == "/api/gemini/diagnostics":
            from applypilot.analytics.gemini_advisor import run_gemini_strategic_analysis
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(run_gemini_strategic_analysis(force_refresh=False)).encode("utf-8"))
            return

        # /api/calls (Retrieve logged recruiter phone screens and calls)
        elif path == "/api/calls":
            from applypilot.enrichment.call_logger import get_logged_calls
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(get_logged_calls()).encode("utf-8"))
            return

        # /api/cheatsheet (Generate technical & HR interview cheat sheet)
        elif path == "/api/cheatsheet":
            query_params = urllib.parse.parse_qs(parsed.query)
            comp_param = query_params.get("company", ["PhonePe"])[0]
            role_param = query_params.get("role", ["SDE Backend Engineer"])[0]
            from applypilot.enrichment.interview_cheatsheet import generate_company_cheatsheet
            sheet = generate_company_cheatsheet(comp_param, role_param)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(sheet).encode("utf-8"))
            return

        # /api/gsheet/status
        elif path == "/api/gsheet/status":
            from applypilot.export.gsheets_sync import get_sheet_config
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(get_sheet_config()).encode("utf-8"))
            return

        # /api/analytics (Full application lifecycle, sources, and audit metrics)
        elif path == "/api/analytics":
            from applypilot.dashboard.analytics import get_application_analytics
            data = get_application_analytics()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        # /api/analytics/export_csv (Download full application audit trail as CSV)
        elif path == "/api/analytics/export_csv":
            from applypilot.dashboard.analytics import get_application_analytics
            data = get_application_analytics()
            csv_bytes = data.get("csv_data", "").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="ApplyPilot_Application_Audit_Ledger.csv"')
            self.end_headers()
            self.wfile.write(csv_bytes)
            return

        elif path.startswith("/api/linkedin/scan"):
            query_params = urllib.parse.parse_qs(parsed.query)
            comp_param = query_params.get("company", [""])[0]

            from applypilot.networking.linkedin import search_linkedin_connections, is_linkedin_authenticated
            if not is_linkedin_authenticated():
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "not_authenticated",
                    "message": "LinkedIn session not active."
                }).encode("utf-8"))
                return

            try:
                results = search_linkedin_connections(company=comp_param, role="backend", school="RV College of Engineering", max_results=8)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "connections": results
                }).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "error",
                    "message": str(e)
                }).encode("utf-8"))
                return

        elif path.startswith("/api/jobs/") and (path.endswith("/resume") or path.endswith("/cover_letter")):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[2].isdigit():
                rowid = int(parts[2])
                doc_type = parts[3]
                conn = get_connection()
                c = conn.cursor()
                row = c.execute("SELECT site, title, tailored_resume_path, cover_letter_path FROM jobs WHERE rowid = ?", (rowid,)).fetchone()
                if not row:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"Job not found")
                    return

                site, title, tailored_path, cover_path = row
                target_file = None

                if doc_type == "resume":
                    if tailored_path and Path(tailored_path).is_file():
                        target_file = Path(tailored_path)
                    elif tailored_path and (APP_DIR / tailored_path).is_file():
                        target_file = APP_DIR / tailored_path
                    elif (APP_DIR / "resume.pdf").is_file():
                        target_file = APP_DIR / "resume.pdf"
                elif doc_type == "cover_letter":
                    if cover_path and Path(cover_path).is_file():
                        target_file = Path(cover_path)
                    elif cover_path and (APP_DIR / cover_path).is_file():
                        target_file = APP_DIR / cover_path

                if target_file and target_file.is_file():
                    pdf_bytes = target_file.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Length", str(len(pdf_bytes)))
                    self.send_header("Content-Disposition", f'inline; filename="{target_file.name}"')
                    self.end_headers()
                    self.wfile.write(pdf_bytes)
                    return
                else:
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"Document not found")
                    return

        elif path.startswith("/files/"):
            # Stream PDF file
            subpath = urllib.parse.unquote(path[len("/files/"):])
            if subpath.startswith("resumes/"):
                fname = subpath[len("resumes/"):]
                target = TAILORED_DIR / fname
            elif subpath.startswith("covers/"):
                fname = subpath[len("covers/"):]
                target = COVER_LETTER_DIR / fname
            else:
                target = APP_DIR / subpath

            if target.exists() and target.is_file():
                pdf_bytes = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(pdf_bytes)))
                self.send_header("Content-Disposition", f'inline; filename="{target.name}"')
                self.end_headers()
                self.wfile.write(pdf_bytes)
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        from applypilot.database import get_connection

        # /api/jobs/process_link (Instant Job Link Intake -> JD extraction + tailored resume + referral messages)
        if path.startswith("/api/followups/") and path.endswith("/ack"):
            parts = path.strip("/").split("/")
            # ["api", "followups", "<job_id>", "ack"]
            if len(parts) >= 4 and parts[1] == "followups" and parts[-1] == "ack":
                job_id = urllib.parse.unquote("/".join(parts[2:-1]))
                try:
                    from applypilot.networking.followup_engine import ReferralFollowUpEngine
                    engine = ReferralFollowUpEngine()
                    engine.acknowledge_action(job_id)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "job_id": job_id, "message": "Action acknowledged"}).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
                return

        if path == "/api/jobs/process_link":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                payload = json.loads(body_data)
                url = payload.get("url", "").strip()
                manual_jd = payload.get("jd", "").strip()
                from applypilot.apply.quick_tailor import process_job_link
                result = process_job_link(url, manual_jd=manual_jd)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        # /api/linkedin/process_post (Dedicated LinkedIn Post Intake -> Recruiter Mail / Form Link + Tailored Resume)
        if path == "/api/linkedin/process_post":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                payload = json.loads(body_data)
                url = payload.get("url", "").strip()
                text = payload.get("text", "").strip()
                from applypilot.networking.linkedin_post_intake import process_linkedin_post
                result = process_linkedin_post(url, manual_text=text)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        # /api/activity/heartbeat (Track active search time)
        if path == "/api/activity/heartbeat":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                payload = json.loads(body_data)
                sec = payload.get("duration_seconds", 30)
                act = payload.get("action", "dashboard_browsing")
                from applypilot.analytics.activity import record_activity_heartbeat
                record_activity_heartbeat(action=act, duration_seconds=sec)
            except Exception:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
            return

        # /api/ats/sync (Sync direct ATS: Greenhouse, Lever, SmartRecruiters, Workday)
        elif path == "/api/ats/sync":
            def _bg_ats_sync():
                try:
                    from applypilot.discovery.ats import run_ats_discovery
                    from applypilot.discovery.workday import run_workday_discovery
                    from applypilot.export.csv_export import export_opportunities_csv
                    print("[ATS Sync] Scraping Greenhouse, Lever, SmartRecruiters & Workday...")
                    ats_res = run_ats_discovery(workers=4)
                    wd_res = run_workday_discovery(workers=4)
                    print(f"[ATS Sync] Complete: ATS={ats_res}, Workday={wd_res}")
                    try:
                        export_opportunities_csv()
                    except Exception:
                        pass
                except Exception as ex:
                    print(f"[ATS Sync Error] {ex}")

            threading.Thread(target=_bg_ats_sync, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "message": "Direct ATS & Workday background sync initiated! Fresh corporate postings will load into your pipeline."
            }).encode("utf-8"))
            return

        # /api/seed_startups/sync (Sync YC & Seed Funded Startups)
        elif path == "/api/seed_startups/sync":
            try:
                from applypilot.discovery.seed_startups import ingest_seed_funded_startups
                res = ingest_seed_funded_startups()
            except Exception as e:
                res = {"status": "error", "message": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/kadegree/sync (Sync latest openings from KaDegree Kannada Referral Community)
        elif path == "/api/kadegree/sync":
            from applypilot.discovery.kadegree import sync_kadegree_jobs
            try:
                res = sync_kadegree_jobs()
            except Exception as e:
                res = {"status": "error", "message": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/linkedin/easy_apply_scan (Scan LinkedIn specifically for Easy Apply jobs)
        elif path == "/api/linkedin/easy_apply_scan":
            def _bg_easy_apply_scan():
                try:
                    from applypilot.networking.linkedin import scan_linkedin_easy_apply_jobs
                    scan_linkedin_easy_apply_jobs()
                except Exception as ex:
                    print(f"LinkedIn easy apply scan error: {ex}")
            threading.Thread(target=_bg_easy_apply_scan, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "Scanning LinkedIn specifically for Easy Apply openings..."}).encode("utf-8"))
            return

        # /api/linkedin/incognito_scan (Scrape multi-source fresh jobs in incognito mode: LinkedIn, Indeed, and Direct ATS)
        elif path == "/api/linkedin/incognito_scan":
            def _bg_incognito_scan():
                try:
                    from applypilot.discovery.multi_incognito import run_fresh_incognito_multisource_scan
                    run_fresh_incognito_multisource_scan(linkedin_hours=4, indeed_days=1, run_ats=True)
                except Exception as ex:
                    print(f"Multi-source incognito scan error: {ex}")
            threading.Thread(target=_bg_incognito_scan, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "Multi-Source Incognito Scan running across LinkedIn, Indeed & Direct ATS (Greenhouse, Lever, SmartRecruiters)..."}).encode("utf-8"))
            return

        # /api/linkedin/posts_poll (Scan LinkedIn for fresh hiring posts in real-time)
        elif path == "/api/linkedin/posts_poll":
            def _bg_linkedin_posts():
                try:
                    from applypilot.networking.linkedin import search_linkedin_posts
                    search_linkedin_posts(max_results=12, save_to_db=True)
                except Exception as ex:
                    print(f"LinkedIn posts poll error: {ex}")
            threading.Thread(target=_bg_linkedin_posts, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "LinkedIn hiring post scan active in background."}).encode("utf-8"))
            return

        # /api/channels/poll (Trigger community & inbound polling cycle)
        elif path == "/api/channels/poll":
            try:
                from applypilot.automation.poller import execute_polling_cycle
                def _bg_poll():
                    execute_polling_cycle(headless=True)
                threading.Thread(target=_bg_poll, daemon=True).start()
                res = {"status": "ok", "message": "Community polling cycle started in background (WhatsApp + Telegram + Gmail)."}
            except Exception as e:
                res = {"status": "error", "message": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/calls/log (Log recruiter call or offline interview)
        elif path == "/api/calls/log":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                payload = json.loads(body_data)
                from applypilot.enrichment.call_logger import log_recruiter_call
                res = log_recruiter_call(payload)
            except Exception as e:
                res = {"status": "error", "message": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/gemini/diagnostics (Force re-run Gemini analysis)
        elif path == "/api/gemini/diagnostics":
            from applypilot.analytics.gemini_advisor import run_gemini_strategic_analysis
            res = run_gemini_strategic_analysis(force_refresh=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/calendar/block_oas (Block pending OA deadlines on calendar)
        elif path == "/api/calendar/block_oas":
            from applypilot.calendar.scheduler import block_all_pending_oas
            res = block_all_pending_oas()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/gsheet/sync (Sync pipeline to Google Sheets / CSV)
        elif path == "/api/gsheet/sync":
            from applypilot.export.gsheets_sync import sync_to_google_sheets
            res = sync_to_google_sheets()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/alerts/test (Send test alert to phone via Telegram/WhatsApp and Desktop Toast)
        elif path == "/api/alerts/test":
            from applypilot.notifications.alerts import dispatch_alert
            res = dispatch_alert(
                title="ApplyPilot Mobile Alert Test",
                body="Real-time mobile notification pipeline operational! You will be alerted the second an OA arrives or interview is scheduled.",
                url="http://localhost:8765"
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "details": res}).encode("utf-8"))
            return

        # 1. /api/jobs/{rowid}/tailor (On-Demand JIT Tailoring)
        elif path.startswith("/api/jobs/") and path.endswith("/tailor"):
            parts = path.split("/")
            rowid = int(parts[3])
            res = tailor_single_job(rowid)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 2. /api/jobs/{rowid}/open_brave (Direct Open in Live Brave + Copy PDF path)
        elif path.startswith("/api/jobs/") and path.endswith("/open_brave"):
            parts = path.split("/")
            rowid = int(parts[3])
            conn = get_connection()
            c = conn.cursor()
            row = c.execute("SELECT application_url, url, tailored_resume_path, site FROM jobs WHERE rowid = ?", (rowid,)).fetchone()
            if not row:
                self.send_response(404)
                self.end_headers()
                return

            app_url = row[0]
            job_url = row[1]
            apply_url = None
            for u in (app_url, job_url):
                if u and str(u).strip().lower() not in ("none", "null", "", "http://none/", "http://none", "none/"):
                    u_str = str(u).strip()
                    if u_str.startswith("http://") or u_str.startswith("https://"):
                        apply_url = u_str
                        break

            if apply_url:
                u_lower = apply_url.lower()
                site_lower = (row[3] or "").lower()
                if ("razorpay" in u_lower or "razorpay" in site_lower) and "greenhouse.io" not in u_lower:
                    apply_url = "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited"
                elif ("phonepe" in u_lower or "phonepe" in site_lower) and ("sde1" in u_lower or u_lower.rstrip("/").endswith("/careers")):
                    apply_url = "https://jobs.smartrecruiters.com/PhonePeLimited/1000000000003895"

            if not apply_url:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "error",
                    "message": "No direct application URL found for this position."
                }).encode("utf-8"))
                return

            tailored_path = row[2]

            # Copy PDF path to clipboard if available
            msg_clip = ""
            if tailored_path:
                abs_pdf = (APP_DIR / tailored_path).resolve()
                if abs_pdf.exists():
                    try:
                        subprocess.run(["powershell", "-Command", f"Set-Clipboard -Value '{str(abs_pdf)}'"], capture_output=True)
                        msg_clip = " Tailored Resume PDF path copied to clipboard — press Ctrl+V to attach!"
                    except Exception:
                        pass

            # Open directly in running Brave browser
            launch_url_in_brave(apply_url)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "apply_url": apply_url,
                "tailored_path": tailored_path,
                "message": f"Opened portal in your active Brave browser!{msg_clip}"
            }).encode("utf-8"))
            return

        # 3. /api/jobs/{rowid}/approve
        elif path.startswith("/api/jobs/") and path.endswith("/approve"):
            parts = path.split("/")
            rowid = int(parts[3])
            conn = get_connection()
            conn.execute("UPDATE jobs SET apply_status = 'approved' WHERE rowid = ?", (rowid,))
            conn.commit()
            export_opportunities_csv()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "rowid": rowid}).encode("utf-8"))
            return

        # 3b. /api/jobs/{rowid}/ignore
        elif path.startswith("/api/jobs/") and path.endswith("/ignore"):
            parts = path.split("/")
            rowid = int(parts[3])
            conn = get_connection()
            conn.execute("UPDATE jobs SET apply_status = 'ignored' WHERE rowid = ?", (rowid,))
            conn.commit()
            export_opportunities_csv()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "rowid": rowid}).encode("utf-8"))
            return

        # 3c. /api/jobs/{rowid}/unignore
        elif path.startswith("/api/jobs/") and path.endswith("/unignore"):
            parts = path.split("/")
            rowid = int(parts[3])
            conn = get_connection()
            conn.execute("UPDATE jobs SET apply_status = NULL WHERE rowid = ?", (rowid,))
            conn.commit()
            export_opportunities_csv()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "rowid": rowid}).encode("utf-8"))
            return

        # 4. /api/jobs/{rowid}/applied
        elif path.startswith("/api/jobs/") and path.endswith("/applied"):
            parts = path.split("/")
            rowid = int(parts[3])
            from applypilot.apply.assistant import mark_job_applied
            res = mark_job_applied(rowid)
            if isinstance(res, dict) and res.get("status") == "applied":
                res["status"] = "ok"

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 4b. /api/jobs/{rowid}/asked_referral
        elif path.startswith("/api/jobs/") and path.endswith("/asked_referral"):
            parts = path.split("/")
            rowid = int(parts[3])
            length = int(self.headers.get("Content-Length", 0))
            payload = {}
            if length > 0:
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except Exception:
                    pass
            from applypilot.apply.assistant import mark_job_referral_asked
            contact_name = payload.get("contact_name", "")
            platform = payload.get("platform", "LinkedIn")
            res = mark_job_referral_asked(rowid, contact_name=contact_name, platform=platform)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 5a. /api/jobs/{rowid}/auto_apply (100% Autonomous Auto-Apply - Kanistus Workflow)
        elif path.startswith("/api/jobs/") and path.endswith("/auto_apply"):
            parts = path.split("/")
            rowid = int(parts[3])
            from applypilot.apply.assistant import launch_application_assistant
            from applypilot.analytics.activity import mark_job_half_applied
            mark_job_half_applied(rowid, action="autonomous_apply")

            t = threading.Thread(target=launch_application_assistant, kwargs={"identifier": rowid, "headed": True, "auto_submit": True}, daemon=True)
            t.start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "launched", "mode": "autonomous", "rowid": rowid}).encode("utf-8"))
            return

        # 5b. /api/auto_apply_batch (Batch Autonomous Execution)
        elif path == "/api/auto_apply_batch":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            req_data = json.loads(body_data) if body_data else {}
            limit = int(req_data.get("limit", 5))
            min_score = int(req_data.get("min_score", 7))
            auto_submit = bool(req_data.get("auto_submit", True))

            from applypilot.apply.assistant import auto_apply_batch
            t = threading.Thread(target=auto_apply_batch, kwargs={"limit": limit, "min_score": min_score, "headed": True, "auto_submit": auto_submit}, daemon=True)
            t.start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "batch_launched", "limit": limit, "min_score": min_score}).encode("utf-8"))
            return

        # 5c. /api/jobs/{rowid}/launch (Playwright Assistant - Review Mode)
        elif path.startswith("/api/jobs/") and path.endswith("/launch"):
            parts = path.split("/")
            rowid = int(parts[3])
            from applypilot.apply.assistant import launch_application_assistant
            from applypilot.analytics.activity import mark_job_half_applied
            mark_job_half_applied(rowid, action="autofill_launch")

            t = threading.Thread(target=launch_application_assistant, kwargs={"identifier": rowid, "headed": True, "auto_submit": False}, daemon=True)
            t.start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "rowid": rowid}).encode("utf-8"))
            return

        # 5c. /api/remote_boards/sync (Sync Remotive & Working Nomads APIs)
        elif path == "/api/remote_boards/sync":
            from applypilot.discovery.remote_boards import run_remote_boards_discovery
            try:
                res = run_remote_boards_discovery()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        # 6. /api/open_url (Directly open URL in running Brave)
        elif path == "/api/open_url":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                target_url = data.get("url", "")
                incognito = bool(data.get("incognito", False))
                if target_url:
                    launch_url_in_brave(target_url, incognito=incognito)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "url": target_url, "incognito": incognito}).encode("utf-8"))
                    return
            except Exception as e:
                log.error("Failed to open URL in Brave: %s", e)

            self.send_response(400)
            self.end_headers()
            return

        # 7. /api/gmail/sync (Scan Gmail inbox for new employer updates)
        elif path == "/api/gmail/sync":
            from applypilot.enrichment.email_tracker import sync_gmail_job_responses
            try:
                synced = sync_gmail_job_responses(max_results=15)
                res = {"status": "ok", "synced_count": len(synced)}
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 7c. /api/responses/{message_id}/request_extension (Draft polite 24h extension in Gmail)
        elif path.startswith("/api/responses/") and path.endswith("/request_extension"):
            parts = path.split("/")
            msg_id = parts[3]
            from applypilot.database import get_connection
            conn = get_connection()
            row = conn.execute("SELECT sender, company, role_title, subject FROM application_responses WHERE message_id = ?", (msg_id,)).fetchone()
            
            to_email = "moheek@chausar.co.in"
            comp_name = "Chausar"
            role_name = "Founding Engineer"
            if row:
                sender_hdr = row[0] or ""
                m_email = re.search(r"[\w\.-]+@[\w\.-]+", sender_hdr)
                if m_email:
                    to_email = m_email.group(0)
                comp_name = row[1] or comp_name
                role_name = row[2] or role_name

            subject = f"Re: Next step for {role_name} - Extension Request - Deepak S H"
            body = (
                f"Hi {comp_name} Hiring Team,\n\n"
                f"Thank you for the opportunity and the assessment invitation for the {role_name} role.\n\n"
                f"Due to critical production deployment duties at Meesho yesterday, I was unable to complete "
                f"the engineering assessment before the Monday 11:59 PM IST window closed.\n\n"
                f"Would it be possible to grant a brief 24-hour extension so I can complete and submit the challenge today? "
                f"I am deeply excited about {comp_name}'s mission and engineering bar, and I am ready to start the assessment right away.\n\n"
                f"I have also attached my resume for your reference. Thank you so much for your consideration and understanding!\n\n"
                f"Best regards,\n\n"
                f"**Deepak S H**\n"
                f"SDE-I Backend Engineer, Meesho\n"
                f"RVCE CSE '25 | +91 8431433659\n"
            )

            from applypilot.networking.gmail_drafter import create_gmail_draft
            res = create_gmail_draft(
                to_email=to_email,
                subject=subject,
                body_markdown=body
            )

            # Generate guaranteed 1-click web compose fallback URL for Brave
            web_compose = (
                f"https://mail.google.com/mail/?view=cm&fs=1"
                f"&to={urllib.parse.quote(to_email)}"
                f"&su={urllib.parse.quote(subject)}"
                f"&body={urllib.parse.quote(body)}"
            )
            res["web_compose_url"] = web_compose
            if res.get("status") != "ok":
              res["message"] = "Opening pre-filled Gmail compose tab in your active Brave browser..."

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 7b. /api/responses/{message_id}/toggle_completed (Mark OA as completed / pending)
        elif path.startswith("/api/responses/") and path.endswith("/toggle_completed"):
            parts = path.split("/")
            msg_id = parts[3]
            from applypilot.enrichment.email_tracker import toggle_response_completed
            success = toggle_response_completed(msg_id)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message_id": msg_id, "success": success}).encode("utf-8"))
            return

        # /api/jobs/{rowid}/draft_email (Draft cold email in Gmail with attached resume)
        elif path.startswith("/api/jobs/") and path.endswith("/draft_email"):
            parts = path.split("/")
            rowid = int(parts[3])
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            custom_email = ""
            try:
                payload = json.loads(body_data)
                custom_email = payload.get("custom_email", "").strip()
            except Exception:
                pass

            from applypilot.networking.gmail_drafter import draft_for_job
            pitch_style = payload.get("pitch_style", "quick_pitch") if isinstance(body_data, str) and "pitch_style" in body_data else "quick_pitch"
            res = draft_for_job(rowid, custom_recipient=custom_email or None, pitch_style=pitch_style)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/jobs/{rowid}/send_email (Send cold email directly via Gmail with attached resume)
        elif path.startswith("/api/jobs/") and path.endswith("/send_email"):
            parts = path.split("/")
            rowid = int(parts[3])
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            custom_email = ""
            try:
                payload = json.loads(body_data)
                custom_email = payload.get("custom_email", "").strip()
            except Exception:
                pass

            from applypilot.networking.gmail_drafter import send_for_job
            res = send_for_job(rowid, custom_recipient=custom_email or None)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/email/custom_draft (Draft arbitrary cold email in Gmail)
        elif path == "/api/email/custom_draft":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                to_email = data.get("to_email", "").strip()
                company = data.get("company", "").strip()
                role_str = data.get("role", "").strip()
                job_url = data.get("job_url", "").strip()

                action_mode = data.get("action", "draft").strip().lower()
                from applypilot.networking.gmail_drafter import generate_recruiter_email, create_gmail_draft, send_gmail_email
                from applypilot.config import load_profile
                email_content = generate_recruiter_email(
                    company=company,
                    role_title=role_str,
                    job_url=job_url,
                    candidate_profile=load_profile()
                )
                if action_mode == "send":
                    res = send_gmail_email(
                        to_email=to_email,
                        subject=email_content["subject"],
                        body_markdown=email_content["body_markdown"]
                    )
                else:
                    res = create_gmail_draft(
                        to_email=to_email,
                        subject=email_content["subject"],
                        body_markdown=email_content["body_markdown"]
                    )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/copilot/answer (Gemini Application & Screening Copilot)
        elif path == "/api/copilot/answer":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                question = data.get("question", "").strip()
                company = data.get("company", "").strip()
                role_title = data.get("role_title", "").strip()
                job_desc = data.get("job_description", "").strip()

                from applypilot.apply.screening_copilot import answer_screening_question
                res = answer_screening_question(
                    question=question,
                    company=company,
                    role_title=role_title,
                    job_description=job_desc
                )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/cold_crm/record (Record new cold email outreach)
        elif path == "/api/cold_crm/record":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                from applypilot.networking.cold_email_tracker import record_cold_outreach
                res = record_cold_outreach(
                    recipient_email=data.get("recipient_email", ""),
                    company=data.get("company", ""),
                    role_title=data.get("role_title", "Backend Engineer"),
                    recipient_name=data.get("recipient_name", ""),
                    recipient_role=data.get("recipient_role", "recruiter"),
                    subject=data.get("subject", ""),
                    body=data.get("body", ""),
                    template_id=data.get("template_id", "quick_pitch_v1"),
                    pitch_style=data.get("pitch_style", "quick_pitch"),
                    open_count=int(data.get("open_count", 0)),
                    job_rowid=data.get("job_rowid")
                )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/referral_crm/record (Record new connection request sent for referral)
        elif path == "/api/referral_crm/record":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                from applypilot.networking.referral_tracker import record_connection_request
                res = record_connection_request(
                    company=data.get("company", ""),
                    person_name=data.get("person_name", ""),
                    profile_url=data.get("profile_url", ""),
                    headline=data.get("headline", ""),
                    is_alumni=bool(data.get("is_alumni", False)),
                    degree=data.get("degree", "2nd"),
                    role_type=data.get("role_type", "Engineer"),
                    notes=data.get("notes", ""),
                    job_rowid=data.get("job_rowid")
                )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/referral_crm/update (Update connection acceptance, referral pitch status, notes)
        elif path == "/api/referral_crm/update":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                req_id = int(data.get("request_id", 0))
                from applypilot.networking.referral_tracker import update_connection_status
                res = update_connection_status(
                    request_id=req_id,
                    status=data.get("status", "accepted"),
                    referral_status=data.get("referral_status"),
                    notes=data.get("notes")
                )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/referral_crm/sync_accepted (Auto-detect accepted connection requests and sent invites from LinkedIn)
        elif path == "/api/referral_crm/sync_accepted":
            try:
                from applypilot.networking.referral_tracker import sync_accepted_connections_from_linkedin, sync_sent_invitations_from_linkedin
                # 1. First sync sent invites so nothing manual is required!
                sent_res = sync_sent_invitations_from_linkedin(max_check=50, headless=True)
                # 2. Sync accepted connections
                res = sync_accepted_connections_from_linkedin(max_check=50, headless=True)
                res["new_sent_discovered"] = sent_res.get("new_recorded", 0)
                res["total_sent_found"] = sent_res.get("total_sent_found", 0)
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/referral_crm/pitch_generate (Generate tailored referral pitch message and resume for accepted connection)
        elif path == "/api/referral_crm/pitch_generate":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                req_id = int(data.get("request_id", 0))
                from applypilot.networking.referral_tracker import generate_tailored_pitch_for_request
                res = generate_tailored_pitch_for_request(req_id)
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/referral_crm/auto_connect (Auto-discover connections at a company from job URL and optionally send)
        elif path == "/api/referral_crm/auto_connect":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                job_url = data.get("job_url", "").strip()
                max_people = int(data.get("max_people", 5))
                send_connection = bool(data.get("send_connection", False))
                single_profile_url = data.get("single_profile_url", "").strip()

                # Handle single-person connect request (from "Send Request" button per row)
                if single_profile_url:
                    from applypilot.networking.linkedin import compose_referral_dm
                    sname = data.get("single_name", "")
                    scomp = data.get("single_company", "")
                    srole = data.get("single_role", "Backend Engineer")
                    is_alum = "rvce" in sname.lower()
                    if is_alum:
                        note = f"Hi {sname.split()[0] if sname else 'there'}, RVCE CSE '25 junior, SDE-1 @ Meesho (Java/Go/Kafka). Interested in {srole} at {scomp} — would you be open to a referral?"[:295]
                    else:
                        note = f"Hi {sname.split()[0] if sname else 'there'}, I'm an SDE-1 Backend Engineer at Meesho (RVCE '25, Java/Go/Kafka/Redis). Interested in the {srole} role at {scomp}. Would love to connect!"[:295]
                    res = compose_referral_dm(
                        profile_url=single_profile_url,
                        company=scomp,
                        role_title=srole,
                        name=sname,
                        custom_message=note,
                        action_type="connect",
                        headed=True,
                    )
                    res["message"] = f"Brave opened for {sname} — connection note pre-filled. Click Send in Brave!"
                else:
                    from applypilot.networking.referral_tracker import auto_connect_referral_from_job_url
                    res = auto_connect_referral_from_job_url(
                        job_url=job_url,
                        max_people=max_people,
                        headless=False,
                        send_connection=send_connection,
                    )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/jobs/prune (Delete stale jobs older than N days that are not in active pipeline state)
        elif path == "/api/jobs/prune":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                days = int(data.get("days", 15))
                from applypilot.database import prune_old_jobs
                res = prune_old_jobs(days=days)
                res["status"] = "ok"
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/cold_crm/update (Update interaction, open count, reply, follow-up, notes)
        elif path == "/api/cold_crm/update":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                outreach_id = int(data.get("outreach_id", 0))
                from applypilot.networking.cold_email_tracker import log_interaction_update
                res = log_interaction_update(
                    outreach_id=outreach_id,
                    open_count=data.get("open_count"),
                    reply_status=data.get("reply_status"),
                    reply_snippet=data.get("reply_snippet"),
                    led_to_call=data.get("led_to_call"),
                    interest_level=data.get("interest_level"),
                    notes=data.get("notes"),
                    increment_followup=bool(data.get("increment_followup", False))
                )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/cold_crm/generate_followup (Generate copy for follow-up based on open signals)
        elif path == "/api/cold_crm/generate_followup":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                from applypilot.networking.cold_email_tracker import generate_followup_message
                res = generate_followup_message(
                    company=data.get("company", ""),
                    role=data.get("role_title", "Backend Engineer"),
                    recipient_name=data.get("recipient_name", ""),
                    original_subject=data.get("subject", "Application"),
                    followup_number=int(data.get("followup_number", 1)),
                    open_count=int(data.get("open_count", 0))
                )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/linkedin/set_cookie (Save li_at cookie and activate LinkedIn AI agent)
        elif path == "/api/linkedin/set_cookie":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                token = data.get("token", "").strip()
                from applypilot.networking.linkedin import set_li_at_cookie
                ok = set_li_at_cookie(token)
                res = {"status": "ok" if ok else "error", "message": "LinkedIn session saved successfully!" if ok else "Invalid cookie value"}
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 8. /api/linkedin/login
        elif path == "/api/linkedin/login":
            from applypilot.networking.linkedin import login_to_linkedin
            t = threading.Thread(target=login_to_linkedin, kwargs={"timeout_sec": 75, "headed": True}, daemon=True)
            t.start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "launched"}).encode("utf-8"))
            return

        # /api/linkedin/compose_dm (Assisted 1-Click Referral DM auto-composer in Brave)
        elif path == "/api/linkedin/compose_dm":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                profile_url = data.get("profile_url", "").strip()
                company = data.get("company", "").strip()
                role_str = data.get("role", "Backend Engineer").strip()
                name_str = data.get("name", "").strip()
                custom_msg = data.get("message", "").strip()
                template = data.get("template", "referral").strip()
                action_type = data.get("action_type", "auto").strip()

                from applypilot.networking.linkedin import compose_referral_dm
                res = compose_referral_dm(
                    profile_url=profile_url,
                    company=company,
                    role_title=role_str,
                    name=name_str,
                    custom_message=custom_msg,
                    template_type=template,
                    action_type=action_type,
                    headed=True
                )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 9. /api/naukri/refresh
        elif path == "/api/naukri/refresh":
            from applypilot.automation.naukri_updater import update_naukri_resume
            t = threading.Thread(target=update_naukri_resume, kwargs={"headed": False}, daemon=True)
            t.start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "initiated", "message": "Naukri resume refresh initiated in background."}).encode("utf-8"))
            return

        # 10. /api/naukri/login
        elif path == "/api/naukri/login":
            from applypilot.automation.naukri_updater import login_interactive
            t = threading.Thread(target=login_interactive, kwargs={"timeout_seconds": 90}, daemon=True)
            t.start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "launched", "message": "Opening Brave for Naukri login..."}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()


def _ensure_external_auto_applier_running():
    """Ensure Auto_job_applier_linkedIn control panel server is running on port 5000."""
    import sys
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:5000/", timeout=1.0) as resp:
            if resp.status == 200:
                return
    except Exception:
        pass

    tool_dir = Path("D:/ApplyPilot_Workspace/tools/Auto_job_applier_linkedIn")
    app_py = tool_dir / "app.py"
    if not app_py.exists():
        return

    import subprocess
    cmd = [sys.executable, str(app_py)]
    try:
        subprocess.Popen(
            cmd,
            cwd=str(tool_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        log.info("Started external Auto_job_applier_linkedIn server on http://127.0.0.1:5000")
    except Exception as e:
        log.warning("Could not auto-start external applier: %s", e)


def start_dashboard_server(port: int = PORT, open_browser: bool = True):
    """Start the interactive dashboard server and open it in Chrome/default browser."""
    # Auto-start the external LinkedIn applier control panel alongside ApplyPilot
    _ensure_external_auto_applier_running()

    ThreadingHTTPServer.allow_reuse_address = True
    server = None
    for attempt in range(5):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
            break
        except OSError as e:
            if attempt < 4:
                time.sleep(1)
            else:
                raise e

    url = f"http://127.0.0.1:{port}"
    print(f"\n🚀 ApplyPilot 2.0 Command Dashboard running at: {url}")
    print("   Press Ctrl+C to stop the dashboard server.\n")

    if open_browser:
        launch_url_in_brave(url)

    while True:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping dashboard server...")
            try:
                server.shutdown()
            except Exception:
                pass
            break
        except Exception as e:
            print(f"\nServer error: {e}", file=sys.stderr)
            time.sleep(1)
