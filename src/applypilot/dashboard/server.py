"""ApplyPilot Phase 2 Interactive Review & Approval Dashboard.

Built on Python's built-in ThreadingHTTPServer (zero new pip dependencies).
Provides:
- High-fit job cards with fit scores, ATS keywords, and match reasoning.
- Side-by-side or modal preview of Tailored Resume & Cover Letter PDFs.
- 1-Click approval queue and direct Phase 3 application launcher.
"""

import json
import logging
import mimetypes
import os
import sqlite3
import threading
import urllib.parse
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from applypilot.config import APP_DIR, DB_PATH, TAILORED_DIR, COVER_LETTER_DIR, load_profile
from applypilot.database import get_connection
from applypilot.export.csv_export import export_opportunities_csv

log = logging.getLogger(__name__)

PORT = 8765

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ApplyPilot - Review & Approval Dashboard</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #6366f1;
      --accent-hover: #4f46e5;
      --emerald: #10b981;
      --amber: #f59e0b;
      --cyan: #06b6d4;
      --rose: #f43f5e;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding-bottom: 60px;
    }
    header {
      background: #1e1b4b;
      border-bottom: 1px solid #3730a3;
      padding: 16px 32px;
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
      gap: 12px;
    }
    .brand h1 { font-size: 20px; font-weight: 700; color: #fff; letter-spacing: -0.5px; }
    .brand .badge {
      background: #4338ca;
      color: #c7d2fe;
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 999px;
      font-weight: 600;
    }
    .profile-pill {
      background: rgba(255,255,255,0.08);
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 13px;
      display: flex;
      align-items: center;
      gap: 8px;
      border: 1px solid rgba(255,255,255,0.1);
    }
    .container {
      max-width: 1400px;
      margin: 0 auto;
      padding: 24px 32px;
    }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .stat-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      padding: 16px;
      border-radius: 10px;
      display: flex;
      flex-direction: column;
    }
    .stat-card .label { font-size: 12px; color: var(--text-muted); text-transform: uppercase; font-weight: 600; }
    .stat-card .val { font-size: 28px; font-weight: 700; margin-top: 4px; }
    .controls {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }
    .tabs {
      display: flex;
      gap: 8px;
      background: var(--card-bg);
      padding: 4px;
      border-radius: 8px;
      border: 1px solid var(--card-border);
    }
    .tab-btn {
      background: transparent;
      color: var(--text-muted);
      border: none;
      padding: 8px 16px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s;
    }
    .tab-btn.active {
      background: var(--accent);
      color: white;
    }
    .search-box {
      flex: 1;
      max-width: 380px;
      position: relative;
    }
    .search-box input {
      width: 100%;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      padding: 9px 14px 9px 36px;
      border-radius: 8px;
      color: white;
      font-size: 14px;
      outline: none;
    }
    .search-box i {
      position: absolute;
      left: 12px;
      top: 12px;
      color: var(--text-muted);
    }
    .jobs-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(440px, 1fr));
      gap: 18px;
    }
    .job-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      position: relative;
      transition: transform 0.15s, border-color 0.15s;
    }
    .job-card:hover {
      border-color: #6366f1;
      transform: translateY(-2px);
    }
    .job-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 12px;
    }
    .job-company {
      font-size: 13px;
      font-weight: 600;
      color: var(--cyan);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .job-title {
      font-size: 17px;
      font-weight: 700;
      color: #fff;
      margin-top: 2px;
    }
    .job-loc {
      font-size: 13px;
      color: var(--text-muted);
      margin-top: 4px;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .score-badge {
      font-size: 13px;
      font-weight: 800;
      padding: 6px 12px;
      border-radius: 8px;
      display: flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
    }
    .score-9, .score-10 { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #059669; }
    .score-8 { background: rgba(99, 102, 241, 0.2); color: #a5b4fc; border: 1px solid #4f46e5; }
    .score-7 { background: rgba(6, 182, 212, 0.2); color: #67e8f9; border: 1px solid #0891b2; }
    .score-low { background: rgba(148, 163, 184, 0.15); color: #cbd5e1; border: 1px solid #475569; }
    .reasoning {
      background: rgba(0, 0, 0, 0.2);
      padding: 12px;
      border-radius: 8px;
      font-size: 12.5px;
      color: #cbd5e1;
      margin: 12px 0;
      border-left: 3px solid var(--accent);
      max-height: 100px;
      overflow-y: auto;
    }
    .badges-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 16px;
    }
    .artifact-tag {
      font-size: 11px;
      padding: 3px 8px;
      border-radius: 4px;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .tag-resume { background: #064e3b; color: #a7f3d0; }
    .tag-cover { background: #1e3a8a; color: #bfdbfe; }
    .tag-status { background: #374151; color: #f3f4f6; }
    .tag-applied { background: #065f46; color: #34d399; font-weight: 700; }
    .tag-approved { background: #4c1d95; color: #c4b5fd; font-weight: 700; }
    .actions-bar {
      display: flex;
      gap: 8px;
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid var(--card-border);
      flex-wrap: wrap;
    }
    .btn {
      padding: 7px 13px;
      border-radius: 6px;
      font-size: 12.5px;
      font-weight: 600;
      cursor: pointer;
      border: none;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      text-decoration: none;
      transition: all 0.15s;
    }
    .btn-apply { background: #10b981; color: white; }
    .btn-apply:hover { background: #059669; }
    .btn-approve { background: var(--accent); color: white; }
    .btn-approve:hover { background: var(--accent-hover); }
    .btn-preview { background: #334155; color: #e2e8f0; }
    .btn-preview:hover { background: #475569; }
    .btn-link { background: #1e293b; color: #94a3b8; border: 1px solid var(--card-border); }
    .btn-link:hover { color: white; border-color: #64748b; }
    .btn-done { background: #047857; color: white; }

    /* Modal for PDF Preview */
    .modal-backdrop {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.75);
      backdrop-filter: blur(4px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 1000;
      padding: 20px;
    }
    .modal-content {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      width: 100%;
      max-width: 960px;
      height: 90vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5);
    }
    .modal-header {
      padding: 14px 20px;
      border-bottom: 1px solid var(--card-border);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .modal-header h3 { font-size: 16px; font-weight: 600; }
    .modal-close {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 18px;
      cursor: pointer;
    }
    .modal-close:hover { color: white; }
    .modal-body {
      flex: 1;
      background: #525659;
    }
    .modal-body iframe {
      width: 100%;
      height: 100%;
      border: none;
    }
    .toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #1e1b4b;
      color: #e0e7ff;
      border: 1px solid #6366f1;
      padding: 12px 20px;
      border-radius: 8px;
      font-size: 13px;
      display: none;
      z-index: 2000;
      box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
    }
  </style>
</head>
<body>

  <header>
    <div class="brand">
      <i class="fa-solid fa-plane-departure" style="color: #818cf8; font-size: 20px;"></i>
      <h1>ApplyPilot Review Dashboard</h1>
      <span class="badge">Phase 2 & 3 Active</span>
    </div>
    <div class="profile-pill">
      <i class="fa-solid fa-user-check" style="color: #34d399;"></i>
      <span><strong>Deepak S H</strong> (SDE-I Backend @ Meesho | RVCE CSE 8.92)</span>
    </div>
  </header>

  <div class="container">
    <div class="stats-grid">
      <div class="stat-card">
        <span class="label">Total Scraped</span>
        <span class="val" id="stat-total">0</span>
      </div>
      <div class="stat-card">
        <span class="label">High-Fit Matches (&ge; 7)</span>
        <span class="val" id="stat-high" style="color: #34d399;">0</span>
      </div>
      <div class="stat-card">
        <span class="label">Tailored Resumes Ready</span>
        <span class="val" id="stat-tailored" style="color: #818cf8;">0</span>
      </div>
      <div class="stat-card">
        <span class="label">Cover Letters Ready</span>
        <span class="val" id="stat-cover" style="color: #38bdf8;">0</span>
      </div>
      <div class="stat-card">
        <span class="label">Applied Count</span>
        <span class="val" id="stat-applied" style="color: #fbbf24;">0</span>
      </div>
    </div>

    <div class="controls">
      <div class="tabs">
        <button class="tab-btn active" onclick="setTab('high')">High Fit (&ge; 7/10)</button>
        <button class="tab-btn" onclick="setTab('top')">Top Matches (&ge; 8/10)</button>
        <button class="tab-btn" onclick="setTab('approved')">Approved Queue</button>
        <button class="tab-btn" onclick="setTab('applied')">Applied</button>
        <button class="tab-btn" onclick="setTab('all')">All Opportunities</button>
      </div>
      <div class="search-box">
        <i class="fa-solid fa-magnifying-glass"></i>
        <input type="text" id="search-input" placeholder="Search by company, role, stack..." oninput="renderJobs()">
      </div>
    </div>

    <div id="jobs-container" class="jobs-grid">
      <!-- Injected via JavaScript -->
    </div>
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

  <div id="toast" class="toast"></div>

  <script>
    let allJobs = [];
    let currentTab = 'high';

    async function fetchJobs() {
      try {
        const res = await fetch('/api/jobs');
        allJobs = await res.json();
        updateStats();
        renderJobs();
      } catch (e) {
        showToast('Error loading jobs: ' + e);
      }
    }

    function updateStats() {
      document.getElementById('stat-total').textContent = allJobs.length;
      document.getElementById('stat-high').textContent = allJobs.filter(j => j.fit_score >= 7).length;
      document.getElementById('stat-tailored').textContent = allJobs.filter(j => !!j.tailored_resume_path).length;
      document.getElementById('stat-cover').textContent = allJobs.filter(j => !!j.cover_letter_path).length;
      document.getElementById('stat-applied').textContent = allJobs.filter(j => j.apply_status === 'applied').length;
    }

    function setTab(tab) {
      currentTab = tab;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      event.target.classList.add('active');
      renderJobs();
    }

    function renderJobs() {
      const q = document.getElementById('search-input').value.toLowerCase().trim();
      let filtered = allJobs.filter(job => {
        // Tab filter
        if (currentTab === 'high' && !(job.fit_score >= 7)) return false;
        if (currentTab === 'top' && !(job.fit_score >= 8)) return false;
        if (currentTab === 'approved' && job.apply_status !== 'approved') return false;
        if (currentTab === 'applied' && job.apply_status !== 'applied') return false;

        // Search text
        if (q) {
          const matchStr = (job.company + ' ' + job.title + ' ' + job.location + ' ' + (job.score_reasoning || '')).toLowerCase();
          if (!matchStr.includes(q)) return false;
        }
        return true;
      });

      const container = document.getElementById('jobs-container');
      if (filtered.length === 0) {
        container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 48px; color: var(--text-muted);">No jobs match the current filter.</div>`;
        return;
      }

      container.innerHTML = filtered.map(job => {
        const scoreClass = job.fit_score >= 9 ? 'score-9' : job.fit_score === 8 ? 'score-8' : job.fit_score === 7 ? 'score-7' : 'score-low';
        const hasResume = !!job.tailored_resume_path;
        const hasCover = !!job.cover_letter_path;
        const isApplied = job.apply_status === 'applied';
        const isApproved = job.apply_status === 'approved';

        return `
          <div class="job-card">
            <div>
              <div class="job-header">
                <div>
                  <div class="job-company">${job.company}</div>
                  <div class="job-title">${job.title}</div>
                  <div class="job-loc"><i class="fa-solid fa-location-dot"></i> ${job.location || 'India'}</div>
                </div>
                <div class="score-badge ${scoreClass}">
                  <i class="fa-solid fa-star"></i> ${job.fit_score || 0}/10
                </div>
              </div>

              <div class="badges-row">
                ${hasResume ? `<span class="artifact-tag tag-resume"><i class="fa-solid fa-file-pdf"></i> Tailored Resume</span>` : ''}
                ${hasCover ? `<span class="artifact-tag tag-cover"><i class="fa-solid fa-envelope-open-text"></i> Cover Letter</span>` : ''}
                ${isApplied ? `<span class="artifact-tag tag-applied"><i class="fa-solid fa-check-double"></i> Applied</span>` : isApproved ? `<span class="artifact-tag tag-approved"><i class="fa-solid fa-thumbs-up"></i> Approved</span>` : ''}
              </div>

              ${job.score_reasoning ? `<div class="reasoning">${job.score_reasoning.replace(/\\n/g, '<br>')}</div>` : ''}
            </div>

            <div class="actions-bar">
              ${hasResume ? `<button class="btn btn-preview" onclick="previewPDF('${job.tailored_resume_path}', '${job.company} - ${job.title} Resume')"><i class="fa-solid fa-eye"></i> Resume PDF</button>` : ''}
              ${hasCover ? `<button class="btn btn-preview" onclick="previewPDF('${job.cover_letter_path}', '${job.company} - Cover Letter')"><i class="fa-solid fa-eye"></i> Cover PDF</button>` : ''}
              
              <button class="btn btn-apply" onclick="launchAssistant(${job.rowid})">
                <i class="fa-solid fa-bolt"></i> 1-Click Apply
              </button>

              ${!isApproved && !isApplied ? `<button class="btn btn-approve" onclick="approveJob(${job.rowid})"><i class="fa-solid fa-check"></i> Approve</button>` : ''}
              ${!isApplied ? `<button class="btn btn-done" onclick="markApplied(${job.rowid})"><i class="fa-solid fa-check-circle"></i> Mark Applied</button>` : ''}

              <a class="btn btn-link" href="${job.apply_url || job.url}" target="_blank" rel="noopener">
                <i class="fa-solid fa-arrow-up-right-from-square"></i> Portal
              </a>
            </div>
          </div>
        `;
      }).join('');
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

    async function approveJob(rowid) {
      const res = await fetch(`/api/jobs/${rowid}/approve`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast('Job marked Approved!');
        fetchJobs();
      }
    }

    async function markApplied(rowid) {
      const res = await fetch(`/api/jobs/${rowid}/applied`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast('Job recorded as APPLIED in database and CSV updated!');
        fetchJobs();
      }
    }

    async function launchAssistant(rowid) {
      showToast('Launching 1-Click Playwright Assistant on your screen...');
      const res = await fetch(`/api/jobs/${rowid}/launch`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast('Browser launched! Pre-filling candidate info & tailored PDF...');
      } else {
        showToast('Error: ' + data.message);
      }
    }

    function showToast(msg) {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.style.display = 'block';
      setTimeout(() => { t.style.display = 'none'; }, 4000);
    }

    fetchJobs();
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

        elif path == "/api/jobs":
            conn = get_connection()
            c = conn.cursor()
            query = """
                SELECT 
                    rowid,
                    COALESCE(site, 'Unknown') AS company,
                    COALESCE(title, 'N/A') AS title,
                    COALESCE(location, 'N/A') AS location,
                    fit_score,
                    score_reasoning,
                    COALESCE(application_url, url) AS apply_url,
                    url,
                    tailored_resume_path,
                    cover_letter_path,
                    apply_status,
                    applied_at
                FROM jobs
                ORDER BY fit_score DESC NULLS LAST, discovered_at DESC
            """
            rows = c.execute(query).fetchall()
            cols = [d[0] for d in c.description]
            jobs = [dict(zip(cols, r)) for r in rows]

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(jobs).encode("utf-8"))
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

        # /api/jobs/{rowid}/approve
        if path.startswith("/api/jobs/") and path.endswith("/approve"):
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

        # /api/jobs/{rowid}/applied
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

        # /api/jobs/{rowid}/launch
        elif path.startswith("/api/jobs/") and path.endswith("/launch"):
            parts = path.split("/")
            rowid = int(parts[3])
            from applypilot.apply.assistant import launch_application_assistant

            # Launch Playwright browser in background thread so HTTP response returns immediately
            t = threading.Thread(target=launch_application_assistant, args=(rowid, True), daemon=True)
            t.start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "rowid": rowid}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()


def start_dashboard_server(port: int = PORT, open_browser: bool = True):
    """Start the interactive dashboard server and open it in Chrome/default browser."""
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    url = f"http://127.0.0.1:{port}"
    print(f"\n🚀 ApplyPilot Interactive Dashboard running at: {url}")
    print("   Press Ctrl+C to stop the dashboard server.\n")

    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
        server.shutdown()
