/**
 * ApplyPilot Command Center Frontend Application (Linear/Vercel Dark Theme)
 */

// State
let allJobs = [];
let allFollowups = [];
let currentView = 'action_queue';
let selectedJob = null;
let quickFilters = {
  score8: false,
  tier1: false,
  remote: false,
};
let globalSearchQuery = '';

// Dom Ready
document.addEventListener('DOMContentLoaded', () => {
  initKeyboardShortcuts();
  initSearchInput();
  fetchInitialData();
  refreshLucideIcons();
  startPeriodicPolling();
});

function refreshLucideIcons() {
  if (window.lucide && typeof window.lucide.createIcons === 'function') {
    window.lucide.createIcons();
  }
}

// --------------------------------------------------------------------------
// Keyboard Shortcuts
// --------------------------------------------------------------------------
function initKeyboardShortcuts() {
  window.addEventListener('keydown', (e) => {
    // Cmd/Ctrl + K Focus search
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      const searchInput = document.getElementById('global-search');
      if (searchInput) {
        searchInput.focus();
        searchInput.select();
      }
    }
    // Escape closes drawer and modals
    if (e.key === 'Escape') {
      closeDrawer();
      closePdfModal();
      closeJobLinkModal();
      closeCopilotModal();
      closeIgnoreModal();
    }
  });
}

function initSearchInput() {
  const input = document.getElementById('global-search');
  if (input) {
    input.addEventListener('input', (e) => {
      globalSearchQuery = e.target.value.trim().toLowerCase();
      renderCurrentView();
    });
  }
}

// --------------------------------------------------------------------------
// Data Fetching
// --------------------------------------------------------------------------
async function fetchInitialData() {
  await Promise.allSettled([
    fetchJobs(),
    fetchFollowupsDue(),
    fetchOutreachSummary(),
    checkAllServices(),
  ]);
  renderCurrentView();
  updateBadges();
}

function startPeriodicPolling() {
  // Check health and followups periodically
  setInterval(() => {
    fetchFollowupsDue();
    checkAllServices();
  }, 45000);
}

async function fetchJobs() {
  try {
    const res = await fetch('/api/jobs');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    allJobs = Array.isArray(data) ? data : [];
    updateBadges();
    renderCurrentView();
  } catch (err) {
    showToast(`Failed loading jobs: ${err.message}`, 'error');
  }
}

async function fetchFollowupsDue() {
  try {
    const res = await fetch('/api/followups/due');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.status === 'ok' && Array.isArray(data.actions)) {
      allFollowups = data.actions;
    } else if (Array.isArray(data)) {
      allFollowups = data;
    } else {
      allFollowups = [];
    }
    updateBadges();
    if (currentView === 'action_queue') {
      renderActionQueue();
    }
  } catch (err) {
    console.warn('Failed fetching followups:', err);
  }
}

async function checkAllServices() {
  try {
    // Check LinkedIn
    const resLi = await fetch('/api/linkedin/status');
    const dataLi = await resLi.json();
    const isLiAuth = !!dataLi.authenticated;
    updateDot('dot-linkedin', isLiAuth ? 'dot-emerald' : 'dot-rose');
    const badgeLi = document.getElementById('sh-linkedin-badge');
    if (badgeLi) {
      badgeLi.textContent = isLiAuth ? 'ACTIVE' : 'OFFLINE';
      badgeLi.className = 'status-badge ' + (isLiAuth ? 'pill-emerald' : 'pill-rose');
    }
    const bodyLi = document.getElementById('sh-linkedin-body');
    if (bodyLi) {
      bodyLi.textContent = isLiAuth
        ? 'Active LinkedIn session authenticated. Ready for 1-click Voyager connect & scanning.'
        : 'Session not active. Attach Chrome session or add li_at cookie.';
    }

    // Check Naukri
    const resNk = await fetch('/api/naukri/status');
    const dataNk = await resNk.json();
    updateDot('dot-naukri', 'dot-emerald');
    const badgeNk = document.getElementById('sh-naukri-badge');
    if (badgeNk) {
      badgeNk.textContent = 'READY';
      badgeNk.className = 'status-badge pill-emerald';
    }

    // Gmail & Poller default to healthy
    updateDot('dot-gmail', 'dot-emerald');
    updateDot('dot-poller', 'dot-emerald');
    const badgeGm = document.getElementById('sh-gmail-badge');
    if (badgeGm) {
      badgeGm.textContent = 'CONNECTED';
      badgeGm.className = 'status-badge pill-emerald';
    }
  } catch (err) {
    console.warn('Health check issue:', err);
  }
}

function updateDot(elementId, className) {
  const el = document.getElementById(elementId);
  if (el) {
    el.className = 'live-dot ' + className;
  }
}

