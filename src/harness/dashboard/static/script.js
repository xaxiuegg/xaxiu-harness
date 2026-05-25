(function () {
  'use strict';

  const sections = {
    loop: document.querySelector('#loop .content'),
    phases: document.querySelector('#phases .content'),
    dispatches: document.querySelector('#dispatches .content'),
    'status-summary': document.querySelector('#status-summary .content'),
    'wave-plan': document.querySelector('#wave-plan .content'),
    flags: document.querySelector('#flags .content'),
    heartbeat: document.querySelector('#heartbeat .content'),
  };

  function setText(key, text) {
    const el = sections[key];
    if (el) el.textContent = text;
  }

  // W12-A2 cost widget --------------------------------------------------
  function fmtMoney(n) {
    if (n === null || n === undefined || isNaN(n)) return '—';
    return '$' + Number(n).toFixed(4);
  }

  function fmtBudget(n) {
    if (n === null || n === undefined || isNaN(n)) return '—';
    return '$' + Number(n).toFixed(2);
  }

  function renderCost(cost) {
    const summaryEl = document.querySelector('#cost .cost-summary');
    const barEl = document.querySelector('#cost .cost-bar');
    const subEl = document.querySelector('#cost .cost-sub');
    const paidEl = document.querySelector('#cost .cost-paid');
    const offloadEl = document.querySelector('#cost .cost-offload');
    if (!summaryEl || !barEl) return;
    if (!cost || cost.error) {
      summaryEl.textContent = '(no cost data)';
      barEl.style.width = '0%';
      barEl.className = 'cost-bar';
      return;
    }
    const spent = cost.spent_usd || 0;
    const budget = cost.budget_usd || 5.0;
    const pct = Math.max(0, Math.min(100, (cost.pct_of_budget_used || 0) * 100));
    summaryEl.textContent =
      fmtMoney(spent) + ' spent / ' + fmtBudget(budget) +
      ' (' + (cost.window_label || 'today') + ') — ' +
      (cost.dispatches || 0) + ' dispatches';
    barEl.style.width = pct.toFixed(1) + '%';
    barEl.className = 'cost-bar' + (
      cost.status === 'exhausted' ? ' exhausted'
      : cost.status === 'warn' ? ' warn'
      : ''
    );
    if (subEl) {
      subEl.textContent = (cost.subscription_dispatches || 0) + ' sub';
    }
    if (paidEl) {
      paidEl.textContent = (cost.paid_dispatches || 0) + ' paid';
    }
    if (offloadEl) {
      offloadEl.textContent =
        Math.round((cost.offload_ratio || 0) * 100) + '% offload';
    }
  }

  // W12-A2 L5 banner -----------------------------------------------------
  function renderL5(l5) {
    const banner = document.querySelector('#l5-banner');
    const body = document.querySelector('#l5-banner .l5-body');
    if (!banner || !body) return;
    const events = (l5 && l5.events) || [];
    if (!events.length) {
      banner.classList.add('hidden');
      return;
    }
    banner.classList.remove('hidden');
    body.textContent = events.map(function (ev) {
      return ev.code + ' — ' + ev.summary + '\n  ACTION: ' + ev.action;
    }).join('\n\n');
  }

  function fetchJSON(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error(url + ' returned ' + r.status);
      return r.json();
    });
  }

  function refreshCostAndL5() {
    fetchJSON('/api/cost').then(renderCost).catch(function (e) {
      console.warn('[dashboard] /api/cost', e);
      renderCost(null);
    });
    fetchJSON('/api/l5-events').then(renderL5).catch(function (e) {
      console.warn('[dashboard] /api/l5-events', e);
      renderL5(null);
    });
  }

  refreshCostAndL5();
  setInterval(refreshCostAndL5, 30000);  // 30s refresh
  // --------------------------------------------------------------------

  function renderSnapshot(data) {
    const state = data.state || {};

    // Loop
    const loopLines = [
      'Status: ' + (state.loop_status || '—'),
      'Tick: ' + (state.tick_count ?? '—'),
      'Last tick: ' + (state.last_tick_at || '—'),
    ];
    if (state.escalations && state.escalations.length) {
      loopLines.push('Escalations: ' + state.escalations.length);
    }
    setText('loop', loopLines.join('\n'));

    // Phases
    const phaseStatus = state.phase_status || {};
    const phaseEntries = Object.entries(phaseStatus);
    if (phaseEntries.length) {
      setText('phases', phaseEntries.map(([k, v]) => k + ': ' + v).join('\n'));
    } else {
      setText('phases', '(none)');
    }

    // Active dispatches
    const active = data.active_dispatches || [];
    if (active.length) {
      setText('dispatches', active.length + ' active\n' + active.map(function (d) {
        return (d.task_id || '?') + '  ' + (d.engine || '?') + '  ' + (d.wave_id || '-');
      }).join('\n'));
    } else {
      setText('dispatches', '(none)');
    }

    // Status summary
    const statusSummary = data.status_summary || {};
    const statusParts = Object.entries(statusSummary).map(function (kv) {
      return kv[1] + ' ' + kv[0];
    });
    setText('status-summary', statusParts.length ? statusParts.join(', ') : '(empty)');

    // Wave plan
    const waveCounts = data.wave_plan_counts || {};
    const waveParts = Object.entries(waveCounts).map(function (kv) {
      return kv[1] + ' ' + kv[0];
    });
    setText('wave-plan', waveParts.length ? waveParts.join(', ') : '(none)');

    // Flags
    const flags = data.flags || [];
    if (flags.length) {
      setText('flags', flags.map(function (f) {
        return f.id + '  ' + f.severity.toUpperCase() + '  [' + f.category + ']  ' + f.summary;
      }).join('\n'));
    } else {
      setText('flags', '(no pending flags)');
    }

    // Heartbeat
    const hb = data.heartbeat;
    if (hb) {
      setText('heartbeat', 'Tick #' + hb.tick_count + '  |  Status: ' + hb.loop_status +
        '  |  Dispatches: ' + hb.active_dispatches +
        ' (kimi ' + hb.in_flight_kimi + ', deepseek ' + hb.in_flight_deepseek + ')' +
        '  |  Updated: ' + data.ts);
    } else {
      setText('heartbeat', 'No heartbeat recorded');
    }
  }

  function connect() {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(proto + '//' + window.location.host + '/ws');

    ws.onopen = function () {
      console.log('[dashboard] WebSocket connected');
    };

    ws.onmessage = function (event) {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'snapshot') {
          renderSnapshot(data);
        }
      } catch (e) {
        console.error('[dashboard] failed to parse message', e);
      }
    };

    ws.onerror = function (err) {
      console.error('[dashboard] WebSocket error', err);
    };

    ws.onclose = function () {
      console.log('[dashboard] WebSocket closed, reconnecting in 3s…');
      setTimeout(connect, 3000);
    };
  }

  connect();
})();
