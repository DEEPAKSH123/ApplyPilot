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
import sqlite3
import subprocess
import threading
import urllib.parse
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from applypilot.config import APP_DIR, DB_PATH, TAILORED_DIR, COVER_LETTER_DIR, load_profile
from applypilot.database import get_connection
from applypilot.export.csv_export import export_opportunities_csv
from applypilot.networking.outreach import generate_outreach_messages
from applypilot.scoring.jit_tailor import tailor_single_job

log = logging.getLogger(__name__)

PORT = 8765
BRAVE_EXE = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"


def launch_url_in_brave(url: str) -> bool:
    """Launch URL in Brave browser using Windows Shell or direct process without pipe redirection."""
    if not url or not (str(url).startswith("http://") or str(url).startswith("https://")):
        return False
    try:
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
                subprocess.Popen([BRAVE_EXE, url])
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
  <title>⚡ ApplyPilot 2.0 - Command & Review Dashboard</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
  <style>
    /* Premier Nordic Aurora Cyber Theme */
    :root {
      --bg: #060913;
      --bg-gradient: radial-gradient(circle at 10% 12%, rgba(6, 182, 212, 0.22) 0%, transparent 45%),
                     radial-gradient(circle at 90% 15%, rgba(16, 185, 129, 0.18) 0%, transparent 45%),
                     radial-gradient(circle at 50% 85%, rgba(59, 130, 246, 0.14) 0%, transparent 55%),
                     #060913;
      --panel: rgba(11, 19, 38, 0.82);
      --panel-border: rgba(56, 189, 248, 0.16);
      --card-bg: rgba(13, 22, 44, 0.88);
      --card-border: rgba(56, 189, 248, 0.18);
      --text: #f0fdf4;
      --text-muted: #94a3b8;
      --accent: #06b6d4;
      --accent-glow: rgba(6, 182, 212, 0.35);
      --brand-grad: linear-gradient(135deg, #00f2fe, #38bdf8, #34d399);
      --tab-active: linear-gradient(135deg, #0284c7, #0d9488);
      --emerald: #10b981;
      --emerald-glow: rgba(16, 185, 129, 0.35);
      --amber: #f59e0b;
      --cyan: #06b6d4;
      --purple: #38bdf8;
      --rose: #f43f5e;
    }

    header {
      background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--panel-border);
      padding: 14px 32px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 100;
      box-shadow: 0 4px 24px rgba(0,0,0,0.4);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .brand-logo {
      font-size: 24px;
      color: #38bdf8;
      filter: drop-shadow(0 0 10px rgba(56, 189, 248, 0.6));
    }
    .brand-title {
      font-size: 21px;
      font-weight: 800;
      letter-spacing: -0.5px;
      background: var(--brand-grad);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .status-pill {
      display: flex;
      align-items: center;
      gap: 8px;
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: #34d399;
      font-size: 11px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 999px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .pulse-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #10b981;
      box-shadow: 0 0 8px #10b981;
      animation: pulse 1.6s infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.4; transform: scale(0.85); }
    }

    /* Candidate Quick-Copy Bar */
    .quick-bar {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .quick-pill {
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.12);
      color: #cbd5e1;
      font-size: 12px;
      padding: 5px 12px;
      border-radius: 999px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s ease;
      font-family: 'JetBrains Mono', monospace;
    }
    .quick-pill:hover {
      background: rgba(99, 102, 241, 0.25);
      border-color: #818cf8;
      color: #fff;
      transform: translateY(-1px);
    }

    .container {
      max-width: 1440px;
      margin: 0 auto;
      padding: 24px 32px;
    }

    /* Stats Grid */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .stat-card {
      background: var(--panel);
      backdrop-filter: blur(12px);
      border: 1px solid var(--panel-border);
      padding: 18px 20px;
      border-radius: 14px;
      display: flex;
      flex-direction: column;
      position: relative;
      overflow: hidden;
      transition: all 0.25s ease;
    }
    .stat-card:hover {
      transform: translateY(-3px);
      box-shadow: 0 10px 25px rgba(0,0,0,0.3);
      border-color: rgba(255,255,255,0.2);
    }
    .stat-card .label {
      font-size: 11px;
      color: var(--text-muted);
      text-transform: uppercase;
      font-weight: 700;
      letter-spacing: 0.6px;
    }
    .stat-card .val {
      font-size: 32px;
      font-weight: 800;
      margin-top: 4px;
      letter-spacing: -1px;
    }

    /* Queue Announcement Banner */
    .queue-banner {
      background: linear-gradient(90deg, rgba(99, 102, 241, 0.18), rgba(168, 85, 247, 0.18));
      border: 1px solid rgba(168, 85, 247, 0.35);
      border-radius: 12px;
      padding: 14px 20px;
      margin-bottom: 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    .queue-banner-title {
      font-weight: 700;
      font-size: 14px;
      color: #e0e7ff;
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
      gap: 6px;
      background: rgba(15, 23, 42, 0.7);
      padding: 5px;
      border-radius: 12px;
      border: 1px solid var(--panel-border);
      backdrop-filter: blur(10px);
    }
    .tab-btn {
      background: transparent;
      color: var(--text-muted);
      border: none;
      padding: 9px 18px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.2s ease;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .tab-btn:hover {
      color: #fff;
    }
    .tab-btn.active {
      background: var(--tab-active);
      color: white;
      box-shadow: 0 4px 14px var(--accent-glow);
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
      gap: 18px;
    }
    .job-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 22px 26px;
      display: flex;
      flex-direction: column;
      gap: 16px;
      transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
      position: relative;
      backdrop-filter: blur(14px);
    }
    .job-card:hover {
      transform: translateY(-3px);
      box-shadow: 0 16px 36px rgba(0,0,0,0.45);
      border-color: rgba(129, 140, 248, 0.4);
    }

    /* Score 9 Dream Match Special Styling */
    .job-card.super-match {
      border: 1.5px solid #10b981;
      box-shadow: 0 0 24px rgba(16, 185, 129, 0.18);
      background: linear-gradient(135deg, rgba(6, 78, 59, 0.25), rgba(15, 23, 42, 0.85));
    }
    .job-card.super-match::before {
      content: '🔥 DREAM 9/10 MATCH';
      position: absolute;
      top: -10px;
      right: 28px;
      background: linear-gradient(90deg, #10b981, #059669);
      color: #fff;
      font-size: 10px;
      font-weight: 800;
      padding: 3px 10px;
      border-radius: 999px;
      letter-spacing: 0.5px;
      box-shadow: 0 2px 8px rgba(16, 185, 129, 0.5);
    }

    /* Score 8 Top Match Styling */
    .job-card.top-match {
      border: 1.5px solid #06b6d4;
      box-shadow: 0 0 20px rgba(6, 182, 212, 0.15);
    }
    .job-card.top-match::before {
      content: '⚡ TOP TIER 8/10';
      position: absolute;
      top: -10px;
      right: 28px;
      background: linear-gradient(90deg, #06b6d4, #2563eb);
      color: #fff;
      font-size: 10px;
      font-weight: 800;
      padding: 3px 10px;
      border-radius: 999px;
      letter-spacing: 0.5px;
      box-shadow: 0 2px 8px rgba(6, 182, 212, 0.4);
    }

    .card-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
    }
    .job-meta {
      display: flex;
      gap: 16px;
      align-items: center;
    }
    .company-avatar {
      width: 48px;
      height: 48px;
      border-radius: 12px;
      background: linear-gradient(135deg, #1e1b4b, #3730a3);
      border: 1px solid rgba(255,255,255,0.15);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 18px;
      font-weight: 800;
      color: #38bdf8;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
      flex-shrink: 0;
    }
    .job-title-row {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    .job-title {
      font-size: 18px;
      font-weight: 800;
      color: #fff;
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
      width: 54px;
      height: 54px;
      border-radius: 12px;
      font-weight: 800;
      flex-shrink: 0;
      box-shadow: 0 4px 14px rgba(0,0,0,0.3);
    }
    .score-badge .num { font-size: 20px; line-height: 1; }
    .score-badge .denom { font-size: 9px; opacity: 0.8; text-transform: uppercase; font-weight: 700; margin-top: 2px; }

    .score-9 { background: linear-gradient(135deg, #059669, #10b981); color: #fff; box-shadow: 0 0 16px rgba(16, 185, 129, 0.5); }
    .score-8 { background: linear-gradient(135deg, #0284c7, #06b6d4); color: #fff; box-shadow: 0 0 14px rgba(6, 182, 212, 0.4); }
    .score-7 { background: linear-gradient(135deg, #4f46e5, #6366f1); color: #fff; }
    .score-mid { background: #334155; color: #cbd5e1; }
    .score-low { background: #1e293b; color: #64748b; }

    .badges-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      margin-top: 2px;
    }
    .tag {
      font-size: 11px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 6px;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .tag-resume { background: #1e3a5f; color: #60a5fa; border: 1px solid rgba(96, 165, 250, 0.3); }
    .tag-cover { background: #1e3a3f; color: #34d399; border: 1px solid rgba(52, 211, 153, 0.3); }
    .tag-email { background: #3b1d54; color: #e879f9; border: 1px solid rgba(232, 121, 249, 0.3); }
    .tag-approved { background: #064e3b; color: #6ee7b7; border: 1px solid rgba(110, 231, 183, 0.4); }
    .tag-applied { background: #713f12; color: #fde047; border: 1px solid rgba(253, 224, 71, 0.4); }

    .reasoning {
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 10px;
      padding: 12px 16px;
      font-size: 13px;
      color: #cbd5e1;
      line-height: 1.55;
    }

    /* Actions Bar */
    .actions-bar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      border-top: 1px solid rgba(255, 255, 255, 0.07);
      padding-top: 14px;
    }
    .btn {
      padding: 8px 14px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 700;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      text-decoration: none;
      transition: all 0.15s ease;
    }
    .btn:hover {
      transform: translateY(-1px);
      filter: brightness(1.1);
    }
    .btn-autofill {
      background: linear-gradient(135deg, #0284c7, #10b981);
      color: white;
      font-weight: 700;
      box-shadow: 0 2px 10px rgba(16, 185, 129, 0.35);
    }
    .btn-autofill:hover {
      background: linear-gradient(135deg, #0369a1, #059669);
      color: #fff;
      transform: translateY(-1px);
      box-shadow: 0 4px 14px rgba(16, 185, 129, 0.5);
    }

    .btn-brave {
      background: linear-gradient(135deg, #ea580c, #f97316);
      color: white;
      box-shadow: 0 2px 10px rgba(249, 115, 22, 0.3);
    }
    .btn-tailor {
      background: linear-gradient(135deg, #9333ea, #a855f7);
      color: white;
      box-shadow: 0 2px 10px rgba(168, 85, 247, 0.3);
    }
    .btn-outreach {
      background: #0284c7;
      color: white;
    }
    .btn-preview {
      background: #334155;
      color: #e2e8f0;
    }
    .btn-approve {
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid #10b981;
      color: #34d399;
    }
    .btn-applied {
      background: rgba(245, 158, 11, 0.15);
      border: 1px solid #f59e0b;
      color: #fbbf24;
    }
    .btn-email {
      background: linear-gradient(135deg, #ea4335, #dc2626);
      color: white;
      box-shadow: 0 2px 10px rgba(234, 67, 53, 0.3);
    }
    .btn-email-ghost {
      background: rgba(234, 67, 53, 0.12);
      border: 1px solid rgba(234, 67, 53, 0.35);
      color: #fca5a5;
    }
    .btn-email-ghost:hover {
      background: rgba(234, 67, 53, 0.25);
      color: #fff;
    }

    /* Response Cards & Sentiment Badges */
    .response-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 22px 26px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      position: relative;
      backdrop-filter: blur(14px);
      transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .response-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 16px 36px rgba(0,0,0,0.45);
    }
    .response-card.sentiment-positive, .response-card.cat-interview {
      border: 1.5px solid #10b981;
      background: linear-gradient(135deg, rgba(6, 78, 59, 0.35), rgba(15, 23, 42, 0.95));
      box-shadow: 0 0 24px rgba(16, 185, 129, 0.25);
    }
    .response-card.cat-oa {
      border: 1.5px solid #f59e0b;
      background: linear-gradient(135deg, rgba(120, 53, 15, 0.35), rgba(15, 23, 42, 0.95));
      box-shadow: 0 0 26px rgba(245, 158, 11, 0.25);
    }
    .response-card.cat-oa.is-done {
      opacity: 0.65;
      border: 1px solid #059669;
      box-shadow: none;
    }
    .response-card.sentiment-negative, .response-card.cat-rejected {
      border: 1.5px solid rgba(244, 63, 94, 0.5);
      background: linear-gradient(135deg, rgba(136, 19, 55, 0.25), rgba(15, 23, 42, 0.95));
      box-shadow: 0 0 20px rgba(244, 63, 94, 0.12);
    }
    .response-card.cat-apply {
      border: 1.5px solid #06b6d4;
      background: linear-gradient(135deg, rgba(14, 116, 144, 0.25), rgba(15, 23, 42, 0.95));
      box-shadow: 0 0 22px rgba(6, 182, 212, 0.2);
    }
    .response-card.sentiment-neutral, .response-card.cat-acknowledged {
      border: 1.5px solid rgba(148, 163, 184, 0.25);
      background: linear-gradient(135deg, rgba(30, 41, 59, 0.35), rgba(15, 23, 42, 0.9));
      box-shadow: 0 0 16px rgba(148, 163, 184, 0.08);
    }
    .resp-filter-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 16px;
      padding: 12px 16px;
      background: rgba(15, 23, 42, 0.75);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 12px;
    }
    .resp-pill {
      background: rgba(30, 41, 59, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.12);
      color: #94a3b8;
      font-size: 12px;
      font-weight: 700;
      padding: 7px 15px;
      border-radius: 999px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }
    .resp-pill:hover, .resp-pill.active {
      background: rgba(6, 182, 212, 0.25);
      border-color: #06b6d4;
      color: #fff;
    }
    .resp-pill.pill-oa.active {
      background: rgba(245, 158, 11, 0.25);
      border-color: #f59e0b;
      color: #fde047;
    }
    .resp-pill.pill-interview.active {
      background: rgba(16, 185, 129, 0.25);
      border-color: #10b981;
      color: #6ee7b7;
    }
    .resp-pill.pill-rejected.active {
      background: rgba(244, 63, 94, 0.25);
      border-color: #f43f5e;
      color: #fca5a5;
    }
    .resp-pill.pill-apply.active {
      background: rgba(56, 189, 248, 0.25);
      border-color: #38bdf8;
      color: #bae6fd;
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

    /* Confetti Canvas */
    #confetti-canvas {
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      pointer-events: none;
      z-index: 999999;
    }
  </style>
</head>
<body>
  <canvas id="confetti-canvas"></canvas>

  <header>
    <div class="brand">
      <i class="fa-solid fa-bolt-lightning brand-logo"></i>
      <div>
        <div class="brand-title">ApplyPilot 2.0</div>
      </div>
      <div class="status-pill">
        <div class="pulse-dot"></div>
        <span>Live System Active</span>
      </div>
    </div>

    <!-- Quick Copy Drawer & Theme Picker -->
    <div class="quick-bar">
      <div class="quick-pill" onclick="copyText('8431433659', 'Phone Number')"><i class="fa-solid fa-phone" style="color:#38bdf8;"></i> 8431433659</div>
      <div class="quick-pill" onclick="copyText('deepakshkarkala@gmail.com', 'Email')"><i class="fa-solid fa-envelope" style="color:#34d399;"></i> deepakshkarkala@gmail.com</div>
      <div class="quick-pill" onclick="copyText('https://www.linkedin.com/in/deepak-s-h-82b772254', 'LinkedIn URL')"><i class="fa-brands fa-linkedin" style="color:#60a5fa;"></i> LinkedIn</div>
      <div class="quick-pill" onclick="copyText('20 LPA', 'Current CTC')"><i class="fa-solid fa-indian-rupee-sign" style="color:#f59e0b;"></i> 20 LPA</div>
      <div class="quick-pill" onclick="copyText('Immediate', 'Notice Period')"><i class="fa-solid fa-bolt" style="color:#ec4899;"></i> Immediate Notice</div>
      <a href="https://www.linkedin.com/feed/" target="_blank" rel="noopener noreferrer" class="quick-pill" style="background: #0a66c2; color: #fff; font-weight: 700; text-decoration: none;"><i class="fa-brands fa-linkedin"></i> Open LinkedIn</a>
      <a href="https://referral-community.kadegree.in/get" target="_blank" rel="noopener noreferrer" class="quick-pill" style="background: linear-gradient(135deg, #b45309, #d97706); color: #fff; font-weight: 700; text-decoration: none;"><i class="fa-solid fa-users"></i> KaDegree (ಕನ್ನಡ Community)</a>
      <a href="https://mail.google.com/mail/u/0/#drafts" target="_blank" rel="noopener noreferrer" class="quick-pill" style="background: #ea4335; color: #fff; font-weight: 700; text-decoration: none;"><i class="fa-solid fa-envelope"></i> Gmail Drafts</a>
      <div class="quick-pill" onclick="openCustomDraftModal()" style="background: rgba(234, 67, 53, 0.2); border: 1px solid #ea4335; color: #fca5a5; font-weight: 700; cursor: pointer;"><i class="fa-solid fa-pen-nib"></i> + Draft Cold Email</div>

      
    </div>
  </header>

  <div class="container">
    <!-- Energetic Stats Cards -->
    <div class="stats-grid">
      <div class="stat-card">
        <span class="label">Total Discoveries</span>
        <span class="val" id="stat-total" style="color: #38bdf8;">0</span>
      </div>
      <div class="stat-card" style="border-color: rgba(16, 185, 129, 0.4);">
        <span class="label">🔥 9/10 Dream Matches</span>
        <span class="val" id="stat-nine" style="color: #34d399;">0</span>
      </div>
      <div class="stat-card">
        <span class="label">⚡ High Fit (≥ 7)</span>
        <span class="val" id="stat-high" style="color: #818cf8;">0</span>
      </div>
      <div class="stat-card">
        <span class="label">🎯 Approved Shortlist</span>
        <span class="val" id="stat-approved" style="color: #a855f7;">0</span>
      </div>
      <div class="stat-card">
        <span class="label">📄 Tailored Resumes</span>
        <span class="val" id="stat-tailored" style="color: #38bdf8;">0</span>
      </div>
      <div class="stat-card" style="border-color: rgba(245, 158, 11, 0.5); cursor: pointer;" onclick="setTab('responses'); filterResponsesCategory('oa');">
        <span class="label"><i class="fa-solid fa-clock-rotate-left"></i> Active OAs & Tests</span>
        <span class="val" id="stat-oa" style="color: #fbbf24;">0</span>
      </div>
      <div class="stat-card" style="border-color: rgba(52, 211, 153, 0.4); cursor: pointer;" onclick="setTab('responses'); filterResponsesCategory('all');">
        <span class="label">📬 Recruiter Replies</span>
        <span class="val" id="stat-responses" style="color: #34d399;">0</span>
      </div>
      <div class="stat-card">
        <span class="label">🏆 Applications Applied</span>
        <span class="val" id="stat-applied" style="color: #fbbf24;">0</span>
      </div>
    </div>

    <!-- Urgent OA Alert Bar (Displays when any pending OA exists) -->
    <div id="urgent-oa-alert" class="queue-banner" style="display: none; background: linear-gradient(90deg, rgba(180, 83, 9, 0.45), rgba(15, 23, 42, 0.95)); border: 1.5px solid #f59e0b; justify-content: space-between; align-items: center; box-shadow: 0 0 24px rgba(245, 158, 11, 0.25);">
      <div style="display: flex; align-items: center; gap: 14px;">
        <i class="fa-solid fa-triangle-exclamation" style="color: #fbbf24; font-size: 22px;"></i>
        <div>
          <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px; color: #fde047; font-weight: 800;">⚡ ACTION REQUIRED: ONLINE ASSESSMENT (OA) DUE</span>
          <div id="urgent-oa-title" style="font-size: 14.5px; font-weight: 700; color: #fff; margin-top: 2px;"></div>
        </div>
      </div>
      <div style="display: flex; gap: 10px; align-items: center;">
        <a id="urgent-oa-link" href="#" target="_blank" rel="noopener noreferrer" class="btn btn-brave" style="background: linear-gradient(135deg, #d97706, #f59e0b); border-color: #f59e0b; text-decoration: none; padding: 7px 16px;">
          <i class="fa-solid fa-code"></i> Open Assessment in Brave
        </a>
        <button class="btn btn-preview" onclick="setTab('responses'); filterResponsesCategory('oa');" style="white-space: nowrap;">
          <i class="fa-solid fa-list-check"></i> View in Dashboard
        </button>
      </div>
    </div>

    <!-- Active Tab Announcement Banner -->
    <div id="queue-banner" class="queue-banner" style="display: none;">
      <div class="queue-banner-title">
        <i class="fa-solid fa-bullseye" style="color: #c084fc; font-size: 18px;"></i>
        <span><strong>Approved Shortlist:</strong> Apply to these vetted roles today. Click <strong>[🚀 Open in Brave]</strong> or generate JIT tailored resumes on-demand!</span>
      </div>
    </div>

    <!-- Gmail Response Announcement Banner -->
    <div id="responses-banner" class="queue-banner" style="display: none; background: linear-gradient(90deg, rgba(6, 78, 59, 0.35), rgba(15, 23, 42, 0.85)); border-color: rgba(16, 185, 129, 0.4); justify-content: space-between; align-items: center;">
      <div class="queue-banner-title">
        <i class="fa-solid fa-envelope-circle-check" style="color: #34d399; font-size: 20px;"></i>
        <span><strong>Gmail Application Response Tracker:</strong> Monitoring interviews, coding challenges, and recruiter replies from Deepak's connected Gmail (<code>deepakshkarkala@gmail.com</code>).</span>
      </div>
      <button class="btn btn-preview" onclick="syncGmailNow()" style="background: rgba(16, 185, 129, 0.2); border: 1px solid #10b981; color: #34d399; font-weight: 700; white-space: nowrap;">
        <i class="fa-solid fa-arrows-rotate"></i> Sync Gmail Inbox
      </button>
    </div>

    <!-- Tabs & Search -->
    <div class="controls">
      <div class="tabs">
        <button class="tab-btn active" onclick="setTab('high')">
          <i class="fa-solid fa-fire"></i> High Fit (≥ 7)
          <span class="tab-badge" id="badge-high">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('top')">
          <i class="fa-solid fa-bolt"></i> Top Matches (≥ 8)
          <span class="tab-badge" id="badge-top">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('approved')" style="color: #c084fc;">
          <i class="fa-solid fa-circle-check"></i> Approved Queue
          <span class="tab-badge" id="badge-approved" style="background:#7c3aed;color:#fff;">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('responses')" style="color: #34d399;">
          <i class="fa-solid fa-envelope-open-text"></i> Gmail Tracker
          <span class="tab-badge" id="badge-responses" style="background:#059669;color:#fff;">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('applied')">
          <i class="fa-solid fa-trophy"></i> Applied
          <span class="tab-badge" id="badge-applied">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('all')">All Opportunities</button>
      </div>

      <div class="search-box">
        <i class="fa-solid fa-magnifying-glass"></i>
        <input type="text" id="search-input" placeholder="Search company, skills (Java, Go, Kafka)..." oninput="renderJobs()">
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

    <div id="jobs-container" class="jobs-grid"></div>
  </div>

  <!-- PDF Preview Modal -->
  <div id="pdf-modal" class="modal-backdrop">
    <div class="modal-content">
      <div class="modal-header">
        <h3 id="modal-title">PDF Preview</h3>
        <button class="modal-close" onclick="closeModal()"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div class="modal-body">
        <iframe id="pdf-frame" src=""></iframe>
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
          <button class="btn" id="btn-submit-custom-draft" style="background: linear-gradient(135deg, #ea4335, #dc2626); color:white; font-weight:700; padding: 9px 18px;" onclick="submitCustomDraft()">
            <i class="fa-solid fa-paper-plane"></i> Create Gmail Draft (w/ Resume)
          </button>
        </div>
      </div>
    </div>
  </div>

<div id="toast" class="toast"></div>

  <script>
    let allJobs = [];
    let allResponses = [];
    let currentTab = 'high';

    

    
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

      document.getElementById('badge-high').textContent = allJobs.filter(j => j.fit_score >= 7).length;
      document.getElementById('badge-top').textContent = allJobs.filter(j => j.fit_score >= 8).length;
      document.getElementById('badge-approved').textContent = allJobs.filter(j => j.apply_status === 'approved').length;
      document.getElementById('badge-applied').textContent = allJobs.filter(j => j.apply_status === 'applied').length;
      document.getElementById('badge-responses').textContent = allResponses.length;

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

      // Update Top Urgent OA Banner
      const urgentBanner = document.getElementById('urgent-oa-alert');
      if (urgentBanner) {
        if (activeOAs.length > 0) {
          urgentBanner.style.display = 'flex';
          const firstOa = activeOAs[0];
          const urgentTitle = document.getElementById('urgent-oa-title');
          if (urgentTitle) {
            urgentTitle.innerHTML = `<strong>${firstOa.company}</strong> (${firstOa.role_title || 'Software Engineer'}) &mdash; <span style="color:#fde047; font-weight:800;"><i class="fa-solid fa-clock"></i> Deadline: ${firstOa.due_date || 'Urgent assessment'}</span>`;
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

    function setTab(tab) {
      currentTab = tab;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      const activeBtn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick') && b.getAttribute('onclick').includes(`'${tab}'`));
      if (activeBtn) activeBtn.classList.add('active');

      const qBanner = document.getElementById('queue-banner');
      const rBanner = document.getElementById('responses-banner');
      const respFilterBar = document.getElementById('resp-filter-bar');

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
                  </div>
                </div>
              </div>
              <div>${badgeHtml}</div>
            </div>

            ${extraBanner}

            <div style="background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 10px; padding: 14px; font-size: 13px; color: #cbd5e1; line-height: 1.6;">
              <div style="font-weight: 700; color: #f8fafc; margin-bottom: 6px; display: flex; align-items: center; gap: 8px;">
                <i class="fa-solid fa-comment-dots" style="color: ${cat === 'oa' ? '#fbbf24' : cat === 'interview_selected' ? '#34d399' : cat === 'rejected' ? '#fb7185' : '#38bdf8'};"></i>
                <span>${r.status}: ${r.summary}</span>
              </div>
              <div style="color: #94a3b8; font-style: italic; font-size: 12.5px; border-left: 2px solid rgba(255,255,255,0.15); padding-left: 10px; margin-top: 6px;">
                "${r.body_snippet}"
              </div>
            </div>

            <div class="actions-bar" style="margin-top: 4px;">
              ${actionButtons}
              <button class="btn btn-preview" onclick="showToast('Email Subject: ' + '${(r.subject || '').replace(/'/g, "\'")}')">
                <i class="fa-solid fa-envelope"></i> Subject: ${(r.subject || '').substring(0, 42)}...
              </button>
            </div>
          </div>
        `;
      }).join('');
    }

    function renderJobs() {
      if (currentTab === 'responses') {
        renderResponses();
        return;
      }

      const q = document.getElementById('search-input').value.toLowerCase().trim();
      let filtered = allJobs.filter(job => {
        if (currentTab === 'high' && (job.fit_score === null || job.fit_score < 7)) return false;
        if (currentTab === 'top' && (job.fit_score === null || job.fit_score < 8)) return false;
        if (currentTab === 'approved' && job.apply_status !== 'approved') return false;
        if (currentTab === 'applied' && job.apply_status !== 'applied') return false;

        if (q) {
          const hay = `${job.company} ${job.title} ${job.location} ${job.score_reasoning || ''}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
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
        const cardClass = score >= 9 ? 'job-card super-match' : score >= 8 ? 'job-card top-match' : 'job-card';
        const hasResume = !!job.tailored_resume_path;
        const hasCover = !!job.cover_letter_path;
        const isApproved = job.apply_status === 'approved';
        const isApplied = job.apply_status === 'applied';

        const initial = (job.company || 'C').charAt(0).toUpperCase();

        return `
          <div class="${cardClass}" id="card-${job.rowid}">
            <div class="card-top">
              <div class="job-meta">
                <div class="company-avatar">${initial}</div>
                <div>
                  <div class="job-title-row">
                    <span class="job-title">${job.title}</span>
                  </div>
                  <div class="job-sub">
                    <span><i class="fa-regular fa-building"></i> <strong>${job.company}</strong></span>
                    <span><i class="fa-solid fa-location-dot"></i> ${job.location}</span>
                  </div>
                </div>
              </div>

              <div class="score-badge ${scoreClass}">
                <span class="num">${score}</span>
                <span class="denom">FIT / 10</span>
              </div>
            </div>

            <div class="badges-row">
              ${job.recruiter_email ? `<span class="tag tag-email"><i class="fa-solid fa-envelope"></i> ${job.recruiter_email}</span>` : ''}
              ${hasResume ? `<span class="tag tag-resume"><i class="fa-solid fa-file-pdf"></i> Tailored Resume Ready</span>` : '<span class="tag" style="background:#334155;color:#94a3b8;"><i class="fa-solid fa-clock"></i> Base Resume</span>'}
              ${hasCover ? `<span class="tag tag-cover"><i class="fa-solid fa-envelope-open-text"></i> Cover Letter Ready</span>` : ''}
              ${isApplied ? `<span class="tag tag-applied"><i class="fa-solid fa-check-double"></i> Applied</span>` : isApproved ? `<span class="tag tag-approved"><i class="fa-solid fa-thumbs-up"></i> Approved Shortlist</span>` : ''}
            </div>

            ${job.score_reasoning ? `<div class="reasoning">${job.score_reasoning.replace(/\\n/g, '<br>')}</div>` : ''}

            <div class="actions-bar">
              <!-- 1-Click Application Assistant & Autofill Button -->
              <button class="btn btn-autofill" id="btn-autofill-${job.rowid}" onclick="launchAutofill(${job.rowid})">
                <i class="fa-solid fa-wand-magic-sparkles"></i> Autofill in Brave
              </button>

              <!-- Live Brave Browser Launcher -->
              <a href="${job.apply_url || job.url || '#'}" target="_blank" rel="noopener noreferrer" class="btn btn-brave" onclick="handleJobClick(event, ${job.rowid}, '${encodeURIComponent(job.tailored_resume_path || "")}')" style="text-decoration: none;">
                <i class="fa-brands fa-brave"></i> Open Portal
              </a>

              <!-- On-Demand Tailoring Button (JIT) -->
              ${!hasResume ? `
                <button class="btn btn-tailor" id="btn-tailor-${job.rowid}" onclick="tailorSingleJob(${job.rowid})">
                  <i class="fa-solid fa-wand-magic-sparkles"></i> Tailor Resume (AI)
                </button>
              ` : `
                <button class="btn btn-preview" onclick="previewPDF('${job.tailored_resume_path}', '${job.company} - ${job.title} Resume')">
                  <i class="fa-solid fa-eye"></i> View Resume PDF
                </button>
              `}

              ${hasCover ? `
                <button class="btn btn-preview" onclick="previewPDF('${job.cover_letter_path}', '${job.company} - Cover Letter')">
                  <i class="fa-solid fa-eye"></i> Cover PDF
                </button>
              ` : ''}

              <!-- Referral Outreach Modal Button -->
              <button class="btn btn-outreach" onclick="openReferralModal(${job.rowid})">
                <i class="fa-solid fa-people-arrows"></i> Referral Outreach
              </button>

              ${job.recruiter_email ? `
                <button class="btn btn-email" id="btn-draft-${job.rowid}" onclick="draftEmailForJob(${job.rowid})">
                  <i class="fa-solid fa-envelope-circle-check"></i> Draft in Gmail (w/ Resume)
                </button>
              ` : `
                <button class="btn btn-email-ghost" onclick="promptCustomDraft(${job.rowid})">
                  <i class="fa-regular fa-envelope"></i> Draft to Recruiter
                </button>
              `}

              ${!isApproved && !isApplied ? `
                <button class="btn btn-approve" onclick="approveJob(${job.rowid})">
                  <i class="fa-solid fa-check"></i> Approve
                </button>
              ` : ''}

              ${!isApplied ? `
                <button class="btn btn-applied" onclick="markApplied(${job.rowid})">
                  <i class="fa-solid fa-check-circle"></i> Mark Applied
                </button>
              ` : ''}
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
          showToast('✓ Resume tailored & PDF compiled successfully!');
          triggerConfetti();
          await fetchJobs();
          if (data.tailored_resume_path) {
            previewPDF(data.tailored_resume_path, `${data.company} - ${data.job_title} Tailored Resume`);
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
      const res = await fetch(`/api/jobs/${rowid}/applied`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast('🎉 BOOM! Job recorded as APPLIED! Keep up the momentum, Deepak!');
        triggerConfetti();
        fetchJobs();
      }
    }

    function previewPDF(pdfPath, title) {
      const cleanPath = pdfPath.replace(/^.*tailored_resumes[\\\\/]/, 'resumes/').replace(/^.*cover_letters[\\\\/]/, 'covers/');
      document.getElementById('modal-title').textContent = title;
      document.getElementById('pdf-frame').src = '/files/' + cleanPath;
      document.getElementById('pdf-modal').style.display = 'flex';
    }

    function closeModal() {
      document.getElementById('pdf-modal').style.display = 'none';
      document.getElementById('pdf-frame').src = '';
    }

    /* Referral & LinkedIn Modal */
    function openReferralModal(rowid) {
      const job = allJobs.find(j => j.rowid === rowid);
      if (!job) return;
      const o = job.outreach || {};
      const comp = job.company || 'Target Company';

      document.getElementById('referral-modal-title').innerHTML = `<i class="fa-brands fa-linkedin" style="color:#38bdf8;"></i> LinkedIn Connections & Outreach: <strong>${comp}</strong> (${job.title})`;

      const html = `
        <!-- Section 1: Active Connections & Network Filters -->
        <div style="background: rgba(30, 41, 59, 0.75); border: 1.5px solid rgba(56, 189, 248, 0.3); border-radius: 12px; padding: 18px; margin-bottom: 20px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <h4 style="margin: 0; color: #38bdf8; font-size: 15px;"><i class="fa-solid fa-filter"></i> 1. Targeted LinkedIn Network Filters (Opens in active Brave)</h4>
            <span style="font-size: 11px; background: rgba(56,189,248,0.15); color: #38bdf8; padding: 3px 8px; border-radius: 6px; font-weight: 700;">Deepak's Active Network</span>
          </div>
          <p style="margin: 0 0 14px 0; font-size: 13px; color: #94a3b8;">
            🎯 <em>Filters your live LinkedIn account for 1st-degree friends, 2nd-degree mutuals, and RVCE alumni currently working at ${comp}.</em>
          </p>
          <div style="display: flex; flex-wrap: wrap; gap: 10px;">
            <a href="${o.first_degree_url || '#'}" id="ref-first-deg-link" target="_blank" class="btn" style="background: linear-gradient(135deg, #059669, #10b981); color: white; text-decoration: none; padding: 9px 14px; font-weight: 700; box-shadow: 0 2px 8px rgba(16,185,129,0.3);">
              🟢 Find My 1st Degree Connections @ ${comp}
            </a>
            <a href="${o.second_degree_url || '#'}" target="_blank" class="btn" style="background: linear-gradient(135deg, #d97706, #f59e0b); color: white; text-decoration: none; padding: 9px 14px; font-weight: 700;">
              🟡 Find 2nd Degree (Mutual) Connections @ ${comp}
            </a>
            <a href="${o.alumni_search_url || '#'}" target="_blank" class="btn" style="background: #0284c7; color: white; text-decoration: none; padding: 9px 14px; font-weight: 700;">
              🎓 Find RVCE Alumni @ ${comp}
            </a>
            <a href="${o.recruiter_search_url || '#'}" target="_blank" class="btn" style="background: #7c3aed; color: white; text-decoration: none; padding: 9px 14px; font-weight: 700;">
              🎯 Find Tech Recruiters @ ${comp}
            </a>
            <a href="${o.lead_search_url || '#'}" target="_blank" class="btn" style="background: #334155; color: white; text-decoration: none; padding: 9px 14px;">
              ⚡ Engineering Managers
            </a>
            <a href="https://referral-community.kadegree.in/get" target="_blank" rel="noopener noreferrer" class="btn" style="background: linear-gradient(135deg, #b45309, #d97706); color: white; text-decoration: none; padding: 9px 14px; font-weight: 700;">
              🟡 KaDegree Community (${comp})
            </a>
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
          <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.08); display: flex; gap: 10px; align-items: center;">
            <input type="text" id="direct-conn-input" placeholder="Paste specific connection's LinkedIn profile URL or name..." style="flex:1; background: #0f172a; border: 1px solid #334155; color: #fff; padding: 8px 12px; border-radius: 8px; font-size: 12px;">
            <button class="btn" style="background:#0a66c2;color:white;" onclick="openDirectConnectionChat()"><i class="fa-solid fa-paper-plane"></i> Open Chat in Brave</button>
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
            <button class="btn" id="btn-modal-draft-${job.rowid}" style="background: linear-gradient(135deg, #dc2626, #b91c1c); color: white; font-weight: 700; padding: 8px 16px; white-space: nowrap;" onclick="draftEmailFromModal(${job.rowid})">
              <i class="fa-solid fa-paper-plane"></i> Create Gmail Draft (w/ Resume)
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
          container.innerHTML = data.connections.map(c => `
            <div style="background: #0f172a; border: 1px solid #334155; border-radius: 10px; padding: 12px; display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px;">
              <div>
                <div style="font-weight: 700; color: #f8fafc; font-size: 13.5px; display: flex; align-items: center; gap: 8px;">
                  <span>${c.name}</span>
                  <span style="background: #065f46; color: #34d399; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 700;">Alumni / Connection</span>
                </div>
                <div style="color: #94a3b8; font-size: 12px;">${c.headline}</div>
                <div style="color: #64748b; font-size: 11px;"><i class="fa-solid fa-location-dot"></i> ${c.location}</div>
              </div>
              <div style="display: flex; gap: 6px;">
                <button class="btn" style="background: #0a66c2; color: #fff; padding: 6px 10px; font-size: 11px;" onclick="openDirectUrl('${c.profile_url}')">
                  <i class="fa-brands fa-linkedin"></i> View & Chat
                </button>
                <button class="btn" style="background: #10b981; color: white; padding: 6px 10px; font-size: 11px;" onclick="copyCustomReferral('${c.name.replace(/'/g, "\'")}')">
                  <i class="fa-regular fa-copy"></i> Copy Note
                </button>
              </div>
            </div>
          `).join('');
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
    /* Gmail Recruiter Drafting System */
    async function draftEmailForJob(rowid, customEmail = null) {
      const btn = document.getElementById(`btn-draft-${rowid}`);
      if (btn) {
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Drafting in Gmail...';
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
            btn.innerHTML = '<i class="fa-solid fa-check"></i> Draft Created in Gmail!';
            btn.style.background = '#059669';
          }
          setTimeout(() => {
            if (confirm(`Draft created successfully in your Gmail!\n\nTo: ${data.to}\nSubject: ${data.subject}\n\nWould you like to open your Gmail Drafts now in Brave?`)) {
              window.open('https://mail.google.com/mail/u/0/#drafts', '_blank');
            }
          }, 300);
        } else if (data.status === 'missing_email') {
          promptCustomDraft(rowid);
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-envelope-circle-check"></i> Draft in Gmail';
            btn.disabled = false;
          }
        } else {
          showToast('⚠️ Error: ' + (data.message || 'Failed to draft email'));
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-envelope-circle-check"></i> Retry Draft';
            btn.disabled = false;
          }
        }
      } catch (e) {
        showToast('Failed to connect: ' + e);
        if (btn) {
          btn.innerHTML = '<i class="fa-solid fa-envelope-circle-check"></i> Draft in Gmail';
          btn.disabled = false;
        }
      }
    }

    function promptCustomDraft(rowid) {
      const job = allJobs.find(j => j.rowid === rowid);
      const email = prompt(`Enter recruiter or talent email address for ${job ? job.company : 'this role'}:`, job ? job.recruiter_email || '' : '');
      if (email && email.trim()) {
        draftEmailForJob(rowid, email.trim());
      }
    }

    async function draftEmailFromModal(rowid) {
      const input = document.getElementById(`modal-draft-email-${rowid}`);
      const statusEl = document.getElementById(`modal-draft-status-${rowid}`);
      const btn = document.getElementById(`btn-modal-draft-${rowid}`);
      const email = input ? input.value.trim() : '';
      if (!email || !email.includes('@')) {
        alert('Please enter a valid email address.');
        return;
      }
      if (btn) {
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generating Draft...';
        btn.disabled = true;
      }
      if (statusEl) {
        statusEl.style.display = 'block';
        statusEl.style.background = 'rgba(56, 189, 248, 0.2)';
        statusEl.style.color = '#38bdf8';
        statusEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Running Gmail CLI to compose draft and attach resume PDF...';
      }
      try {
        const res = await fetch(`/api/jobs/${rowid}/draft_email`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ custom_email: email })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-check"></i> Draft Ready in Gmail!';
            btn.style.background = '#059669';
          }
          if (statusEl) {
            statusEl.style.background = 'rgba(16, 185, 129, 0.25)';
            statusEl.style.color = '#34d399';
            statusEl.innerHTML = `<strong>✅ Draft created in Gmail!</strong><br>
              <span style="font-size:11px;color:#cbd5e1;">Recipient: ${data.to} | Attachment: ${data.attachment ? 'Resume PDF attached' : 'None'}</span><br>
              <a href="https://mail.google.com/mail/u/0/#drafts" target="_blank" rel="noopener noreferrer" style="color:#38bdf8;text-decoration:underline;display:inline-block;margin-top:6px;font-weight:700;">Open Gmail Drafts to Review & Send &rarr;</a>`;
          }
          showToast('✅ Draft created for ' + email);
        } else {
          if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Retry Draft';
            btn.disabled = false;
          }
          if (statusEl) {
            statusEl.style.background = 'rgba(239, 68, 68, 0.25)';
            statusEl.style.color = '#f87171';
            statusEl.innerHTML = '⚠️ Error: ' + (data.message || 'Draft creation failed.');
          }
        }
      } catch (err) {
        if (btn) {
          btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Retry Draft';
          btn.disabled = false;
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

    async function submitCustomDraft() {
      const email = document.getElementById('custom-draft-email').value.trim();
      const comp = document.getElementById('custom-draft-comp').value.trim();
      const role = document.getElementById('custom-draft-role').value.trim();
      const url = document.getElementById('custom-draft-url').value.trim();
      const statusEl = document.getElementById('custom-draft-status');
      const btn = document.getElementById('btn-submit-custom-draft');

      if (!email || !email.includes('@')) {
        alert('Please enter a valid recruiter email address.');
        return;
      }

      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Creating Draft...';
      btn.disabled = true;
      statusEl.style.display = 'block';
      statusEl.style.background = 'rgba(56, 189, 248, 0.2)';
      statusEl.style.color = '#38bdf8';
      statusEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Composing draft and attaching resume PDF...';

      try {
        const res = await fetch('/api/email/custom_draft', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ to_email: email, company: comp, role: role, job_url: url })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          btn.innerHTML = '<i class="fa-solid fa-check"></i> Draft Created in Gmail!';
          btn.style.background = '#059669';
          statusEl.style.background = 'rgba(16, 185, 129, 0.25)';
          statusEl.style.color = '#34d399';
          statusEl.innerHTML = `<strong>✅ Draft created in Gmail!</strong><br>
            <span style="font-size:11px;color:#cbd5e1;">Recipient: ${data.to} | Resume: Attached</span><br>
            <a href="https://mail.google.com/mail/u/0/#drafts" target="_blank" rel="noopener noreferrer" style="color:#38bdf8;text-decoration:underline;display:inline-block;margin-top:6px;font-weight:700;">Open Gmail Drafts to Review & Send &rarr;</a>`;
          showToast('✅ Cold email drafted for ' + email);
        } else {
          btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Retry Draft';
          btn.disabled = false;
          statusEl.style.background = 'rgba(239, 68, 68, 0.25)';
          statusEl.style.color = '#f87171';
          statusEl.innerHTML = '⚠️ Error: ' + (data.message || 'Failed to create draft');
        }
      } catch (err) {
        btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Retry Draft';
        btn.disabled = false;
        statusEl.style.background = 'rgba(239, 68, 68, 0.25)';
        statusEl.style.color = '#f87171';
        statusEl.innerHTML = '⚠️ Network Error: ' + err;
      }
    }

    function triggerConfetti() {
      const canvas = document.getElementById('confetti-canvas');
      const ctx = canvas.getContext('2d');
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;

      const particles = [];
      const colors = ['#6366f1', '#10b981', '#38bdf8', '#f59e0b', '#ec4899', '#a855f7'];

      for (let i = 0; i < 90; i++) {
        particles.push({
          x: canvas.width / 2,
          y: canvas.height * 0.4,
          r: Math.random() * 6 + 4,
          dx: (Math.random() - 0.5) * 16,
          dy: (Math.random() - 0.7) * 16,
          color: colors[Math.floor(Math.random() * colors.length)],
          tilt: Math.random() * 10,
          tiltAngle: 0,
          tiltAngleIncremental: (Math.random() * 0.07) + 0.05
        });
      }

      let animationFrames = 0;
      function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => {
          ctx.beginPath();
          ctx.lineWidth = p.r / 2;
          ctx.strokeStyle = p.color;
          ctx.moveTo(p.x + p.tilt + (p.r / 4), p.y);
          ctx.lineTo(p.x + p.tilt, p.y + p.tilt + (p.r / 4));
          ctx.stroke();

          p.x += p.dx;
          p.y += p.dy;
          p.dy += 0.35; // gravity
          p.tiltAngle += p.tiltAngleIncremental;
          p.tilt = Math.sin(p.tiltAngle) * 12;
        });

        animationFrames++;
        if (animationFrames < 85) {
          requestAnimationFrame(draw);
        } else {
          ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
      }
      draw();
    }

    // Initial load
    fetchJobs();
    setInterval(fetchJobs, 25000); // live sync every 25s
  </script>
</body>
</html>
"""


class DashboardHandler(SimpleHTTPRequestHandler):
    """Custom request handler for ApplyPilot Phase 2 Dashboard & Phase 3 Assistant."""

    def log_message(self, format, *args):
        # Silence default terminal request spam
        return

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

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
                    COALESCE(description, '') AS desc
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
            exp_pattern = re.compile(r'(\d+)\+?\s*(?:to\s*(\d+))?\s*(?:years?|yrs?)(?:\s*of)?\s*experience', re.IGNORECASE)

            jobs = []
            for j in all_raw:
                loc = (j.get("location") or "").lower()
                tit = (j.get("title") or "").lower()

                # 1. Location rejection (e.g. US-only, Canada, UK)
                if any(rp in loc for rp in reject_patterns):
                    continue

                # 2. Senior / Lead / Staff / Manager title rejection (Deepak has ~1.3 yrs experience)
                if any(st in tit for st in reject_titles):
                    continue

                # 3. Explicit 4+ years experience rejection
                text = f"{tit} {j.get('full_desc', '')} {j.get('desc', '')}"
                matches = exp_pattern.findall(text)
                if matches:
                    years = [int(m[0]) for m in matches if m[0].isdigit()]
                    if years and min(years) >= 4:
                        continue

                # Clean internal fields
                j.pop('full_desc', None)
                j.pop('desc', None)
                jobs.append(j)

            # Attach LinkedIn referral outreach data to each job
            for j in jobs:
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

        elif path.startswith("/files/"):
            # Stream PDF file
            subpath = path[len("/files/"):]
            if subpath.startswith("resumes/"):
                fname = subpath[len("resumes/"):]
                target = TAILORED_DIR / fname
            elif subpath.startswith("covers/"):
                fname = subpath[len("covers/"):]
                target = COVER_LETTER_DIR / fname
            else:
                target = APP_DIR / subpath

            if target.exists() and target.is_file():
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f"inline; filename={target.name}")
                self.end_headers()
                self.wfile.write(target.read_bytes())
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 1. /api/jobs/{rowid}/tailor (On-Demand JIT Tailoring)
        if path.startswith("/api/jobs/") and path.endswith("/tailor"):
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
            row = c.execute("SELECT application_url, url, tailored_resume_path FROM jobs WHERE rowid = ?", (rowid,)).fetchone()
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

        # 4. /api/jobs/{rowid}/applied
        elif path.startswith("/api/jobs/") and path.endswith("/applied"):
            parts = path.split("/")
            rowid = int(parts[3])
            from applypilot.apply.assistant import mark_job_applied
            res = mark_job_applied(rowid)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 5. /api/jobs/{rowid}/launch (Playwright Assistant)
        elif path.startswith("/api/jobs/") and path.endswith("/launch"):
            parts = path.split("/")
            rowid = int(parts[3])
            from applypilot.apply.assistant import launch_application_assistant

            t = threading.Thread(target=launch_application_assistant, args=(rowid, True), daemon=True)
            t.start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "rowid": rowid}).encode("utf-8"))
            return

        # 6. /api/open_url (Directly open URL in running Brave)
        elif path == "/api/open_url":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                target_url = data.get("url", "")
                if target_url:
                    launch_url_in_brave(target_url)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "url": target_url}).encode("utf-8"))
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
            res = draft_for_job(rowid, custom_recipient=custom_email or None)

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

                from applypilot.networking.gmail_drafter import generate_recruiter_email, create_gmail_draft
                from applypilot.config import load_profile
                email_content = generate_recruiter_email(
                    company=company,
                    role_title=role_str,
                    job_url=job_url,
                    candidate_profile=load_profile()
                )
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

        self.send_response(404)
        self.end_headers()


def start_dashboard_server(port: int = PORT, open_browser: bool = True):
    """Start the interactive dashboard server and open it in Chrome/default browser."""
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    url = f"http://127.0.0.1:{port}"
    print(f"\n🚀 ApplyPilot 2.0 Command Dashboard running at: {url}")
    print("   Press Ctrl+C to stop the dashboard server.\n")

    if open_browser:
        launch_url_in_brave(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
        server.shutdown()