// --------------------------------------------------------------------------
// Navigation & Views
// --------------------------------------------------------------------------
function switchView(viewName) {
  currentView = viewName;
  document.querySelectorAll('.sidebar-nav .nav-item').forEach((item) => {
    if (item.getAttribute('data-view') === viewName) {
      item.classList.add('active');
    } else {
      item.classList.remove('active');
    }
  });

  document.querySelectorAll('.view-pane').forEach((pane) => {
    pane.classList.remove('active');
  });

  const activePane = document.getElementById(`view-${viewName}`);
  if (activePane) {
    activePane.classList.add('active');
  }

  renderCurrentView();
  refreshLucideIcons();
}

function toggleQuickFilter(filterKey) {
  quickFilters[filterKey] = !quickFilters[filterKey];
  const pill = document.getElementById(`filter-${filterKey}`);
  if (pill) {
    pill.classList.toggle('active', quickFilters[filterKey]);
  }
  renderCurrentView();
}

function renderCurrentView() {
  switch (currentView) {
    case 'action_queue':
      renderActionQueue();
      break;
    case 'fresh_jobs':
      renderFreshJobs();
      break;
    case 'all_pipeline':
      renderAllPipeline();
      break;
    case 'outreach':
      renderOutreachView();
      break;
    case 'system_health':
      // Health view static cards
      break;
  }
  refreshLucideIcons();
}

function updateBadges() {
  // Fresh jobs (<4h)
  const nowMs = Date.now();
  const fourHoursMs = 4 * 60 * 60 * 1000;
  const freshCount = allJobs.filter((j) => {
    if (j.apply_status === 'applied' || j.apply_status === 'ignored' || j.apply_status === 'rejected') return false;
    const d = parseJobDate(j);
    return d && (nowMs - d.getTime()) <= fourHoursMs && (nowMs - d.getTime()) >= 0;
  }).length;

  // Action Queue (Due followups + active holds)
  const holdCount = allJobs.filter(j => j.apply_status === 'REFERRAL_HOLD').length;
  const dueCount = allFollowups.length;
  const actionQueueTotal = dueCount + holdCount;

  setBadge('badge-action-queue', actionQueueTotal);
  setBadge('badge-fresh-jobs', freshCount);
  setBadge('badge-all-pipeline', allJobs.length);

  const aqDue = document.getElementById('aq-due-count');
  if (aqDue) aqDue.textContent = dueCount;
  const aqHold = document.getElementById('aq-hold-count');
  if (aqHold) aqHold.textContent = holdCount;

  const freshTot = document.getElementById('fresh-total-count');
  if (freshTot) freshTot.textContent = freshCount;

  const pipeTot = document.getElementById('pipeline-total-count');
  if (pipeTot) pipeTot.textContent = allJobs.length;

  const pipeTail = document.getElementById('pipeline-tailored-count');
  if (pipeTail) pipeTail.textContent = allJobs.filter(j => !!j.tailored_resume_path).length;

  const pipeApp = document.getElementById('pipeline-applied-count');
  if (pipeApp) pipeApp.textContent = allJobs.filter(j => j.apply_status === 'applied').length;
}

function setBadge(id, count) {
  const el = document.getElementById(id);
  if (el) el.textContent = count;
}

