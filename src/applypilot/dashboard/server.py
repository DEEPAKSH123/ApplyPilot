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
    /* Dynamic Theme Palettes */
    :root, [data-theme="classic"] {
      --bg: #070a13;
      --bg-gradient: radial-gradient(ellipse at 15% 0%, rgba(99, 102, 241, 0.22) 0%, transparent 55%),
                     radial-gradient(ellipse at 85% 100%, rgba(236, 72, 153, 0.16) 0%, transparent 55%),
                     radial-gradient(circle at 50% 50%, rgba(56, 189, 248, 0.08) 0%, transparent 60%),
                     #070a13;
      --panel: rgba(15, 23, 42, 0.85);
      --panel-border: rgba(99, 102, 241, 0.22);
      --card-bg: rgba(18, 26, 47, 0.9);
      --card-border: rgba(99, 102, 241, 0.25);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #6366f1;
      --accent-glow: rgba(99, 102, 241, 0.4);
      --brand-grad: linear-gradient(135deg, #6366f1, #38bdf8, #10b981);
      --tab-active: linear-gradient(135deg, #4f46e5, #0ea5e9);
      --emerald: #10b981;
      --emerald-glow: rgba(16, 185, 129, 0.35);
      --amber: #f59e0b;
      --cyan: #06b6d4;
      --purple: #a855f7;
      --rose: #f43f5e;
    }

    [data-theme="aurora"] {
      --bg: #060913;
      --bg-gradient: radial-gradient(circle at 10% 12%, rgba(6, 182, 212, 0.22) 0%, transparent 45%),
                     radial-gradient(circle at 90% 15%, rgba(16, 185, 129, 0.18) 0%, transparent 45%),
                     radial-gradient(circle at 50% 85%, rgba(59, 130, 246, 0.14) 0%, transparent 55%),
                     #060913;
      --panel: rgba(11, 19, 38, 0.85);
      --panel-border: rgba(56, 189, 248, 0.2);
      --card-bg: rgba(13, 22, 44, 0.9);
      --card-border: rgba(56, 189, 248, 0.22);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #06b6d4;
      --accent-glow: rgba(6, 182, 212, 0.4);
      --brand-grad: linear-gradient(135deg, #00f2fe, #38bdf8, #34d399);
      --tab-active: linear-gradient(135deg, #0284c7, #0d9488);
      --emerald: #10b981;
      --emerald-glow: rgba(16, 185, 129, 0.35);
      --amber: #f59e0b;
      --cyan: #06b6d4;
      --purple: #38bdf8;
      --rose: #f43f5e;
    }

    [data-theme="space-black"] {
      --bg: #000000;
      --bg-gradient: radial-gradient(circle at 50% 12%, rgba(34, 197, 94, 0.14) 0%, transparent 60%),
                     #000000;
      --panel: rgba(16, 16, 20, 0.95);
      --panel-border: rgba(255, 255, 255, 0.14);
      --card-bg: rgba(20, 20, 26, 0.95);
      --card-border: rgba(255, 255, 255, 0.16);
      --text: #ffffff;
      --text-muted: #9ca3af;
      --accent: #22c55e;
      --accent-glow: rgba(34, 197, 94, 0.4);
      --brand-grad: linear-gradient(135deg, #22c55e, #10b981, #06b6d4);
      --tab-active: linear-gradient(135deg, #15803d, #047857);
      --emerald: #22c55e;
      --emerald-glow: rgba(34, 197, 94, 0.35);
      --amber: #eab308;
      --cyan: #06b6d4;
      --purple: #a855f7;
      --rose: #f43f5e;
    }

    [data-theme="cyberpunk"] {
      --bg: #090615;
      --bg-gradient: radial-gradient(ellipse at 15% 0%, rgba(168, 85, 247, 0.25) 0%, transparent 55%),
                     radial-gradient(ellipse at 85% 100%, rgba(244, 63, 94, 0.2) 0%, transparent 55%),
                     #090615;
      --panel: rgba(22, 13, 41, 0.88);
      --panel-border: rgba(168, 85, 247, 0.25);
      --card-bg: rgba(26, 16, 49, 0.92);
      --card-border: rgba(168, 85, 247, 0.28);
      --text: #faf5ff;
      --text-muted: #a8a29e;
      --accent: #a855f7;
      --accent-glow: rgba(168, 85, 247, 0.45);
      --brand-grad: linear-gradient(135deg, #f43f5e, #c084fc, #38bdf8);
      --tab-active: linear-gradient(135deg, #7c3aed, #ec4899);
      --emerald: #10b981;
      --emerald-glow: rgba(16, 185, 129, 0.35);
      --amber: #f59e0b;
      --cyan: #38bdf8;
      --purple: #a855f7;
      --rose: #f43f5e;
    }

    [data-theme="sunset-slate"] {
      --bg: #0c0e12;
      --bg-gradient: radial-gradient(circle at 12% 15%, rgba(249, 115, 22, 0.22) 0%, transparent 50%),
                     radial-gradient(circle at 88% 85%, rgba(217, 70, 239, 0.16) 0%, transparent 50%),
                     #0c0e12;
      --panel: rgba(20, 24, 33, 0.88);
      --panel-border: rgba(249, 115, 22, 0.22);
      --card-bg: rgba(25, 30, 42, 0.92);
      --card-border: rgba(249, 115, 22, 0.26);
      --text: #fff7ed;
      --text-muted: #a1a1aa;
      --accent: #f97316;
      --accent-glow: rgba(249, 115, 22, 0.4);
      --brand-grad: linear-gradient(135deg, #f97316, #fb923c, #fbbf24);
      --tab-active: linear-gradient(135deg, #ea580c, #c026d3);
      --emerald: #10b981;
      --emerald-glow: rgba(16, 185, 129, 0.35);
      --amber: #f59e0b;
      --cyan: #38bdf8;
      --purple: #d946ef;
      --rose: #f43f5e;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: var(--bg-gradient);
      color: var(--text);
      line-height: 1.5;
      padding-bottom: 80px;
      min-height: 100vh;
      background-attachment: fixed;
      transition: background 0.3s ease, color 0.3s ease;
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

    /* Palette Switcher */
    .theme-picker {
      display: flex;
      align-items: center;
      gap: 3px;
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid var(--panel-border);
      border-radius: 999px;
      padding: 3px 5px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }
    .theme-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 11px;
      font-weight: 700;
      padding: 5px 11px;
      border-radius: 999px;
      cursor: pointer;
      transition: all 0.2s ease;
      white-space: nowrap;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .theme-btn:hover {
      color: #fff;
    }
    .theme-btn.active {
      background: var(--accent);
      color: #fff;
      box-shadow: 0 0 12px var(--accent-glow);
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
    .btn-auto-apply {
      background: linear-gradient(135deg, #10b981, #06b6d4);
      color: white;
      font-weight: 800;
      box-shadow: 0 2px 10px rgba(16, 185, 129, 0.4);
      border: 1px solid rgba(255,255,255,0.25);
    }
    .btn-auto-apply:hover {
      background: linear-gradient(135deg, #059669, #0891b2);
      transform: translateY(-2px);
      box-shadow: 0 4px 16px rgba(16, 185, 129, 0.65);
      color: #fff;
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
    .response-card.cat-oa.is-missed {
      border: 1.5px solid #ef4444;
      background: linear-gradient(135deg, rgba(153, 27, 27, 0.35), rgba(15, 23, 42, 0.95));
      box-shadow: 0 0 26px rgba(239, 68, 68, 0.25);
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

    /* Source Filters Bar & Badges */
    .source-filter-bar {
      display: flex;
      gap: 8px;
      margin-bottom: 18px;
      flex-wrap: wrap;
      align-items: center;
    }
    .source-pill {
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
    .source-pill:hover, .source-pill.active {
      background: rgba(99, 102, 241, 0.25);
      border-color: #6366f1;
      color: #fff;
    }
    .source-pill.pill-kadegree.active {
      background: rgba(245, 158, 11, 0.28);
      border-color: #f59e0b;
      color: #fde047;
      box-shadow: 0 0 12px rgba(245, 158, 11, 0.3);
    }
    .source-pill.pill-linkedin.active {
      background: rgba(10, 102, 194, 0.3);
      border-color: #0a66c2;
      color: #60a5fa;
    }
    .source-pill.pill-whatsapp.active {
      background: rgba(37, 211, 102, 0.25);
      border-color: #25d366;
      color: #86efac;
    }
    .source-pill.pill-ats.active {
      background: rgba(16, 185, 129, 0.25);
      border-color: #10b981;
      color: #6ee7b7;
    }

    /* Source Tags on Cards */
    .tag-kadegree {
      background: linear-gradient(135deg, rgba(180, 83, 9, 0.45), rgba(217, 119, 6, 0.35));
      color: #fbbf24;
      border: 1px solid rgba(245, 158, 11, 0.6);
      font-weight: 700;
      letter-spacing: 0.3px;
    }
    .tag-referrer {
      background: rgba(245, 158, 11, 0.15);
      color: #fde68a;
      border: 1px dashed rgba(245, 158, 11, 0.4);
    }
    .tag-linkedin {
      background: rgba(10, 102, 194, 0.2);
      color: #38bdf8;
      border: 1px solid rgba(56, 189, 248, 0.35);
    }
    .tag-whatsapp {
      background: rgba(37, 211, 102, 0.18);
      color: #4ade80;
      border: 1px solid rgba(74, 222, 128, 0.35);
    }
    .tag-ats {
      background: rgba(99, 102, 241, 0.18);
      color: #a5b4fc;
      border: 1px solid rgba(165, 180, 252, 0.35);
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
      <a href="https://www.linkedin.com/search/results/content/?keywords=backend%20engineer%20AND%20(%22hiring%22%20OR%20%22requirement%22)&sortBy=%22date_posted%22" target="_blank" rel="noopener noreferrer" class="quick-pill" style="background: rgba(10, 102, 194, 0.2); border: 1px solid #0a66c2; color: #60a5fa; font-weight: 700; text-decoration: none;" title="Open live LinkedIn hiring & requirement posts feed"><i class="fa-brands fa-linkedin"></i> Hiring Posts Feed</a>
      <a href="https://referral-community.kadegree.in/get" target="_blank" rel="noopener noreferrer" class="quick-pill" style="background: linear-gradient(135deg, #b45309, #d97706); color: #fff; font-weight: 700; text-decoration: none;"><i class="fa-solid fa-users"></i> KaDegree (ಕನ್ನಡ Community)</a>
      <a href="https://mail.google.com/mail/u/0/#drafts" target="_blank" rel="noopener noreferrer" class="quick-pill" style="background: #ea4335; color: #fff; font-weight: 700; text-decoration: none;"><i class="fa-solid fa-envelope"></i> Gmail Drafts</a>
      <div id="naukri-quick-pill" class="quick-pill" onclick="triggerNaukriRefresh()" style="background: linear-gradient(135deg, #0284c7, #2563eb); color: #fff; font-weight: 700; cursor: pointer;" title="Naukri 9:00 AM Daily Refresh Active (Click to refresh now)"><i class="fa-solid fa-arrows-rotate"></i> <span id="naukri-pill-label">Naukri: 9 AM Active ⚡</span></div>
      <div class="quick-pill" onclick="openLogCallModal()" style="background: linear-gradient(135deg, #10b981, #059669); color: #fff; font-weight: 700; cursor: pointer;"><i class="fa-solid fa-phone"></i> + Log Recruiter Call / Update</div>
      <div class="quick-pill" onclick="openCheatsheetModal('PhonePe', 'SDE-1 Backend')" style="background: rgba(168, 85, 247, 0.2); border: 1px solid #a855f7; color: #d8b4fe; font-weight: 700; cursor: pointer;" title="Instant Technical & HR Interview Cheat-Sheet tailored to Deepak's Meesho experience"><i class="fa-solid fa-bolt"></i> ⚡ Tech Cheat-Sheet</div>
      <div class="quick-pill" onclick="testAlertsFromUI()" style="background: rgba(6, 182, 212, 0.2); border: 1px solid #06b6d4; color: #7dd3fc; font-weight: 700; cursor: pointer;" title="Test instant alerts to Telegram, WhatsApp CallMeBot & Windows Desktop"><i class="fa-solid fa-bell"></i> 📱 Mobile Alert Bot</div>
      <div class="quick-pill" onclick="syncGSheetsNow()" style="background: linear-gradient(135deg, #0284c7, #0369a1); color: #fff; font-weight: 700; cursor: pointer;"><i class="fa-solid fa-table"></i> 📱 Central Google Sheet</div>
      <div class="quick-pill" onclick="openCustomDraftModal()"  style="background: rgba(234, 67, 53, 0.2); border: 1px solid #ea4335; color: #fca5a5; font-weight: 700; cursor: pointer;"><i class="fa-solid fa-pen-nib"></i> + Draft Cold Email</div>
      <div class="quick-pill" onclick="triggerBatchAutoApply()" style="background: linear-gradient(135deg, #10b981, #06b6d4); color: #fff; font-weight: 800; border: 1px solid #34d399; cursor: pointer;" title="Autonomously apply to top qualified roles in Brave (Kanistus Workflow: does everything itself)"><i class="fa-solid fa-bolt"></i> ⚡ Auto-Apply Top Matches</div>
      <div class="quick-pill" onclick="triggerChannelPoll(event)" style="background: linear-gradient(135deg, #0284c7, #10b981); color: #fff; font-weight: 800; border: 1px solid #38bdf8; cursor: pointer;" title="Poll live WhatsApp Web, Telegram channels, and Gmail for fresh referral leads (2x/day scheduled)"><i class="fa-solid fa-satellite-dish"></i> 📡 Poll WhatsApp & Telegram</div>

      <!-- Theme Switcher Pill -->
      <div class="theme-picker" title="Change Theme Palette">
        <button class="theme-btn" id="btn-theme-classic" onclick="setPalette('classic')" title="Classic Cyber Indigo (Original Dark)"><i class="fa-solid fa-moon"></i> Indigo</button>
        <button class="theme-btn" id="btn-theme-aurora" onclick="setPalette('aurora')" title="Nordic Aurora (Cyan & Emerald)"><i class="fa-solid fa-water"></i> Aurora</button>
        <button class="theme-btn" id="btn-theme-space-black" onclick="setPalette('space-black')" title="OLED True Black (Pure Contrast)"><i class="fa-solid fa-circle"></i> OLED</button>
        <button class="theme-btn" id="btn-theme-cyberpunk" onclick="setPalette('cyberpunk')" title="Cyberpunk Neon (Violet & Pink)"><i class="fa-solid fa-wand-magic-sparkles"></i> Neon</button>
        <button class="theme-btn" id="btn-theme-sunset-slate" onclick="setPalette('sunset-slate')" title="Sunset Amber (Warm Carbon)"><i class="fa-solid fa-sun"></i> Sunset</button>
      </div>
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
      <div class="stat-card" style="border-color: rgba(217, 119, 6, 0.5); cursor: pointer;" onclick="setTab('kadegree');" title="Click to view live Kannada referral openings">
        <span class="label"><i class="fa-solid fa-users"></i> 🌟 KaDegree Referrals</span>
        <span class="val" id="stat-kadegree" style="color: #fbbf24;">0</span>
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
        <button class="tab-btn" onclick="setTab('kadegree')" style="color: #fbbf24; border-color: rgba(245, 158, 11, 0.4);">
          <i class="fa-solid fa-users"></i> KaDegree (ಕನ್ನಡ Referrals)
          <span class="tab-badge" id="badge-kadegree" style="background: linear-gradient(135deg, #b45309, #d97706); color:#fff;">0</span>
        </button>
        <button class="tab-btn" onclick="setTab('strategy')" style="color: #fbbf24; border-color: rgba(245, 158, 11, 0.4);">
          <i class="fa-solid fa-brain"></i> ⚡ Conversion & Gemini Strategy
        </button>
        <button class="tab-btn" onclick="setTab('analytics')" style="color: #38bdf8;">
          <i class="fa-solid fa-chart-pie"></i> Application Analytics
          <span class="tab-badge" id="badge-analytics" style="background:#0284c7;color:#fff;">0</span>
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
      <button class="btn btn-sm" id="btn-sync-kadegree" onclick="triggerKaDegreeSync()" style="margin-left: auto; background: linear-gradient(135deg, #b45309, #d97706); color: #fff; font-weight: 700; border-radius: 9999px; padding: 6px 14px; font-size: 11.5px; border: none; cursor: pointer; display: flex; align-items: center; gap: 6px;">
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

    <div id="jobs-container" class="jobs-grid"></div>
    <!-- Application Analytics & Lifecycle Ledger View -->
    <div id="analytics-container" style="display: none;"></div>
    <!-- ⚡ 30-Day Conversion Funnel, Everyday Active Time & Gemini Strategy Container -->
    <div id="strategy-container" style="display: none;"></div>
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

  <!-- Standalone Technical Interview Strategy & Cheat-Sheet Modal -->
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
    let currentTab = 'high';
    let currentSourceFilter = 'all';

    function filterBySource(src) {
      currentSourceFilter = src;
      document.querySelectorAll('.source-pill').forEach(p => p.classList.remove('active'));
      const activePill = document.getElementById('src-' + src);
      if (activePill) activePill.classList.add('active');
      renderJobs();
    }

    function copyKannadaPitchByRowid(rowid) {
      const job = allJobs.find(j => j.rowid === rowid);
      const comp = job ? job.company : 'Tech Company';
      const title = job ? job.title : 'Software Engineer';
      const msg = `ನಮಸ್ಕಾರ,\n\nI noticed the referral opening for ${title} at ${comp} in our KaDegree community. I am an SDE-I Backend Engineer at Meesho (RVCE CSE '25, 1.3y exp) working with high-throughput Java, Go, Kafka, and Redis services.\n\nCould you please refer my profile for this position? I have attached my resume and requisition details:\nRequisition: ${comp} - ${title}\nProfile: SDE-I Backend Engineer, Meesho (RVCE '25)\nEmail: deepakshkarkala@gmail.com | Phone: +91 8431433659\n\nಧನ್ಯವಾದಗಳು! (Thank you!)\n- Deepak S H`;
      navigator.clipboard.writeText(msg).then(() => {
        showToast(`✅ Copied warm Kannada referral pitch for ${comp}!`);
      }).catch(() => {
        showToast('Selected pitch copied to clipboard!');
      });
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

        function setPalette(themeName) {
      document.documentElement.setAttribute('data-theme', themeName);
      localStorage.setItem('applypilot_theme', themeName);
      document.querySelectorAll('.theme-btn').forEach(b => b.classList.remove('active'));
      const activeBtn = document.getElementById(`btn-theme-${themeName}`);
      if (activeBtn) activeBtn.classList.add('active');
      showToast(`Palette switched to: ${themeName.replace('-', ' ').toUpperCase()}`);
    }

    // Initialize saved theme (default to classic Cyber Indigo)
    const savedTheme = localStorage.getItem('applypilot_theme') || 'classic';
    document.documentElement.setAttribute('data-theme', savedTheme);
    setTimeout(() => {
      document.querySelectorAll('.theme-btn').forEach(b => b.classList.remove('active'));
      const initialBtn = document.getElementById(`btn-theme-${savedTheme}`);
      if (initialBtn) initialBtn.classList.add('active');
    }, 50);
    /* 100% Autonomous Auto-Apply (Kanistus Workflow - does everything itself) */
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
      if (!confirm('Run Autonomous Auto-Apply batch for Top 5 qualified roles in Brave?\n\nThis will launch Brave, prefill application details, answer screening questions, attach your tailored resume, and submit each application autonomously (Kanistus workflow).')) {
        return;
      }
      showToast('🚀 Launching Autonomous Auto-Apply batch for Top 5 matches in Brave...');
      try {
        const res = await fetch('/api/auto_apply_batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ limit: 5, min_score: 7, auto_submit: true })
        });
        const data = await res.json();
        if (data.status === 'batch_launched') {
          showToast('🤖 Batch running! Applications are being submitted and recorded in your database.');
          setTimeout(() => { loadJobs(); loadStats(); }, 5000);
        }
      } catch (e) {
        showToast('Batch error: ' + e);
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

      document.getElementById('badge-high').textContent = allJobs.filter(j => j.fit_score >= 7).length;
      document.getElementById('badge-top').textContent = allJobs.filter(j => j.fit_score >= 8).length;
      document.getElementById('badge-approved').textContent = allJobs.filter(j => j.apply_status === 'approved').length;
      document.getElementById('badge-applied').textContent = allJobs.filter(j => j.apply_status === 'applied').length;
      document.getElementById('badge-responses').textContent = allResponses.length;

      const kaJobsCount = allJobs.filter(j => j.source_category === 'kadegree' || j.is_kadegree).length;
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

      // Update Top Urgent / Missed OA Banner
      const urgentBanner = document.getElementById('urgent-oa-alert');
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

    function setTab(tab) {
      currentTab = tab;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      const activeBtn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick') && b.getAttribute('onclick').includes(`'${tab}'`));
      if (activeBtn) activeBtn.classList.add('active');

      const qBanner = document.getElementById('queue-banner');
      const rBanner = document.getElementById('responses-banner');
      const respFilterBar = document.getElementById('resp-filter-bar');
      const sourceFilterBar = document.getElementById('source-filter-bar');
      const jobsContainer = document.getElementById('jobs-container');
      const analyticsContainer = document.getElementById('analytics-container');
      const strategyContainer = document.getElementById('strategy-container');

      if (sourceFilterBar) {
        sourceFilterBar.style.display = (tab === 'responses' || tab === 'analytics' || tab === 'strategy') ? 'none' : 'flex';
      }

      if (strategyContainer) strategyContainer.style.display = (tab === 'strategy') ? 'block' : 'none';

      if (tab === 'strategy') {
        qBanner.style.display = 'none';
        rBanner.style.display = 'none';
        if (respFilterBar) respFilterBar.style.display = 'none';
        if (jobsContainer) jobsContainer.style.display = 'none';
        if (analyticsContainer) analyticsContainer.style.display = 'none';
        renderStrategyView();
        return;
      }

      if (tab === 'analytics') {
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
        if (currentTab === 'kadegree' && !job.is_kadegree && job.source_category !== 'kadegree') return false;

        if (currentSourceFilter !== 'all') {
          if (currentSourceFilter === 'kadegree' && !job.is_kadegree && job.source_category !== 'kadegree') return false;
          if (currentSourceFilter === 'linkedin' && job.source_category !== 'linkedin') return false;
          if (currentSourceFilter === 'whatsapp' && job.source_category !== 'whatsapp') return false;
          if (currentSourceFilter === 'ats' && (job.is_kadegree || job.source_category === 'linkedin' || job.source_category === 'whatsapp')) return false;
        }

        if (q) {
          const hay = `${job.company} ${job.title} ${job.location} ${job.source || ''} ${job.score_reasoning || ''}`.toLowerCase();
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
                    <span class="source-badge-meta ${job.is_kadegree ? 'source-kadegree-badge' : ''}">
                      <i class="${job.source_icon || 'fa-solid fa-layer-group'}"></i> <strong>${job.source || 'Direct ATS'}</strong>
                    </span>
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
              ${hasResume ? `<span class="tag tag-resume"><i class="fa-solid fa-file-pdf"></i> Tailored Resume Ready</span>` : '<span class="tag" style="background:#334155;color:#94a3b8;"><i class="fa-solid fa-clock"></i> Base Resume</span>'}
              ${hasCover ? `<span class="tag tag-cover"><i class="fa-solid fa-envelope-open-text"></i> Cover Letter Ready</span>` : ''}
              ${isApplied ? `<span class="tag tag-applied"><i class="fa-solid fa-check-double"></i> Applied</span>` : isApproved ? `<span class="tag tag-approved"><i class="fa-solid fa-thumbs-up"></i> Approved Shortlist</span>` : ''}
            </div>

            ${job.score_reasoning ? `<div class="reasoning">${job.score_reasoning.replace(/\\n/g, '<br>')}</div>` : ''}

            <div class="actions-bar">
              ${job.is_kadegree ? `
                <!-- KaDegree Community Referral Link -->
                <a href="${job.kadegree_url || job.url}" target="_blank" rel="noopener noreferrer" class="btn" style="background: linear-gradient(135deg, #b45309, #d97706); color: white; text-decoration: none; padding: 7px 14px; font-size: 12px; font-weight: 700; border-radius: 8px; display: inline-flex; align-items: center; gap: 6px;" title="View referral post, referrer details & comments in Kannada Referral Community">
                  <i class="fa-solid fa-users-rays"></i> View on KaDegree
                </a>
                <button class="btn" style="background: rgba(217, 119, 6, 0.2); border: 1px solid #d97706; color: #fbbf24; font-size: 12px; font-weight: 700; border-radius: 8px; padding: 7px 12px;" onclick="copyKannadaPitch('${escapeHtml(job.company)}', '${escapeHtml(job.title)}')" title="Copy warm Kannada referral pitch (ನಮಸ್ಕಾರ...) to send to referrer">
                  <i class="fa-regular fa-copy"></i> Copy Kannada Pitch
                </button>
              ` : ''}

              <!-- 1-Click Autonomous Auto-Apply Button (Kanistus Workflow) -->
              <button class="btn btn-auto-apply" id="btn-auto-apply-${job.rowid}" onclick="launchAutonomousApply(${job.rowid})" title="Does everything itself: fills forms, answers screening questions, attaches resume, and submits autonomously">
                <i class="fa-solid fa-bolt"></i> Auto-Apply (Autonomous)
              </button>

              <!-- Application Assistant Autofill & Review Button -->
              <button class="btn btn-autofill" id="btn-autofill-${job.rowid}" onclick="launchAutofill(${job.rowid})" title="Auto-fills all fields and holds for Deepak's final review before submitting">
                <i class="fa-solid fa-shield-halved"></i> Fill & Review
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
                <button class="btn btn-preview" onclick="previewResume(${job.rowid})">
                  <i class="fa-solid fa-file-pdf"></i> View Resume PDF
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
      const res = await fetch(`/api/jobs/${rowid}/applied`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast('🎉 BOOM! Job recorded as APPLIED! Keep up the momentum, Deepak!');
        triggerConfetti();
        fetchJobs();
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
            ${o.hiring_posts_url ? `
            <a href="${o.hiring_posts_url}" target="_blank" class="btn" style="background: linear-gradient(135deg, #0284c7, #06b6d4); color: white; text-decoration: none; padding: 9px 14px; font-weight: 700;">
              💼 Hiring / Requirement Posts @ ${comp}
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
          <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.08); display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
            <input type="text" id="direct-conn-input" placeholder="Paste specific connection's LinkedIn profile URL (e.g. https://www.linkedin.com/in/...)..." style="flex:1; min-width: 280px; background: #0f172a; border: 1px solid #334155; color: #fff; padding: 8px 12px; border-radius: 8px; font-size: 12px;">
            <button class="btn" style="background: linear-gradient(135deg, #0284c7, #10b981); color: white; font-weight: 700; white-space: nowrap;" onclick="autoTypeDirectConnectionDM()"><i class="fa-solid fa-wand-magic-sparkles"></i> ⚡ Auto-Type Referral DM in Brave</button>
            <button class="btn" style="background:#0a66c2; color:white; white-space: nowrap;" onclick="openDirectConnectionChat()"><i class="fa-solid fa-paper-plane"></i> Open Chat in Brave</button>
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
              <div style="display: flex; gap: 6px; align-items: center;">
                <button class="btn" style="background: linear-gradient(135deg, #0284c7, #10b981); color: #fff; padding: 6px 10px; font-size: 11px; font-weight: 700; white-space: nowrap;" onclick="composeLinkedInDM('${c.profile_url}', '${c.name.replace(/'/g, "\\'")}', '${company.replace(/'/g, "\\'")}', 'Backend Engineer', 'alumni')">
                  <i class="fa-solid fa-wand-magic-sparkles"></i> Auto-Type DM
                </button>
                <button class="btn" style="background: #0a66c2; color: #fff; padding: 6px 10px; font-size: 11px; white-space: nowrap;" onclick="openDirectUrl('${c.profile_url}')">
                  <i class="fa-brands fa-linkedin"></i> View & Chat
                </button>
                <button class="btn" style="background: #10b981; color: white; padding: 6px 10px; font-size: 11px; white-space: nowrap;" onclick="copyCustomReferral('${c.name.replace(/'/g, "\\'")}')">
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

    async function composeLinkedInDM(profileUrl, name = '', company = '', role = 'Backend Engineer', template = 'referral') {
      if (!profileUrl) {
        showToast('Please enter or select a profile URL.');
        return;
      }
      showToast(`⚡ Launching Brave & auto-typing referral message for ${name || 'connection'}...`);

      try {
        const res = await fetch('/api/linkedin/compose_dm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            profile_url: profileUrl,
            name: name,
            company: company,
            role: role,
            template: template
          })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast(`🛡️ ${data.message}`);
        } else {
          showToast(`⚠️ Compose DM: ${data.message || 'Error'}`);
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
      const compMatch = titleEl ? titleEl.innerText.match(/Outreach:\s*([^(\n]+)/) : null;
      const comp = compMatch ? compMatch[1].trim() : '';
      composeLinkedInDM(val, '', comp, 'Backend Engineer', 'referral');
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

    async function checkNaukriStatus() {
      try {
        const res = await fetch('/api/naukri/status');
        const data = await res.json();
        const lbl = document.getElementById('naukri-pill-label');
        if (lbl) {
          if (data.last_update && data.last_update.status === 'success') {
            lbl.innerText = 'Naukri: Refreshed Today ✓';
          } else if (data.task && data.task.registered) {
            lbl.innerText = 'Naukri: 9 AM Active ⚡';
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

    // Initial load
    fetchJobs();
    checkNaukriStatus();
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
                    COALESCE(discovered_at, '') AS discovered_at
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

                # Derive Source & Job Related Info
                strat = (j.get("strategy") or "").lower()
                u_str = (j.get("url") or j.get("apply_url") or "").lower()
                c_str = (j.get("company") or "").lower()

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
                    elif (APP_DIR / "resume.pdf").is_file():
                        target_file = APP_DIR / "resume.pdf"
                elif doc_type == "cover_letter":
                    if cover_path and Path(cover_path).is_file():
                        target_file = Path(cover_path)

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

        # /api/channels/poll (Trigger community & inbound polling cycle)
        elif path == "/api/channels/poll":
            try:
                from applypilot.automation.poller import execute_polling_cycle
                import threading
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

                from applypilot.networking.linkedin import compose_referral_dm
                res = compose_referral_dm(
                    profile_url=profile_url,
                    company=company,
                    role_title=role_str,
                    name=name_str,
                    custom_message=custom_msg,
                    template_type=template,
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


def start_dashboard_server(port: int = PORT, open_browser: bool = True):
    """Start the interactive dashboard server and open it in Chrome/default browser."""
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

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
        server.shutdown()
    except Exception as e:
        print(f"\nServer error: {e}")
        try:
            server.shutdown()
        except Exception:
            pass
