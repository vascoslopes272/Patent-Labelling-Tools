import time
import datetime
import pyautogui

# Set your target time ("17:50" for 5:50 PM, or "05:50" for 5:50 AM)
TARGET_TIME = "02:20" 

PROMPT_TEXT = """Create a new file: tools/02_ai_review.html
                Do NOT modify any existing files.

                PURPOSE:
                Standalone local HTML review UI (opened via file:/// in browser).
                Loads an existing labels/{patent_id}.json and its ai_prelabel.json,
                displays AI pre-labels alongside figure images for human review and correction,
                then exports the corrected final JSON.

                DESIGN TOKENS (match existing UI exactly):
                --bg:#F5F4F0; --bg2:#EDECE7; --surface:#fff; --border:#D6D5CF;
                --text:#1A1A18; --text2:#5A5955; --text3:#8A8985;
                --accent:#2D5BE3; --accent-bg:#EEF2FD; --accent-text:#1A3A9E;
                --ok:#1A7F4E; --ok-bg:#EAF6F0;
                --warn:#9A4F0A; --warn-bg:#FDF3E7;
                --danger:#C0392B;
                Fonts: IBM Plex Sans + IBM Plex Mono (Google Fonts import)

                LAYOUT — three panels:

                PANEL A — File Loader (shown only before files loaded):
                - <input type="file" id="load-base-json"> label: "Load labels JSON"
                - <input type="file" id="load-ai-json">   label: "Load AI prelabel JSON"
                - <input type="file" id="load-images" multiple accept="image/png,image/jpeg">
                    label: "Load figure images (select all PNGs for this patent)"
                - "Load Patent" button → triggers STATE initialization
                - Store images in a Map: filename → object URL (URL.createObjectURL)

                PANEL B — Patent Header (shown after load):
                - Patent ID, title, assignee, pub_year
                - T1 AI labels as editable chips:
                    scope | field | target | approved (toggle) | arch_count
                    Each chip shows: label name, AI value, confidence badge
                    Confidence badge colors: green ≥0.85, yellow 0.60-0.85, red <0.60
                - G1 topology: large badge with topology code + confidence + reasoning tooltip
                - Override button on each chip opens a small inline dropdown to change value

                PANEL C — Figure Review Grid (one card per figure):
                Each card shows:
                LEFT: figure image (from loaded images Map, matched by filename)
                RIGHT:
                    - Figure number + match_status badge (from base JSON: matched/unmatched/no_label/duplicate)
                    - Matched description text (highlighted)
                    - AI T2 labels as editable chips: perspective | style | symmetry | parts (multi-select)
                    - Each chip has confidence badge (same color scheme)
                    - "✓ Approve" / "✗ Reject" buttons for this figure
                    - "★ Set as Main" button (mutually exclusive)
                    - Yellow border on card if needs_review: true OR overall_confidence < 0.70

                STATE OBJECT:
                {
                patentId: str,
                baseData: {},      // raw loaded labels JSON
                aiData: {},        // raw loaded ai_prelabel JSON
                images: Map,       // filename → objectURL
                overrides: {       // human edits keyed by field path
                    "T1.scope": "Pioneering",
                    "T2.1.perspective": "Front",
                    ...
                },
                figureStatus: {    // per fig_number
                    "1": { approved: null, isMain: false }
                }
                }

                MERGE LOGIC (getMergedValue(path)):
                1. Check overrides[path] → if set, return it with source="human"
                2. Check aiData for path → return value with source="ai", confidence
                3. Check baseData visual field → return with source="auto"
                4. Return null, source=null

                EXPORT (buildFinalJSON()):
                Deep-merge baseData + aiData + overrides into final JSON.
                Add per-field "source" and "confidence" tracking.
                For each T3_image entry: inject merged T2 fields + approval status.
                Inject merged T1 fields (scope, field, target, approved, arch_count).
                Inject G1 topology.
                Add export_metadata: { exported_at, human_overrides_count, ai_labels_count }
                Trigger download as {patent_id}_reviewed.json

                JAVASCRIPT RULES:
                - All event listeners via document.addEventListener('click', ...) delegation
                - Use data-action and data-field attributes on interactive elements
                - No inline onclick handlers
                - No localStorage or sessionStorage
                - All state in a single STATE object
                - render() function rebuilds Panel B + C from STATE on every state change

                INTERACTION FLOW:
                1. User loads files → STATE initialized → render()
                2. User clicks any confidence badge → opens inline override dropdown
                3. User selects new value → STATE.overrides updated → render()
                4. User approves/rejects figures → STATE.figureStatus updated → render()
                5. "Export Final JSON" button → buildFinalJSON() → download

                PROGRESS TRACKER (top bar):
                - "X / Y figures reviewed" counter
                - "Z human overrides" counter
                - Overall confidence bar (avg of all AI confidences)"""

print(f"⏰ Timer active. Waiting until {TARGET_TIME}...")
print("⚠️ CRITICAL: Click your mouse inside the Claude chat box right now so the cursor is blinking there!")

while True:
    now = datetime.datetime.now().strftime("%H:%M")
    if now == TARGET_TIME:
        # Taps the keys to type your prompt and hits enter
        pyautogui.typewrite(PROMPT_TEXT, interval=0.01)
        pyautogui.press('enter')
        print("� Prompt sent successfully!")
        break
    time.sleep(5) # Double-checks every 5 seconds