// --------------------------------------------------------------------------
// 1. Action Queue View Render
// --------------------------------------------------------------------------
function renderActionQueue() {
  const tbody = document.getElementById('tbody-action-queue');
  if (!tbody) return;

  // Combine due actions and referral hold jobs
  const rows = [];

  // Due actions from followup engine
  allFollowups.forEach((a) => {
    rows.push({
      type: 'due_followup',
      id: a.job_id,
      company: a.company || 'Company',
      title: a.title || 'Software Engineer',
      stage: a.stage || 'FOLLOWUP_DUE',
      email: a.email_to_use || 'deepakshkarkala@gmail.com',
      due: a.due_at ? formatTimeAgo(new Date(a.due_at)) : 'Due now',
      raw: a,
    });
  });

  // Active referral holds from allJobs
  const holdJobs = allJobs.filter(j => j.apply_status === 'REFERRAL_HOLD');
  holdJobs.forEach((j) => {
    const discovered = parseJobDate(j);
    let countdownText = '48h hold';
    if (discovered) {
      const expiresAt = discovered.getTime() + (48 * 60 * 60 * 1000);
      const diffMs = expiresAt - Date.now();
      countdownText = formatCountdown(diffMs);
    }
    rows.push({
      type: 'hold',
      id: j.rowid,
      company: j.company,
      title: j.title,
      stage: 'REFERRAL_HOLD',
      email: 'PRIMARY (deepakshkarkala@gmail.com)',
      due: countdownText,
      raw: j,
    });
  });

  if (rows.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="5" style="text-align: center; padding: 36px; color: var(--text-dim);">
          <i data-lucide="check-circle-2" style="width: 24px; height: 24px; margin-bottom: 8px; color: var(--tint-emerald-text);"></i>
          <div>All clear! No overdue follow-ups or pending 48h holds.</div>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = rows.map((r) => {
    const pillClass = r.stage.includes('HOLD') ? 'pill-amber' : 'pill-indigo';
    const isHold = r.type === 'hold';
    return `
      <tr onclick="onActionQueueRowClick('${r.type}', '${r.id}')">
        <td>
          <div class="cell-identity">
            <span class="cell-title">${escapeHtml(r.title)}</span>
            <span class="cell-company">${escapeHtml(r.company)}</span>
          </div>
        </td>
        <td>
          <span class="status-pill ${pillClass}">${escapeHtml(r.stage)}</span>
        </td>
        <td>
          <span class="cell-mono">${escapeHtml(r.email)}</span>
        </td>
        <td>
          <span class="cell-mono" style="font-weight: 600;">${escapeHtml(r.due)}</span>
        </td>
        <td>
          <div class="cell-actions" onclick="event.stopPropagation()">
            ${isHold ? `
              <button class="btn-row-action highlight" onclick="openDrawerByRowId(${r.id})">
                <i data-lucide="send" class="micro-icon"></i> Find Referrer
              </button>
            ` : `
              <button class="btn-row-action" onclick="copyActionTemplate('${r.id}')">
                <i data-lucide="copy" class="micro-icon"></i> Copy
              </button>
              <button class="btn-row-action highlight" onclick="acknowledgeAction('${r.id}')">
                <i data-lucide="check" class="micro-icon"></i> Ack
              </button>
            `}
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

function onActionQueueRowClick(type, id) {
  if (type === 'hold') {
    openDrawerByRowId(id);
  } else {
    const action = allFollowups.find(a => String(a.job_id) === String(id));
    if (action) {
      // Find matching job if exists
      const match = allJobs.find(j => (j.company && action.company && j.company.toLowerCase() === action.company.toLowerCase()));
      if (match) {
        openDrawer(match, action);
      } else {
        openDrawer({
          rowid: id,
          company: action.company,
          title: action.title,
          apply_status: action.stage,
          fit_score: 8,
          score_reasoning: 'Active referral follow-up item.',
        }, action);
      }
    }
  }
}

// --------------------------------------------------------------------------
// 2. Fresh Jobs View Render (<4h)
// --------------------------------------------------------------------------
function renderFreshJobs() {
  const tbody = document.getElementById('tbody-fresh-jobs');
  if (!tbody) return;

  const nowMs = Date.now();
  const fourHoursMs = 4 * 60 * 60 * 1000;

  let filtered = allJobs.filter((j) => {
    if (j.apply_status === 'applied' || j.apply_status === 'ignored' || j.apply_status === 'rejected') return false;
    const d = parseJobDate(j);
    return d && (nowMs - d.getTime()) <= fourHoursMs && (nowMs - d.getTime()) >= 0;
  });

  filtered = applyQuickAndSearchFilters(filtered);

  renderJobRows(tbody, filtered, true);
}

// --------------------------------------------------------------------------
// 3. All Pipeline View Render
// --------------------------------------------------------------------------
function renderAllPipeline() {
  const tbody = document.getElementById('tbody-all-pipeline');
  if (!tbody) return;

  let filtered = applyQuickAndSearchFilters(allJobs);
  renderJobRows(tbody, filtered, false);
}

function applyQuickAndSearchFilters(list) {
  return list.filter((j) => {
    if (quickFilters.score8 && (j.fit_score || 0) < 8) return false;
    if (quickFilters.tier1 && j.apply_status !== 'REFERRAL_HOLD') return false;
    if (quickFilters.remote) {
      const loc = (j.location || '').toLowerCase();
      if (!loc.includes('remote') && !loc.includes('work from home')) return false;
    }
    if (globalSearchQuery) {
      const text = `${j.company} ${j.title} ${j.location} ${j.score_reasoning || ''}`.toLowerCase();
      if (!text.includes(globalSearchQuery)) return false;
    }
    return true;
  });
}

function renderJobRows(tbody, jobs, isFreshView) {
  if (jobs.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; padding: 36px; color: var(--text-dim);">
          No matching jobs found.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = jobs.slice(0, 100).map((job) => {
    const fit = job.fit_score || 0;
    const fitClass = fit >= 8 ? 'fit-high' : (fit >= 6 ? 'fit-mid' : 'fit-low');
    const statusPill = getStatusPill(job);
    const dateObj = parseJobDate(job);
    const ageStr = dateObj ? formatTimeAgo(dateObj) : 'Recently';

    return `
      <tr onclick="openDrawerByRowId(${job.rowid})">
        <td>
          <span class="cell-fit ${fitClass}">${fit}</span>
        </td>
        <td>
          <div class="cell-identity">
            <span class="cell-title">${escapeHtml(job.title)}</span>
            <span class="cell-company">${escapeHtml(job.company)}</span>
          </div>
        </td>
        <td>
          <div class="cell-identity">
            <span style="font-size: 11.5px; color: var(--text-primary);">${escapeHtml(job.source || 'Direct')}</span>
            <span style="font-size: 11px; color: var(--text-dim);">${escapeHtml(job.location || 'India')}</span>
          </div>
        </td>
        <td>
          <span class="cell-mono">${escapeHtml(ageStr)}</span>
        </td>
        <td>
          ${statusPill}
        </td>
        <td>
          <div class="cell-actions" onclick="event.stopPropagation()">
            <button class="btn-row-action" title="Open Portal in Brave" onclick="openBraveDirect(${job.rowid})">
              <i data-lucide="external-link" class="micro-icon"></i>
            </button>
            <button class="btn-row-action highlight" title="Compile JIT Resume" onclick="tailorJobDirect(${job.rowid})">
              <i data-lucide="sparkles" class="micro-icon"></i>
            </button>
            <button class="btn-row-action" title="Mark Applied" onclick="markAppliedDirect(${job.rowid})">
              <i data-lucide="check" class="micro-icon"></i>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

function getStatusPill(job) {
  const status = (job.apply_status || '').toUpperCase();
  if (status === 'REFERRAL_HOLD') {
    return `<span class="status-pill pill-amber">HOLD (48h)</span>`;
  } else if (status === 'REPLIED_ACTIVE' || status === 'INTERVIEW' || status === 'OA') {
    return `<span class="status-pill pill-emerald">${escapeHtml(status)}</span>`;
  } else if (status === 'READY_TO_APPLY' || status === 'APPROVED') {
    return `<span class="status-pill pill-indigo">${escapeHtml(status)}</span>`;
  } else if (status === 'REJECTED') {
    return `<span class="status-pill pill-rose">REJECTED</span>`;
  } else if (status === 'APPLIED') {
    return `<span class="status-pill pill-emerald">APPLIED</span>`;
  } else if (status === 'IGNORED') {
    return `<span class="status-pill pill-neutral">IGNORED</span>`;
  }
  return `<span class="status-pill pill-neutral">OPEN</span>`;
}

// --------------------------------------------------------------------------
// 4. Outreach & Referrals View
// --------------------------------------------------------------------------
async function fetchOutreachSummary() {
  try {
    const res = await fetch('/api/referral_crm/summary');
    if (!res.ok) return;
    const data = await res.json();
    const reqs = data.requests || [];
    setBadge('badge-outreach', reqs.length);

    const mTot = document.getElementById('crm-total-requests');
    if (mTot) mTot.textContent = data.total_requests || reqs.length || 0;

    const mAcc = document.getElementById('crm-accepted-requests');
    if (mAcc) mAcc.textContent = data.accepted_count || 0;

    const mCold = document.getElementById('crm-cold-emails');
    if (mCold) mCold.textContent = data.cold_outreach_count || 0;

    const mCalls = document.getElementById('crm-interview-calls');
    if (mCalls) mCalls.textContent = data.calls_count || 0;

    window._outreachRequests = reqs;
  } catch (e) {
    console.warn('Outreach summary err:', e);
  }
}

function renderOutreachView() {
  const tbody = document.getElementById('tbody-outreach');
  if (!tbody) return;
  const reqs = window._outreachRequests || [];

  if (reqs.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="5" style="text-align: center; padding: 36px; color: var(--text-dim);">
          No connection requests logged yet. Use the drawer on any job to send targeted LinkedIn outreach.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = reqs.map((r) => {
    const isAcc = (r.status || '').toLowerCase() === 'accepted';
    return `
      <tr>
        <td>
          <div class="cell-identity">
            <span class="cell-title">${escapeHtml(r.person_name || 'Connection')}</span>
            <span class="cell-company">${escapeHtml(r.company || '')}</span>
          </div>
        </td>
        <td>
          <span style="font-size: 11.5px; color: var(--text-muted);">${escapeHtml(r.headline || 'Engineer')}</span>
        </td>
        <td>
          <span class="cell-mono">${r.is_alumni ? '🎓 RVCE Alumni' : (r.degree || '2nd')}</span>
        </td>
        <td>
          <span class="status-pill ${isAcc ? 'pill-emerald' : 'pill-amber'}">
            ${escapeHtml((r.status || 'SENT').toUpperCase())}
          </span>
        </td>
        <td>
          <div class="cell-actions">
            ${r.profile_url ? `
              <a href="${escapeHtml(r.profile_url)}" target="_blank" class="btn-row-action" style="text-decoration: none;">
                <i data-lucide="external-link" class="micro-icon"></i> Profile
              </a>
            ` : ''}
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

async function syncAcceptedConnections() {
  showToast('Syncing accepted LinkedIn connection requests...', 'info');
  try {
    const res = await fetch('/api/referral_crm/sync_accepted', { method: 'POST' });
    const data = await res.json();
    showToast(`Accepted sync complete: ${data.accepted_found || 0} accepted, ${data.new_sent_discovered || 0} sent recorded.`, 'ok');
    await fetchOutreachSummary();
    renderOutreachView();
  } catch (err) {
    showToast(`Sync error: ${err.message}`, 'error');
  }
}

// --------------------------------------------------------------------------
// Slide-Over Drawer (480px wide)
// --------------------------------------------------------------------------
function openDrawerByRowId(rowid) {
  const job = allJobs.find(j => j.rowid == rowid);
  if (job) {
    openDrawer(job);
  }
}

function openDrawer(job, actionOverride = null) {
  selectedJob = job;

  const drawer = document.getElementById('job-drawer');
  const backdrop = document.getElementById('drawer-backdrop');
  if (!drawer || !backdrop) return;

  // Identity
  const titleEl = document.getElementById('drawer-title');
  if (titleEl) titleEl.textContent = job.title;

  const compEl = document.getElementById('drawer-company');
  if (compEl) compEl.textContent = job.company;

  const locEl = document.getElementById('drawer-location');
  if (locEl) locEl.textContent = job.location || 'India';

  const fitEl = document.getElementById('drawer-fit-badge');
  if (fitEl) fitEl.textContent = `FIT: ${job.fit_score || 0}/10`;

  const statusEl = document.getElementById('drawer-status-badge');
  if (statusEl) statusEl.textContent = (job.apply_status || 'OPEN').toUpperCase();

  // Tier-1 Hold Section
  const holdSection = document.getElementById('drawer-hold-section');
  const isHold = (job.apply_status || '').toUpperCase() === 'REFERRAL_HOLD';
  if (holdSection) {
    if (isHold) {
      holdSection.style.display = 'block';
      const cdEl = document.getElementById('drawer-hold-countdown');
      const d = parseJobDate(job);
      if (cdEl && d) {
        const expiresAt = d.getTime() + (48 * 60 * 60 * 1000);
        cdEl.textContent = formatCountdown(expiresAt - Date.now());
      }
    } else {
      holdSection.style.display = 'none';
    }
  }

  // Assigned Email
  const emailEl = document.getElementById('drawer-assigned-email');
  if (emailEl) {
    const assigned = isHold ? 'deepakshkarkala@gmail.com (PRIMARY)' : 'deepakshkarkala@gmail.com (STANDARD)';
    emailEl.textContent = assigned;
  }

  // Fit score reasoning
  const scoreReasonEl = document.getElementById('drawer-score-reasoning');
  if (scoreReasonEl) {
    scoreReasonEl.textContent = job.score_reasoning || 'Strong alignment with Java/Go microservices stack, Kafka event-driven architectures, and high-concurrency systems.';
  }

  // Tailored Resume info
  const resumeStatus = document.getElementById('drawer-resume-status');
  if (resumeStatus) {
    resumeStatus.textContent = job.tailored_resume_path ? 'Tailored PDF ready on disk' : 'Not compiled yet (Click Tailor JIT)';
  }

  // Pre-fill LinkedIn connect note
  const comp = job.company || 'there';
  const role = job.title || 'Software Engineer';
  const liNote = document.getElementById('drawer-linkedin-note');
  if (liNote) {
    liNote.value = `Hi there, I'm an SDE-I Backend Engineer at Meesho (RVCE '25, Java/Go/Kafka/Redis). Interested in the ${role} role at ${comp}. Would love to connect!`.slice(0, 200);
  }
  const liStatus = document.getElementById('drawer-linkedin-status');
  if (liStatus) {
    liStatus.className = 'live-action-status';
    liStatus.style.display = 'none';
  }

  // Follow-up card
  const followupCard = document.getElementById('drawer-followup-card');
  const followupTemplate = document.getElementById('drawer-followup-template');
  if (actionOverride && actionOverride.template_text) {
    if (followupCard) followupCard.style.display = 'block';
    if (followupTemplate) followupTemplate.textContent = actionOverride.template_text;
    window._activeDrawerAction = actionOverride;
  } else if (job.outreach && job.outreach.referral_pitch) {
    if (followupCard) followupCard.style.display = 'block';
    if (followupTemplate) followupTemplate.textContent = job.outreach.referral_pitch;
    window._activeDrawerAction = null;
  } else {
    if (followupCard) followupCard.style.display = 'none';
    window._activeDrawerAction = null;
  }

  drawer.classList.add('open');
  backdrop.classList.add('active');
  refreshLucideIcons();
}

function closeDrawer() {
  const drawer = document.getElementById('job-drawer');
  const backdrop = document.getElementById('drawer-backdrop');
  if (drawer) drawer.classList.remove('open');
  if (backdrop) backdrop.classList.remove('active');
  selectedJob = null;
}

// --------------------------------------------------------------------------
// Drawer Actions
// --------------------------------------------------------------------------
async function tailorCurrentJob() {
  if (!selectedJob) return;
  const btn = document.getElementById('btn-tailor-job');
  if (btn) btn.disabled = true;
  showToast(`Compiling tailored resume for ${selectedJob.company}...`, 'info');
  try {
    const res = await fetch(`/api/jobs/${selectedJob.rowid}/tailor`, { method: 'POST' });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast(`Resume tailored successfully for ${selectedJob.company}!`, 'ok');
      selectedJob.tailored_resume_path = data.pdf_path;
      const st = document.getElementById('drawer-resume-status');
      if (st) st.textContent = 'Tailored PDF ready on disk';
      fetchJobs();
    } else {
      showToast(`Tailoring note: ${data.message || 'Error'}`, 'error');
    }
  } catch (err) {
    showToast(`Tailor error: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

function viewCurrentPdf() {
  if (!selectedJob) return;
  openPdfModal(`/api/jobs/${selectedJob.rowid}/resume`, `Resume: ${selectedJob.company} - ${selectedJob.title}`);
}

async function sendLinkedInConnectFromDrawer() {
  if (!selectedJob) return;
  const profileInput = document.getElementById('drawer-linkedin-profile');
  const noteInput = document.getElementById('drawer-linkedin-note');
  const statusBox = document.getElementById('drawer-linkedin-status');
  const profileUrl = profileInput ? profileInput.value.trim() : '';
  const note = noteInput ? noteInput.value.trim() : '';

  if (!profileUrl) {
    showToast('Please enter a target LinkedIn profile URL.', 'error');
    if (profileInput) profileInput.focus();
    return;
  }

  if (statusBox) {
    statusBox.textContent = 'Sending background request via Voyager API...';
    statusBox.className = 'live-action-status pending';
    statusBox.style.display = 'block';
  }

  try {
    const res = await fetch('/api/linkedin/compose_dm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        profile_url: profileUrl,
        company: selectedJob.company,
        role: selectedJob.title,
        message: note,
        action_type: 'connect',
      }),
    });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast(data.message || 'Connection request sent in background!', 'ok');
      if (statusBox) {
        statusBox.textContent = data.message || 'Sent successfully!';
        statusBox.className = 'live-action-status ok';
      }
    } else {
      showToast(data.message || 'Could not send request', 'error');
      if (statusBox) {
        statusBox.textContent = data.message || 'Request failed';
        statusBox.className = 'live-action-status error';
      }
    }
  } catch (err) {
    showToast(`Connect error: ${err.message}`, 'error');
    if (statusBox) {
      statusBox.textContent = err.message;
      statusBox.className = 'live-action-status error';
    }
  }
}

function copyDrawerFollowUp() {
  const el = document.getElementById('drawer-followup-template');
  if (el && el.textContent) {
    navigator.clipboard.writeText(el.textContent.trim()).then(() => {
      showToast('Follow-up text copied to clipboard!', 'ok');
    }).catch(() => {
      showToast('Copied to clipboard!', 'ok');
    });
  }
}

async function acknowledgeDrawerAction() {
  if (window._activeDrawerAction && window._activeDrawerAction.job_id) {
    await acknowledgeAction(window._activeDrawerAction.job_id);
    closeDrawer();
  } else if (selectedJob) {
    await markDrawerJobApplied();
  }
}

async function acknowledgeAction(jobId) {
  try {
    const encoded = encodeURIComponent(jobId);
    const res = await fetch(`/api/followups/${encoded}/ack`, { method: 'POST' });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast('Follow-up action acknowledged!', 'ok');
      await fetchFollowupsDue();
    } else {
      showToast(`Error: ${data.message}`, 'error');
    }
  } catch (err) {
    showToast(`Ack error: ${err.message}`, 'error');
  }
}

function copyActionTemplate(jobId) {
  const a = allFollowups.find(item => String(item.job_id) === String(jobId));
  if (a && a.template_text) {
    navigator.clipboard.writeText(a.template_text).then(() => {
      showToast(`Copied follow-up template for ${a.company}!`, 'ok');
    });
  }
}

async function openJobInBrave() {
  if (!selectedJob) return;
  await openBraveDirect(selectedJob.rowid);
}

async function openBraveDirect(rowid) {
  try {
    const res = await fetch(`/api/jobs/${rowid}/open_brave`, { method: 'POST' });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast(data.message || 'Opened portal in Brave!', 'ok');
    } else {
      showToast(data.message || 'No direct URL available', 'error');
    }
  } catch (err) {
    showToast(`Brave launcher error: ${err.message}`, 'error');
  }
}

async function tailorJobDirect(rowid) {
  const job = allJobs.find(j => j.rowid == rowid);
  const comp = job ? job.company : '';
  showToast(`Compiling tailored resume for ${comp}...`, 'info');
  try {
    const res = await fetch(`/api/jobs/${rowid}/tailor`, { method: 'POST' });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast(`Tailored resume compiled for ${comp}!`, 'ok');
      await fetchJobs();
    } else {
      showToast(data.message || 'Error compiling', 'error');
    }
  } catch (err) {
    showToast(`Tailor error: ${err.message}`, 'error');
  }
}

