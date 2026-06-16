import time
import datetime
import pyautogui

# Set your target time ("17:50" for 5:50 PM, or "05:50" for 5:50 AM)
TARGET_TIME = "03:20" 

PROMPT_TEXT_1 = """Open UI_for_taxonomy_caracterization_10_0.html. Add AI pre-label loading capability. Make exactly three additions — one <input>, one function, one call. Do not touch any existing logic, locks, or rendering.

Addition 1 — file input button in the HTML
Find the .wiz-eyebrow div at the very top of the <body>. Immediately after the closing </div> of that eyebrow element, add:
html<div id="ai-load-bar" style="display:flex;align-items:center;gap:10px;margin-bottom:1rem;padding:10px 14px;background:var(--accent-bg);border:1px solid var(--accent-bdr);border-radius:var(--r);">
  <span style="font-size:11px;font-family:var(--mono);font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--accent-text);">AI Pre-Label</span>
  <input type="file" id="ai-prelabel-input" accept=".json" style="font-size:12px;color:var(--text2);">
  <span id="ai-load-status" style="font-size:12px;font-family:var(--mono);color:var(--text3);"></span>
</div>

Addition 2 — the ingestAI(data) function
Add this function anywhere before the closing </script> tag, after buildExport():
javascriptfunction ingestAI(data) {
  // ── T1 ───────────────────────────────────────────────────────
  if (data.T1) {
    var t1 = data.T1;
    if (t1.approved    != null) S.isApproved         = t1.approved;
    if (t1.disapprove_reason)   S.t1DisapproveReason = t1.disapprove_reason;
    if (t1.scope)               S.t1Scope            = t1.scope;
    if (t1.t1Field)             S.t1Field            = t1.t1Field;
    if (t1.t1Target)            S.t1Target           = t1.t1Target;
    if (t1.innovTarget && !t1.t1Target) S.t1Target   = t1.innovTarget; // fallback key
    if (t1.arch_count  != null) S.archCount          = parseInt(t1.arch_count) || 1;
  }

  // ── G1 ───────────────────────────────────────────────────────
  if (data.G1 && data.G1.topType) {
    S.topType  = data.G1.topType;
    S.g1Focus  = ['TW','TP','DS','CVT','SLC','SRW'].indexOf(S.topType) > -1 ? 'winged'
               : ['RC','MR'].indexOf(S.topType) > -1 ? 'wingless' : 'other';

    // Apply all physics locks — mirrors Audit B-02 exactly
    if (S.topType === 'TP') {
      for (var i = 1; i <= 4; i++) { S['wTilt' + i] = 'Fixed'; }
    } else if (S.topType === 'TW') {
      S.wTilt1 = 'Tilt';
      for (var i = 1; i <= 4; i++) { S['m3_wing' + i + '_orient'] = 'Fixed_Horizontal'; }
    } else if (S.topType === 'RC' || S.topType === 'MR') {
      for (var i = 1; i <= 4; i++) { S['wTilt' + i] = null; }
    }
  }

  // ── M1 ───────────────────────────────────────────────────────
  if (data.M1) {
    var m1 = data.M1;
    if (m1.wingConf)    S.wingConf  = m1.wingConf;
    if (m1.wCount != null) {
      S.wCount = parseInt(m1.wCount) || 1;
      // BWB/FW/LB have no discrete wings
      if (['BWB','FW','LB'].indexOf(S.wingConf) > -1) S.wCount = 0;
    }
    if (m1.empType)     S.empType   = m1.empType;
    if (m1.empKin)      S.empKin    = m1.empKin;
    if (m1.fusShape)    S.fusShape  = m1.fusShape;
    if (m1.fusKin)      S.fusKin    = m1.fusKin;
    if (m1.gearArch)    S.gearArch  = m1.gearArch;
    if (m1.latSym != null) S.latSym = !!m1.latSym;

    // TW empennage lock: must be Fixed
    if (S.topType === 'TW' && S.empType && S.empType !== 'Tailless' && S.empType !== 'Fins') {
      S.empKin = 'Fixed';
    }
    // RC empennage kin: only Fixed or Stabilator allowed
    if (S.topType === 'RC' && S.empKin === 'Tilt') {
      S.empKin = 'Fixed';
    }
  }

  // ── Wings (per-wing detail, if provided) ─────────────────────
  if (Array.isArray(data.wings)) {
    data.wings.forEach(function(w, idx) {
      var i = w.id || (idx + 1);
      if (w.tilt) S['wTilt' + i] = w.tilt;
      if (w.posV) S['wPosV' + i] = w.posV;
      if (w.posL) S['wPosL' + i] = w.posL;
      if (w.plan) {
        if (['Str','Swp','Del','Oth'].indexOf(w.plan) > -1) {
          S['wPlan' + i] = w.plan;
        } else {
          S['wPlan' + i] = 'Oth'; S['wPlanOth' + i] = w.plan;
        }
      }
      if (i > 1 && w.role) S['wRole' + i] = w.role;
    });

    // Re-apply TP/TW tilt locks AFTER wing data (AI might have sent wrong tilt values)
    if (S.topType === 'TP') {
      for (var i = 1; i <= 4; i++) { S['wTilt' + i] = 'Fixed'; }
    }
    if (S.topType === 'TW') { S.wTilt1 = 'Tilt'; }
  }

  // ── T2 per-figure ─────────────────────────────────────────────
  if (data.T2 && typeof data.T2 === 'object') {
    Object.keys(data.T2).forEach(function(figNum) {
      var fig = data.T2[figNum];
      if (!fig || typeof fig !== 'object') return;
      // Only write fields that are non-null and valid strings
      ['per','acSty','acCol','bgSty','bgCol','sym'].forEach(function(key) {
        if (fig[key] != null) figSet(figNum, key, fig[key]);
      });
      if (Array.isArray(fig.parts) && fig.parts.length > 0) {
        figSet(figNum, 'parts', fig.parts);
      }
      // Do NOT auto-approve figures — human must confirm each one
    });
  }

  // ── M3 propulsion cards ───────────────────────────────────────
  if (Array.isArray(data.propulsionCards)) {
    data.propulsionCards.forEach(function(card) {
      var key = card.component;
      if (!key) return;
      ['count','chord','orient','bmech','rmech','zone','zoneChord','zoneSpan','notes'].forEach(function(f) {
        if (card[f] != null) {
          S['m3_' + key + '_' + f] = card[f];
        }
      });
      // TW wing orient lock: override any AI value
      if (S.topType === 'TW' && key.indexOf('wing') > -1) {
        S['m3_' + key + '_orient'] = 'Fixed_Horizontal';
      }
      // SLC/SRW: strip Tilting_Mechanism if AI hallucinated it
      if (['SLC','SRW'].indexOf(S.topType) > -1) {
        if (S['m3_' + key + '_orient'] === 'Tilting_Mechanism') {
          S['m3_' + key + '_orient'] = null;
        }
      }
    });
  }

  // ── Confidence summary in status bar ─────────────────────────
  var confs = [];
  if (data.T1 && data.T1.confidence != null) confs.push(data.T1.confidence);
  if (data.G1 && data.G1.confidence != null) confs.push(data.G1.confidence);
  if (data.M1 && data.M1.confidence != null) confs.push(data.M1.confidence);
  if (data.overall_confidence != null) confs.push(data.overall_confidence);
  var avgConf = confs.length ? (confs.reduce(function(a,b){return a+b;},0)/confs.length) : null;
  var confPct = avgConf != null ? Math.round(avgConf * 100) + '%' : '–';
  var confColor = avgConf >= 0.85 ? 'var(--ok)' : avgConf >= 0.60 ? 'var(--warn)' : 'var(--danger)';
  document.getElementById('ai-load-status').innerHTML =
    '✓ Pre-labels loaded &nbsp;·&nbsp; AI confidence: <b style="color:' + confColor + '">' + confPct + '</b>' +
    (data.G1 && data.G1.reasoning ? ' &nbsp;·&nbsp; <i style="color:var(--text3);">' + data.G1.reasoning + '</i>' : '');

  render();
}

Addition 3 — wire the file input
Find the line document.querySelector('.wiz').addEventListener('input', function(e){ and add this block immediately before it:
javascriptdocument.getElementById('ai-prelabel-input').addEventListener('change', function(e) {
  var file = e.target.files[0];
  if (!file) return;
  var reader = new FileReader();
  reader.onload = function(ev) {
    try {
      var data = JSON.parse(ev.target.result);
      ingestAI(data);
    } catch(err) {
      document.getElementById('ai-load-status').textContent = '✗ Invalid JSON: ' + err.message;
    }
  };
  reader.readAsText(file);
});

Do not touch anything else. All physics locks, canGo() gates, keyboard shortcuts, buildExport(), and render functions stay exactly as they are. The human still steps through every tab and confirms or overrides the AI values — the wizard just starts pre-filled."""

