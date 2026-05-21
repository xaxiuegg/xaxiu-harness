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