async function markAppliedDirect(rowid) {
  try {
    const res = await fetch(`/api/jobs/${rowid}/applied`, { method: 'POST' });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast('Marked as applied!', 'ok');
      await fetchJobs();
    } else {
      showToast(data.message || 'Could not mark applied', 'error');
    }
  } catch (err) {
    showToast(`Mark applied error: ${err.message}`, 'error');
  }
}

async function markDrawerJobApplied() {
  if (!selectedJob) return;
  await markAppliedDirect(selectedJob.rowid);
  closeDrawer();
}

function openIgnoreModalFromDrawer() {
  if (!selectedJob) return;
  openIgnoreModal();
}

async function confirmIgnoreAction() {
  if (!selectedJob) return;
  const reasonRadio = document.querySelector('input[name="ignore-reason"]:checked');
  const reason = reasonRadio ? reasonRadio.value : 'unspecified';
  try {
    const res = await fetch(`/api/jobs/${selectedJob.rowid}/ignore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast('Opportunity ignored and preference logged.', 'info');
      closeIgnoreModal();
      closeDrawer();
      await fetchJobs();
    }
  } catch (err) {
    showToast(`Ignore error: ${err.message}`, 'error');
  }
}

// --------------------------------------------------------------------------
// Topbar Actions (Scan & Auto-apply)
// --------------------------------------------------------------------------
async function triggerScanNow() {
  const icon = document.getElementById('icon-scan-refresh');
  if (icon) icon.classList.add('spin-active');
  showToast('Starting multi-source fresh incognito scan...', 'info');
  try {
    const res = await fetch('/api/linkedin/incognito_scan', { method: 'POST' });
    const data = await res.json();
    showToast(data.message || 'Incognito scan started in background!', 'ok');
    setTimeout(() => { fetchJobs(); }, 8000);
  } catch (err) {
    showToast(`Scan error: ${err.message}`, 'error');
  } finally {
    setTimeout(() => {
      if (icon) icon.classList.remove('spin-active');
    }, 4000);
  }
}

async function triggerAutoApplyBatch() {
  showToast('Launching autonomous auto-apply batch (Score ≥ 7)...', 'info');
  try {
    const res = await fetch('/api/auto_apply_batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: 5, min_score: 7, auto_submit: true }),
    });
    const data = await res.json();
    showToast(`Auto-apply batch launched! Mode: ${data.status}`, 'ok');
  } catch (err) {
    showToast(`Auto-apply error: ${err.message}`, 'error');
  }
}

async function syncGmail() {
  showToast('Syncing Gmail inbox for recruiter updates...', 'info');
  try {
    const res = await fetch('/api/gmail/sync', { method: 'POST' });
    const data = await res.json();
    showToast(`Gmail sync complete: ${data.synced_count || 0} messages synced.`, 'ok');
  } catch (err) {
    showToast(`Gmail sync error: ${err.message}`, 'error');
  }
}

async function triggerAtsSync() {
  showToast('Scraping Direct ATS & Workday career sites...', 'info');
  try {
    const res = await fetch('/api/ats/sync', { method: 'POST' });
    const data = await res.json();
    showToast(data.message || 'ATS sync initiated!', 'ok');
    setTimeout(() => { fetchJobs(); }, 12000);
  } catch (err) {
    showToast(`ATS sync error: ${err.message}`, 'error');
  }
}

async function triggerLinkedInLogin() {
  showToast('Launching interactive LinkedIn login...', 'info');
  try {
    await fetch('/api/linkedin/login', { method: 'POST' });
    showToast('Brave launched for LinkedIn login.', 'ok');
  } catch (e) {
    showToast(`Login trigger error: ${e.message}`, 'error');
  }
}

async function triggerNaukriRefresh() {
  showToast('Initiating Naukri daily profile bump...', 'info');
  try {
    await fetch('/api/naukri/refresh', { method: 'POST' });
    showToast('Naukri profile refresh initiated.', 'ok');
  } catch (e) {
    showToast(`Naukri error: ${e.message}`, 'error');
  }
}

// --------------------------------------------------------------------------
// Modals
// --------------------------------------------------------------------------
function openPdfModal(url, title = 'PDF Preview') {
  const modal = document.getElementById('pdf-modal');
  const frame = document.getElementById('pdf-frame');
  const titleEl = document.getElementById('pdf-modal-title');
  if (frame) frame.src = url;
  if (titleEl) titleEl.textContent = title;
  if (modal) modal.classList.add('active');
  refreshLucideIcons();
}

function closePdfModal() {
  const modal = document.getElementById('pdf-modal');
  const frame = document.getElementById('pdf-frame');
  if (frame) frame.src = '';
  if (modal) modal.classList.remove('active');
}

function openJobLinkModal() {
  const modal = document.getElementById('job-link-modal');
  if (modal) modal.classList.add('active');
  refreshLucideIcons();
}

function closeJobLinkModal() {
  const modal = document.getElementById('job-link-modal');
  if (modal) modal.classList.remove('active');
}

async function submitJobLinkIntake() {
  const urlInput = document.getElementById('intake-job-url');
  const jdInput = document.getElementById('intake-job-jd');
  const url = urlInput ? urlInput.value.trim() : '';
  const jd = jdInput ? jdInput.value.trim() : '';

  if (!url && !jd) {
    showToast('Please provide a job URL or paste JD text.', 'error');
    return;
  }

  showToast('Extracting JD and tailoring resume...', 'info');
  closeJobLinkModal();

  try {
    const res = await fetch('/api/jobs/process_link', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, jd }),
    });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast(`Job processed: ${data.company || ''} ${data.title || ''}!`, 'ok');
      await fetchJobs();
    } else {
      showToast(data.message || 'Processing completed', 'info');
    }
  } catch (err) {
    showToast(`Intake error: ${err.message}`, 'error');
  }
}

function openCopilotModal() {
  const modal = document.getElementById('copilot-modal');
  if (modal) modal.classList.add('active');
  refreshLucideIcons();
}

function closeCopilotModal() {
  const modal = document.getElementById('copilot-modal');
  if (modal) modal.classList.remove('active');
}

async function submitScreeningCopilot() {
  const comp = document.getElementById('copilot-company')?.value.trim() || '';
  const role = document.getElementById('copilot-role')?.value.trim() || 'SDE-I Backend Engineer';
  const q = document.getElementById('copilot-question')?.value.trim() || '';

  if (!q) {
    showToast('Please enter a question to answer.', 'error');
    return;
  }

  const btn = document.getElementById('btn-copilot-submit');
  if (btn) btn.disabled = true;
  showToast('Generating personalized answer with Gemini...', 'info');

  try {
    const res = await fetch('/api/copilot/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company: comp, role_title: role, question: q }),
    });
    const data = await res.json();
    const box = document.getElementById('copilot-answer-box');
    const textEl = document.getElementById('copilot-answer-text');
    if (box && textEl) {
      box.style.display = 'block';
      textEl.textContent = data.answer || data.text || JSON.stringify(data);
    }
    showToast('Grounded answer generated!', 'ok');
  } catch (err) {
    showToast(`Copilot error: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

function copyCopilotAnswer() {
  const textEl = document.getElementById('copilot-answer-text');
  if (textEl && textEl.textContent) {
    navigator.clipboard.writeText(textEl.textContent).then(() => {
      showToast('Copied screening answer to clipboard!', 'ok');
    });
  }
}

function openIgnoreModal() {
  const modal = document.getElementById('ignore-modal');
  if (modal) modal.classList.add('active');
  refreshLucideIcons();
}

function closeIgnoreModal() {
  const modal = document.getElementById('ignore-modal');
  if (modal) modal.classList.remove('active');
}

// --------------------------------------------------------------------------
// Toast System (Bottom-Right)
// --------------------------------------------------------------------------
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span>${escapeHtml(message)}</span>
    <button onclick="this.parentElement.remove()" style="background:none;border:none;color:var(--text-dim);cursor:pointer;padding:2px;">✕</button>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 200);
  }, 4500);
}

function copySnippet(text, label = 'Snippet') {
  navigator.clipboard.writeText(text).then(() => {
    showToast(`Copied ${label} to clipboard: ${text}`, 'ok');
  }).catch(() => {
    showToast(`Copied: ${text}`, 'ok');
  });
}

// --------------------------------------------------------------------------
// Date & Formatting Helpers
// --------------------------------------------------------------------------
function parseJobDate(job) {
  if (job.date_posted) {
    const d = new Date(job.date_posted);
    if (!isNaN(d.getTime())) return d;
  }
  if (job.discovered_at) {
    const d = new Date(job.discovered_at);
    if (!isNaN(d.getTime())) return d;
  }
  return null;
}

function formatTimeAgo(date) {
  const diffMs = Date.now() - date.getTime();
  if (diffMs < 0) return 'Just now';
  const mins = Math.floor(diffMs / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatCountdown(diffMs) {
  if (diffMs <= 0) return '0h 0m (Ready)';
  const totalMins = Math.floor(diffMs / 60000);
  const hrs = Math.floor(totalMins / 60);
  const mins = totalMins % 60;
  return `${hrs}h ${mins}m`;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