PROMPT_TEXT_2 = """Now, I want you to read this document very well, and see if the AI review notebook and the human review HTML that we are talking about are really in sync. The master copy, the best one, the one that you must follow is the one on the path: 
/mnt/storage_11tb/Drive_files_to_syncronize/UI_for_taxonomy_caracterization_10.0.html

Based strictly on the rules of this master HTML, write and apply all the necessary modifications to both the AI review notebook and the human review HTML so that they conform to it perfectly. 

Take all the time necessary. Look closely at the locks and heuristics within it, because each page is associated with the previous one (for example, a rotorcraft (G1) can have wings, but in the M3 prop section, it won't have propulsors on the wings). Ensure all dependency logic, state conditions, and schema fields strictly track this file."""

print(f"⏰ Timer active. Waiting until {TARGET_TIME}...")
print("⚠️ CRITICAL: Click your mouse inside the chat box right now so the cursor is blinking there!")

while True:
    now = datetime.datetime.now().strftime("%H:%M")
    if now == TARGET_TIME:
        # Taps the keys to type your first prompt and hits enter
        print("🚀 Sending Prompt 1...")
        pyautogui.typewrite(PROMPT_TEXT_1, interval=0.01)
        pyautogui.press('enter')
        print("📨 Prompt 1 sent!")
        
        # Wait 20 minutes (20 minutes * 60 seconds = 1200 seconds)
        print("⏳ Waiting 20 minutes before feeding the second prompt...")
        time.sleep(20 * 60)
        
        # Taps the keys to type your second prompt and hits enter
        print("🚀 Sending Prompt 2...")
        pyautogui.typewrite(PROMPT_TEXT_2, interval=0.01)
        pyautogui.press('enter')
        print("🎉 Both prompts sent successfully!")
        break
        
    time.sleep(5)  # Checks every 5 seconds