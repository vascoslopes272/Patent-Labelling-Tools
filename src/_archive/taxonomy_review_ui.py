"""taxonomy_review_ui.py — Human-in-the-loop annotation UI for the eVTOL patent pipeline.

Imported by notebooks/01_review.ipynb.
Depends on: ipywidgets, pandas, json, datetime.
NOT dependent on DINOv2.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import ipywidgets as widgets
import pandas as pd
from IPython.display import display as ipy_display

# ---------------------------------------------------------------------------
# Taxonomy constants
# ---------------------------------------------------------------------------

TOP = [("TW","Tilt Wing"),("TP","Tilt Propulsors"),("DS","Deflected Slipstream"),
       ("CVT","Combined CVT"),("SLC","Lift+Cruise"),("SRW","Stopped Rotor Wing"),
       ("RC","Rotorcraft"),("MR","Multirotor"),("HB","Hoverbike"),("PFV","Personal Flying Vehicle")]
WINGED     = {"TW","TP","DS","CVT","SLC","SRW"}
ROTORBORNE = {"RC","MR"}
WING_CONFIG = [("W","Standard Wings"),("BWB","Blended Wing Body"),("FW","Flying Wing"),("LB","Lifting Body")]
W_POS_V  = [("High","High/Hub"),("Mid","Mid/Center"),("Low","Low/Down")]
W_POS_L  = [("Fwd","Forward"),("Cent","Center CG"),("Aft","Aft/Rear")]
W_PLAN   = [("Str","Straight"),("Swp","Swept"),("Del","Delta"),("Oth","Other")]
W_ROLE   = [("Canard","Canard"),("Tandem","Tandem"),("AftStab","Aft Stabilizer"),("Stacked","Stacked")]
W_TILT   = [("Fixed","Fixed Surface"),("Tilt","Tiltable")]
EMP_TYPE = [("Tailless","Tailless"),("Conventional","Conventional"),("Cruciform","Cruciform"),
            ("T-Tail","T-Tail"),("V-Tail","V-Tail"),("Inv_V-Tail","Inv V-Tail"),
            ("H-Tail","H-Tail"),("Fins","Fins")]
EMP_KIN  = [("Fixed","Fixed"),("Tilt","Full aft tilt"),("Stabilator","All-Moving")]
FUS_SHAPE= [("Circular","Circular"),("Oval","Oval"),("Rectangular","Rectangular"),("Blended","Blended")]
FUS_KIN  = [("Fixed","Fixed"),("Variable","Variable Incidence")]
GEAR_ARCH= [("Skids","Skids"),("FixedWheel","Fixed Wheel"),("RetrWheel","Retractable Wheel"),("PadsHull","Pads/Hull")]
CHORD    = [("Front","Front/Puller"),("Back","Back/Pusher")]
BLADE_MECH=[("Open","Open Rotor"),("Ducted","Ducted Fan"),("Folded","Folding Blades")]
RETRACT  = [("Exposed","Non-Retractable"),("Retractable","Retractable")]
ZONE_CHORD=[("LE","Leading Edge"),("TE","Trailing Edge"),("Above","Above Surface"),("Below","Below Surface")]
ZONE_SPAN =[("Inboard","Inboard"),("MidSpan","Mid-Span"),("Outboard","Outboard"),("Wingtip","Wingtip")]
ZONE_EMP  =[("StackV","Stacked V"),("StackH","Stacked H"),("Tip","Tip Mounted")]
ZONE_FUSE =[("Nose","Nose"),("Aft","Aft"),("Side","Side"),("Dorsal","Dorsal"),("Ventral","Ventral")]
T1_SCOPE = ["Whole Aircraft Architecture","Architectural Subsystem Enabler","Component-Level Generic"]
T1_FIELD = ["Aerodynamic/Structural","Mechanical/Kinematic","Propulsion/Electrical","Control/Avionics","Other"]
T1_TARGET= ["Layout Convergence","Weight/Complexity Reduction","Aerodynamic Efficiency","Redundancy/Safety","Other"]
T1_REJECT= ["Pure UAV (No Passenger Intent)","Out of Technological Domain","Unreadable/Corrupt","Other"]
T2_PER   = ["Top","Bottom/Down","Front","Back","Side","Front-Isometric","Rear-Isometric","Generic 3D"]
T2_SYM   = ["Symmetric View","Asymmetric View"]
T2_ACST  = ["Line Drawing","Shaded Render","Solid/Filled Model","Schematic"]
T2_ACCOL = ["B/W (Monochrome)","Grayscale","Full Color"]
T2_BGST  = ["Solid Fill","Shaded/Gradient","Grid/Pattern"]
T2_BGCOL = ["White","Blueprint Blue","Dark","Grayscale"]
T2_PARTS = ["Whole Vehicle Layout","Primary Wing","Secondary/Canard Wing","Empennage/Tail",
            "Rotor/Propeller Blade","Tilt Hinge/Mechanism","Fuselage Cross-section",
            "Landing Gear/Skids","Internal Components/Batteries/Wiring"]

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def fresh_state() -> dict:
    s: dict[str, Any] = {
        "isApproved": None,
        "t1DisapproveReason": None,
        "t1DisapproveOther": "",
        "isDuplicate": False,
        "duplicateId": "",
        "archCount": 1,
        "t1Scope": None,
        "t1Field": None,
        "t1Target": None,
        "t2figNum": "1",
        "mainFigure": None,
        "figData": {},
        "t2customParts": [],
        "topType": None,
        "wingConf": None,
        "wCount": 1,
        "latSym": True,
        "longSym": False,
        "empType": None,
        "empKin": None,
        "empNotes": "",
        "fusShape": None,
        "fusKin": None,
        "fusNotes": "",
        "gearArch": None,
        "gearNotes": "",
        "footLen": 0.0,
        "footWid": 0.0,
        "footHgt": 0.0,
        "footAmbiguous": False,
        "wingNotes": "",
        "comments": "",
        "m3Comments": "",
    }
    for i in range(1, 5):
        s[f"wTilt{i}"] = None
        s[f"wPosV{i}"] = None
        s[f"wPosL{i}"] = None
        s[f"wPlan{i}"] = None
        s[f"wPlanOth{i}"] = ""
    for i in range(2, 5):
        s[f"wRole{i}"] = None
    return s


def build_label_token(S: dict) -> str:
    parts = []
    if S.get("t1Scope"):
        parts.append(S["t1Scope"].replace(" ", ""))
    tt = S.get("topType")
    if tt:
        parts.append(tt)
    wc = S.get("wingConf")
    if wc:
        if wc == "W":
            n = S.get("wCount", 1)
            parts.append(f"W×{n}")
            for i in range(1, n + 1):
                tilt = "T" if S.get(f"wTilt{i}") == "Tilt" else "F"
                posv = S.get(f"wPosV{i}") or ""
                posl = S.get(f"wPosL{i}") or ""
                plan = S.get(f"wPlan{i}") or ""
                role = S.get(f"wRole{i}") or "" if i > 1 else ""
                desc = f"W{i}:{tilt}-{posv}-{posl}-{plan}"
                if role:
                    desc = f"W{i}:{role}-{tilt}-{posv}-{posl}-{plan}"
                parts.append(desc)
        else:
            parts.append(wc)
    et = S.get("empType")
    if et:
        parts.append(et.split()[0])
    fs = S.get("fusShape")
    if fs:
        parts.append(f"FUS:{fs}")
    if S.get("latSym"):
        parts.append("LSYM")
    elif S.get("longSym"):
        parts.append("FSYM")
    # M3 count tokens
    for key in sorted(S.keys()):
        if key.startswith("m3_") and key.endswith("_count"):
            tag = key[3:-6].upper()
            val = S[key]
            if val and int(val) > 0:
                parts.append(f"{tag}{val}x")
    return "_".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Widget helpers
# ---------------------------------------------------------------------------

class _IntStepper:
    def __init__(self, label: str, value: int = 1, min_val: int = 1, max_val: int = 8,
                 on_change=None):
        self._min = min_val
        self._max = max_val
        self._value = max(min_val, min(max_val, value))
        self._on_change = on_change

        self._lbl = widgets.HTML(value=f"<b>{label}</b>&nbsp;")
        self._disp = widgets.HTML(value=f"<b>{self._value}</b>")
        self._btn_m = widgets.Button(description="-", layout=widgets.Layout(width="32px", height="32px"))
        self._btn_p = widgets.Button(description="+", layout=widgets.Layout(width="32px", height="32px"))
        self._btn_m.on_click(self._dec)
        self._btn_p.on_click(self._inc)
        self.widget = widgets.HBox([self._lbl, self._btn_m, self._disp, self._btn_p])

    def _dec(self, _):
        self.value = self._value - 1

    def _inc(self, _):
        self.value = self._value + 1

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, v: int):
        v = max(self._min, min(self._max, int(v)))
        self._value = v
        self._disp.value = f"<b>{v}</b>"
        if self._on_change:
            self._on_change(v)


def _tbgroup(options: list, value=None) -> widgets.ToggleButtons:
    opts = [(lbl, uid) for uid, lbl in options]
    return widgets.ToggleButtons(
        options=opts,
        value=value,
        style={"button_width": "auto"},
        layout=widgets.Layout(flex_wrap="wrap"),
    )


# ---------------------------------------------------------------------------
# Main UI class
# ---------------------------------------------------------------------------

class TaxonomyReviewUI:
    def __init__(self, df: pd.DataFrame, id_col: str = "patent_id",
                 save_col: str = "label_json", token_col: str = "label_token"):
        self._df = df.copy()
        self._id_col = id_col
        self._save_col = save_col
        self._token_col = token_col
        self._idx = 0
        self._loading = False
        self.S = fresh_state()
        self._m3_live: dict = {}
        self._build_ui()
        self._load_record(0)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        n = len(self._df)
        self._header = widgets.HTML()
        self._progress = widgets.IntProgress(min=0, max=max(1, n - 1), value=0,
                                              layout=widgets.Layout(width="100%"))

        # ---- Tab 0: T1 Meta ----
        self._t1_approve_btn = widgets.Button(description="Approve", button_style="",
                                               layout=widgets.Layout(width="120px"))
        self._t1_disapprove_btn = widgets.Button(description="Disapprove", button_style="",
                                                  layout=widgets.Layout(width="120px"))
        self._t1_approve_btn.on_click(lambda _: self._set_approval(True))
        self._t1_disapprove_btn.on_click(lambda _: self._set_approval(False))

        self._t1_approved_box = widgets.VBox([])
        self._t1_disapproved_box = widgets.VBox([])

        self._t1_scope = _tbgroup([(v, v) for v in T1_SCOPE])
        self._t1_field = widgets.Dropdown(options=[None] + T1_FIELD, value=None, description="Field:")
        self._t1_target = widgets.Dropdown(options=[None] + T1_TARGET, value=None, description="Target:")
        self._arch_stepper = _IntStepper("Architecture count:", 1, 1, 8)

        self._t1_reject_dd = widgets.Dropdown(options=[None] + T1_REJECT, value=None, description="Reason:")
        self._t1_reject_other = widgets.Textarea(placeholder="Specify other reason...",
                                                   layout=widgets.Layout(width="100%", height="60px"))

        self._t1_dup_chk = widgets.Checkbox(value=False, description="Is Duplicate")
        self._t1_dup_id = widgets.Text(placeholder="Duplicate patent ID",
                                        layout=widgets.Layout(width="200px"))
        self._t1_dup_id.layout.display = "none"

        def _dup_toggle(change):
            self._t1_dup_id.layout.display = "" if change["new"] else "none"
        self._t1_dup_chk.observe(_dup_toggle, names="value")

        self._comments = widgets.Textarea(description="Comments:",
                                           layout=widgets.Layout(width="100%", height="80px"))

        self._t1_approved_box.children = [
            widgets.Label("Scope:"), self._t1_scope,
            self._t1_field, self._t1_target,
            self._arch_stepper.widget,
        ]
        self._t1_disapproved_box.children = [
            self._t1_reject_dd,
            widgets.Label("Other:"), self._t1_reject_other,
        ]
        self._t1_approved_box.layout.display = "none"
        self._t1_disapproved_box.layout.display = "none"

        tab0 = widgets.VBox([
            widgets.HBox([self._t1_approve_btn, self._t1_disapprove_btn]),
            self._t1_approved_box,
            self._t1_disapproved_box,
            widgets.HBox([self._t1_dup_chk, self._t1_dup_id]),
            self._comments,
        ])

        # ---- Tab 1: T2 Image ----
        self._t2_fig_label = widgets.HTML(value="Figure 1")
        self._t2_fig_of = widgets.HTML(value="of ?")
        self._t2_prev = widgets.Button(description="◄", layout=widgets.Layout(width="40px"))
        self._t2_next = widgets.Button(description="►", layout=widgets.Layout(width="40px"))
        self._t2_approve_fig = widgets.Button(description="✓ Approve", button_style="success",
                                               layout=widgets.Layout(width="100px"))
        self._t2_reject_fig = widgets.Button(description="✗ Reject", button_style="danger",
                                              layout=widgets.Layout(width="100px"))
        self._t2_set_main = widgets.Button(description="★ Set Main", button_style="warning",
                                            layout=widgets.Layout(width="100px"))
        self._t2_reset_fig = widgets.Button(description="↺ Reset", layout=widgets.Layout(width="100px"))
        self._t2_status = widgets.HTML(value="")
        self._t2_arch_dd = widgets.Dropdown(options=[1], value=1, description="Arch #:")
        self._t2_arch_dd.layout.display = "none"
        self._t2_per = _tbgroup([(v, v) for v in T2_PER])
        self._t2_sym = _tbgroup([(v, v) for v in T2_SYM])
        self._t2_acst = _tbgroup([(v, v) for v in T2_ACST])
        self._t2_accol = _tbgroup([(v, v) for v in T2_ACCOL])
        self._t2_bgst = _tbgroup([(v, v) for v in T2_BGST])
        self._t2_bgcol = _tbgroup([(v, v) for v in T2_BGCOL])
        self._t2_parts_chks = {p: widgets.Checkbox(value=False, description=p,
                                                    layout=widgets.Layout(width="auto"))
                                for p in T2_PARTS}
        self._t2_custom_input = widgets.Text(placeholder="Custom tag",
                                              layout=widgets.Layout(width="200px"))
        self._t2_custom_add = widgets.Button(description="Add", layout=widgets.Layout(width="60px"))
        self._t2_custom_tags = widgets.HTML(value="")
        self._t2_custom_add.on_click(self._t2_add_custom)

        self._t2_prev.on_click(lambda _: self._t2_nav(-1))
        self._t2_next.on_click(lambda _: self._t2_nav(+1))
        self._t2_approve_fig.on_click(lambda _: self._t2_set_status("approved"))
        self._t2_reject_fig.on_click(lambda _: self._t2_set_status("rejected"))
        self._t2_set_main.on_click(lambda _: self._t2_mark_main())
        self._t2_reset_fig.on_click(lambda _: self._t2_reset_current())

        self._arch_stepper._on_change = self._on_arch_count_change

        tab1 = widgets.VBox([
            widgets.HBox([self._t2_prev, self._t2_fig_label, self._t2_next, self._t2_fig_of]),
            widgets.HBox([self._t2_approve_fig, self._t2_reject_fig, self._t2_set_main, self._t2_reset_fig]),
            self._t2_status,
            self._t2_arch_dd,
            widgets.Label("Perspective:"), self._t2_per,
            widgets.Label("Symmetry:"), self._t2_sym,
            widgets.Label("Art Style:"), self._t2_acst,
            widgets.Label("Art Color:"), self._t2_accol,
            widgets.Label("Background Style:"), self._t2_bgst,
            widgets.Label("Background Color:"), self._t2_bgcol,
            widgets.Label("Depicted Parts:"),
            widgets.GridBox(list(self._t2_parts_chks.values()),
                            layout=widgets.Layout(grid_template_columns="repeat(3, 1fr)")),
            widgets.HBox([self._t2_custom_input, self._t2_custom_add]),
            self._t2_custom_tags,
        ])

        # ---- Tab 2: G1 Arch ----
        self._g1_btns: dict[str, widgets.Button] = {}
        for uid, lbl in TOP:
            b = widgets.Button(description=lbl, layout=widgets.Layout(width="auto"))
            b.on_click(lambda _, u=uid: self._g1_select(u))
            self._g1_btns[uid] = b

        winged_box = widgets.VBox([
            widgets.HTML("<b>Winged</b>"),
            widgets.HBox([self._g1_btns[k] for k in ["TW","TP","DS","CVT","SLC","SRW"]]),
        ], layout=widgets.Layout(border="1px solid #ccc", padding="8px", margin="4px"))
        rotorborne_box = widgets.VBox([
            widgets.HTML("<b>Rotorborne</b>"),
            widgets.HBox([self._g1_btns[k] for k in ["RC","MR"]]),
        ], layout=widgets.Layout(border="1px solid #ccc", padding="8px", margin="4px"))
        others_box = widgets.VBox([
            widgets.HTML("<b>Others</b>"),
            widgets.HBox([self._g1_btns[k] for k in ["HB","PFV"]]),
        ], layout=widgets.Layout(border="1px solid #ccc", padding="8px", margin="4px"))
        self._g1_suppress_badge = widgets.HTML(
            '<div style="background:#f90;padding:4px 8px;border-radius:4px;color:#000">'
            'Rotorborne topology — wing section suppressed</div>')
        self._g1_suppress_badge.layout.display = "none"

        tab2 = widgets.VBox([winged_box, rotorborne_box, others_box, self._g1_suppress_badge])

        # ---- Tab 3: M1+M2 Struct ----
        self._wing_section = widgets.VBox([])
        self._wingConf = _tbgroup(WING_CONFIG)
        self._wingConf.observe(self._on_wing_conf, names="value")
        self._wCount_stepper = _IntStepper("Wing count:", 1, 1, 4,
                                            on_change=self._on_wcount_change)
        self._wing_cards: list[widgets.VBox] = []
        self._w_tilt: list = [None] * 5
        self._w_posv: list = [None] * 5
        self._w_posl: list = [None] * 5
        self._w_plan: list = [None] * 5
        self._w_planoth: list[widgets.Text] = [None] * 5  # type: ignore
        self._w_role: list = [None] * 5
        for i in range(1, 5):
            self._w_tilt[i] = _tbgroup(W_TILT)
            self._w_posv[i] = _tbgroup(W_POS_V)
            self._w_posl[i] = _tbgroup(W_POS_L)
            self._w_plan[i] = _tbgroup(W_PLAN)
            self._w_planoth[i] = widgets.Text(placeholder="Other plan...",
                                               layout=widgets.Layout(width="180px", display="none"))
            self._w_role[i] = _tbgroup(W_ROLE)

            def _plan_obs(change, idx=i):
                if not self._loading:
                    self._w_planoth[idx].layout.display = "" if change["new"] == "Oth" else "none"
            self._w_plan[i].observe(_plan_obs, names="value")

        self._latSym = widgets.Checkbox(value=True, description="Lateral Symmetry")
        self._longSym = widgets.Checkbox(value=False, description="Longitudinal Symmetry")
        self._wingNotes = widgets.Textarea(description="Wing notes:",
                                            layout=widgets.Layout(width="100%", height="60px"))

        self._empType = _tbgroup(EMP_TYPE)
        self._empType.observe(self._on_emp_type, names="value")
        self._empKin = _tbgroup(EMP_KIN)
        self._empNotes = widgets.Textarea(description="Emp notes:",
                                           layout=widgets.Layout(width="100%", height="60px"))
        self._empKin_box = widgets.VBox([widgets.Label("Emp kinematics:"), self._empKin])

        self._fusShape = _tbgroup(FUS_SHAPE)
        self._fusKin = _tbgroup(FUS_KIN)
        self._fusNotes = widgets.Textarea(description="Fus notes:",
                                           layout=widgets.Layout(width="100%", height="60px"))

        self._gearArch = _tbgroup(GEAR_ARCH)
        self._gearNotes = widgets.Textarea(description="Gear notes:",
                                            layout=widgets.Layout(width="100%", height="60px"))

        self._footLen = widgets.BoundedFloatText(value=0, min=0, max=999, description="Length (m):")
        self._footWid = widgets.BoundedFloatText(value=0, min=0, max=999, description="Width (m):")
        self._footHgt = widgets.BoundedFloatText(value=0, min=0, max=999, description="Height (m):")
        self._footAmb = widgets.Checkbox(value=False, description="Footprint Ambiguous")

        tab3 = widgets.VBox([
            widgets.HTML("<b>Wing Configuration</b>"),
            self._wing_section,
            widgets.HTML("<hr><b>Empennage</b>"),
            widgets.Label("Type:"), self._empType,
            self._empKin_box,
            self._empNotes,
            widgets.HTML("<hr><b>Fuselage</b>"),
            widgets.Label("Shape:"), self._fusShape,
            widgets.Label("Kinematics:"), self._fusKin,
            self._fusNotes,
            widgets.HTML("<hr><b>Landing Gear</b>"),
            widgets.Label("Architecture:"), self._gearArch,
            self._gearNotes,
            widgets.HTML("<hr><b>Footprint</b>"),
            widgets.HBox([self._footLen, self._footWid, self._footHgt]),
            self._footAmb,
        ])

        # ---- Tab 4: M3 Prop ----
        self._dep_html = widgets.HTML(value="")
        self._m3_out = widgets.Output()
        self._m3Comments = widgets.Textarea(description="M3 notes:",
                                             layout=widgets.Layout(width="100%", height="60px"))
        tab4 = widgets.VBox([self._dep_html, self._m3_out, self._m3Comments])

        # ---- Tab 5: Summary ----
        self._sum_token = widgets.HTML(value="")
        self._sum_json = widgets.Textarea(layout=widgets.Layout(width="100%", height="200px"))
        self._sum_warnings = widgets.HTML(value="")
        self._btn_save_next = widgets.Button(description="Save & Next", button_style="primary",
                                              layout=widgets.Layout(width="150px"))
        self._btn_save_stay = widgets.Button(description="Save (Stay)", button_style="info",
                                              layout=widgets.Layout(width="150px"))
        self._btn_save_next.on_click(self._on_save_next)
        self._btn_save_stay.on_click(self._on_save_stay)

        tab5 = widgets.VBox([
            self._sum_token,
            self._sum_json,
            self._sum_warnings,
            widgets.HBox([self._btn_save_next, self._btn_save_stay]),
        ])

        # ---- Tab container ----
        self._tabs = widgets.Tab(children=[tab0, tab1, tab2, tab3, tab4, tab5])
        for i, title in enumerate(["T1 Meta","T2 Image","G1 Arch","M1+M2 Struct","M3 Prop","Summary"]):
            self._tabs.set_title(i, title)

        self._tabs.observe(self._on_tab_change, names="selected_index")

        self._root = widgets.VBox([self._header, self._progress, self._tabs])

    # ------------------------------------------------------------------
    # Figure management (T2)
    # ------------------------------------------------------------------

    def _t2_fig_count(self) -> int:
        row = self._df.iloc[self._idx]
        try:
            d = json.loads(row[self._save_col])
            figs = d.get("figData", {})
            if figs:
                return max(int(k) for k in figs.keys())
        except Exception:
            pass
        return int(self.S.get("t2figNum", "1") or "1")

    def _t2_current_fnum(self) -> str:
        return self.S.get("t2figNum", "1") or "1"

    def _t2_save_fig(self):
        fnum = self._t2_current_fnum()
        fd = {
            "status": self.S["figData"].get(fnum, {}).get("status", "unset"),
            "arch": self._t2_arch_dd.value,
            "per": self._t2_per.value,
            "sym": self._t2_sym.value,
            "acst": self._t2_acst.value,
            "accol": self._t2_accol.value,
            "bgst": self._t2_bgst.value,
            "bgcol": self._t2_bgcol.value,
            "parts": [p for p, chk in self._t2_parts_chks.items() if chk.value],
            "customParts": self.S.get("t2customParts", []),
        }
        self.S["figData"][fnum] = fd

    def _t2_load_fig(self, fnum: str):
        fd = self.S["figData"].get(fnum, {})
        self._loading = True
        try:
            self._t2_per.value = fd.get("per")
            self._t2_sym.value = fd.get("sym")
            self._t2_acst.value = fd.get("acst")
            self._t2_accol.value = fd.get("accol")
            self._t2_bgst.value = fd.get("bgst")
            self._t2_bgcol.value = fd.get("bgcol")
            parts = fd.get("parts", [])
            for p, chk in self._t2_parts_chks.items():
                chk.value = p in parts
            self._t2_status.value = self._fig_status_html(fd.get("status", "unset"))
        finally:
            self._loading = False

    def _fig_status_html(self, status: str) -> str:
        colors = {"approved": "green", "rejected": "red", "unset": "gray"}
        c = colors.get(status, "gray")
        return f'<span style="color:{c};font-weight:bold">{status.upper()}</span>'

    def _t2_nav(self, delta: int):
        self._t2_save_fig()
        total = self._t2_fig_count()
        cur = int(self._t2_current_fnum())
        new = max(1, min(total, cur + delta))
        self.S["t2figNum"] = str(new)
        self._t2_fig_label.value = f"Figure {new}"
        self._t2_fig_of.value = f"of {total}"
        self._t2_load_fig(str(new))

    def _t2_set_status(self, status: str):
        fnum = self._t2_current_fnum()
        fd = self.S["figData"].get(fnum, {})
        fd["status"] = status
        self.S["figData"][fnum] = fd
        self._t2_status.value = self._fig_status_html(status)

    def _t2_mark_main(self):
        self.S["mainFigure"] = self._t2_current_fnum()
        self._t2_status.value += ' <span style="color:gold">&#9733; MAIN</span>'

    def _t2_reset_current(self):
        fnum = self._t2_current_fnum()
        self.S["figData"][fnum] = {}
        self._t2_load_fig(fnum)

    def _t2_add_custom(self, _):
        tag = self._t2_custom_input.value.strip()
        if tag and tag not in self.S.get("t2customParts", []):
            self.S.setdefault("t2customParts", []).append(tag)
            self._t2_custom_input.value = ""
            self._refresh_custom_tags()

    def _refresh_custom_tags(self):
        tags = self.S.get("t2customParts", [])
        self._t2_custom_tags.value = " ".join(
            f'<span style="background:#ddd;padding:2px 6px;border-radius:3px">{t}</span>'
            for t in tags)

    def _on_arch_count_change(self, val: int):
        if self._loading:
            return
        self.S["archCount"] = val
        opts = list(range(1, val + 1))
        self._t2_arch_dd.options = opts
        self._t2_arch_dd.layout.display = "none" if val == 1 else ""

    # ------------------------------------------------------------------
    # G1 topology
    # ------------------------------------------------------------------

    def _g1_select(self, uid: str):
        self.S["topType"] = uid
        for k, b in self._g1_btns.items():
            b.button_style = "success" if k == uid else ""
        self._apply_physics_locks(uid)
        self._update_wing_section_visibility()
        self._render_m3()

    def _apply_physics_locks(self, tt: str):
        self._loading = True
        try:
            if tt == "TW":
                if self._w_tilt[1] is not None:
                    self._w_tilt[1].value = "Tilt"
                    self._w_tilt[1].disabled = True
            elif tt == "TP":
                for i in range(1, 5):
                    if self._w_tilt[i] is not None:
                        self._w_tilt[i].value = "Fixed"
                        self._w_tilt[i].disabled = True
            else:
                for i in range(1, 5):
                    if self._w_tilt[i] is not None:
                        self._w_tilt[i].disabled = False
            if tt == "TW":
                if self._empKin is not None:
                    self._empKin.value = "Fixed"
                    self._empKin.disabled = True
            else:
                if self._empKin is not None:
                    self._empKin.disabled = False
        finally:
            self._loading = False

    def _update_wing_section_visibility(self):
        tt = self.S.get("topType")
        if tt in ROTORBORNE:
            self._wing_section.children = []
            self._g1_suppress_badge.layout.display = ""
        elif tt in WINGED:
            self._g1_suppress_badge.layout.display = "none"
            self._rebuild_wing_section()
        else:
            self._g1_suppress_badge.layout.display = "none"
            self._wing_section.children = []

    def _rebuild_wing_section(self):
        n = self._wCount_stepper.value
        cards = []
        for i in range(1, n + 1):
            items = [widgets.HTML(f"<b>Wing {i}</b>")]
            if i > 1 and self._w_role[i] is not None:
                items.append(widgets.Label("Role:"))
                items.append(self._w_role[i])
            items.append(widgets.Label("Tilt:"))
            items.append(self._w_tilt[i])
            items.append(widgets.Label("Vertical pos:"))
            items.append(self._w_posv[i])
            items.append(widgets.Label("Longitudinal pos:"))
            items.append(self._w_posl[i])
            items.append(widgets.Label("Planform:"))
            items.append(self._w_plan[i])
            items.append(self._w_planoth[i])
            card = widgets.VBox(items, layout=widgets.Layout(border="1px solid #aaa",
                                                              padding="6px", margin="4px"))
            cards.append(card)
        self._wing_section.children = [
            widgets.Label("Configuration:"), self._wingConf,
            self._wCount_stepper.widget,
            widgets.HBox(cards),
            widgets.HBox([self._latSym, self._longSym]),
            self._wingNotes,
        ]

    def _on_wing_conf(self, change):
        if self._loading:
            return
        self.S["wingConf"] = change["new"]
        wc = change["new"]
        self._wCount_stepper.widget.layout.display = "" if wc == "W" else "none"
        self._render_m3()

    def _on_wcount_change(self, val: int):
        if self._loading:
            return
        self.S["wCount"] = val
        self._rebuild_wing_section()
        self._render_m3()

    def _on_emp_type(self, change):
        if self._loading:
            return
        et = change["new"]
        self.S["empType"] = et
        no_kin = et in (None, "Tailless", "Fins")
        self._empKin_box.layout.display = "none" if no_kin else ""
        self._render_m3()

    # ------------------------------------------------------------------
    # M3 propulsion cards
    # ------------------------------------------------------------------

    def _render_m3(self):
        tt = self.S.get("topType")
        wc = self.S.get("wingConf")
        n_wings = self._wCount_stepper.value
        et = self.S.get("empType")
        is_dep = tt in WINGED
        self._dep_html.value = (
            '<span style="background:#4a90d9;color:#fff;padding:2px 8px;border-radius:4px">DEP</span>'
            if is_dep else "")

        blueprints = []
        if tt == "RC":
            blueprints.append(("core_layout/rc", "rc", False))
        elif tt == "MR":
            blueprints.append(("core_layout/mr", "mr", False))
        elif tt in WINGED and wc == "W":
            for i in range(1, n_wings + 1):
                blueprints.append((f"wing/{i}", "wing", tt == "TW"))
        blueprints.append(("core_layout/fuselage", "fuselage", False))
        if et and et not in ("Tailless", "Fins", None):
            blueprints.append(("core_layout/emp", "emp", False))

        with self._m3_out:
            from IPython.display import clear_output
            clear_output(wait=True)
            cards_ui = []
            for key, mode, is_tw in blueprints:
                card = self._build_m3_card(key, mode, is_tw)
                cards_ui.append(card)
            ipy_display(widgets.VBox(cards_ui))

    def _build_m3_card(self, key: str, mode: str, is_tw: bool) -> widgets.VBox:
        live = self._m3_live
        prev = {k.split(f"m3_{key}_")[1]: v
                for k, v in self.S.items()
                if k.startswith(f"m3_{key}_")}

        def _get_or_create(suffix, constructor):
            full = f"m3_{key}_{suffix}"
            if full not in live:
                live[full] = constructor()
            return live[full]

        title_map = {"rc": "Rotorcraft Core", "mr": "Multirotor Core",
                     "fuselage": "Fuselage", "emp": "Empennage"}
        if mode == "wing":
            idx = key.split("/")[-1]
            title = f"Wing {idx} Propulsors"
        else:
            title = title_map.get(mode, key)

        count_w = _IntStepper("Count:", int(prev.get("count", 1)), 1, 32)
        live[f"m3_{key}_count"] = count_w

        sym_w = _get_or_create("sym", lambda: widgets.Checkbox(value=bool(prev.get("sym", True)),
                                                                description="Symmetric"))
        bmech_w = _get_or_create("bmech", lambda: _tbgroup(BLADE_MECH))
        if "bmech" in prev:
            bmech_w.value = prev["bmech"]

        items = [widgets.HTML(f"<b>{title}</b>"), count_w.widget, sym_w,
                 widgets.Label("Blade mech:"), bmech_w]

        is_simple = mode in ("rc", "mr")
        if not is_simple:
            chord_w = _get_or_create("chord", lambda: _tbgroup(CHORD))
            if "chord" in prev:
                chord_w.value = prev["chord"]

            orient_key = f"m3_{key}_orient"
            if is_tw and mode == "wing":
                orient_disp = widgets.HTML(
                    '<span style="color:gray">Orient: Fixed Horizontal (locked)</span>')
                live[orient_key] = "FixedHorizontal"
                orient_w = orient_disp
            else:
                orient_w = _get_or_create("orient", lambda: _tbgroup(
                    [("FixedH","Fixed Horizontal"),("FixedV","Fixed Vertical"),("Tiltable","Tiltable")]))
                if "orient" in prev:
                    orient_w.value = prev["orient"]

            retract_w = _get_or_create("retract", lambda: _tbgroup(RETRACT))
            if "retract" in prev:
                retract_w.value = prev["retract"]

            items += [widgets.Label("Chord position:"), chord_w,
                      widgets.Label("Orientation:"), orient_w,
                      widgets.Label("Retract:"), retract_w]

            if mode == "wing":
                zone_chord_w = _get_or_create("zoneChord", lambda: _tbgroup(ZONE_CHORD))
                zone_span_w = _get_or_create("zoneSpan", lambda: _tbgroup(ZONE_SPAN))
                if "zoneChord" in prev:
                    zone_chord_w.value = prev["zoneChord"]
                if "zoneSpan" in prev:
                    zone_span_w.value = prev["zoneSpan"]
                items += [widgets.Label("Zone (chord):"), zone_chord_w,
                          widgets.Label("Zone (span):"), zone_span_w]
            elif mode == "emp":
                zone_w = _get_or_create("zone", lambda: _tbgroup(ZONE_EMP))
                if "zone" in prev:
                    zone_w.value = prev["zone"]
                items += [widgets.Label("Zone:"), zone_w]
            else:
                zone_w = _get_or_create("zone", lambda: _tbgroup(ZONE_FUSE))
                if "zone" in prev:
                    zone_w.value = prev["zone"]
                items += [widgets.Label("Zone:"), zone_w]

        notes_w = _get_or_create("notes", lambda: widgets.Textarea(
            value=prev.get("notes", ""),
            placeholder="Notes...",
            layout=widgets.Layout(width="100%", height="50px")))

        items.append(notes_w)
        return widgets.VBox(items, layout=widgets.Layout(border="1px solid #bbb",
                                                          padding="6px", margin="4px"))

    # ------------------------------------------------------------------
    # State sync
    # ------------------------------------------------------------------

    def _sync_widgets_to_state(self):
        self._t2_save_fig()
        S = self.S
        S["isApproved"] = self._approval_state()
        S["t1DisapproveReason"] = self._t1_reject_dd.value
        S["t1DisapproveOther"] = self._t1_reject_other.value
        S["isDuplicate"] = self._t1_dup_chk.value
        S["duplicateId"] = self._t1_dup_id.value
        S["archCount"] = self._arch_stepper.value
        S["t1Scope"] = self._t1_scope.value
        S["t1Field"] = self._t1_field.value
        S["t1Target"] = self._t1_target.value
        S["comments"] = self._comments.value
        S["topType"] = next((uid for uid, b in self._g1_btns.items() if b.button_style == "success"), None)
        S["wingConf"] = self._wingConf.value
        S["wCount"] = self._wCount_stepper.value
        S["latSym"] = self._latSym.value
        S["longSym"] = self._longSym.value
        S["empType"] = self._empType.value
        S["empKin"] = self._empKin.value
        S["empNotes"] = self._empNotes.value
        S["fusShape"] = self._fusShape.value
        S["fusKin"] = self._fusKin.value
        S["fusNotes"] = self._fusNotes.value
        S["gearArch"] = self._gearArch.value
        S["gearNotes"] = self._gearNotes.value
        S["footLen"] = self._footLen.value
        S["footWid"] = self._footWid.value
        S["footHgt"] = self._footHgt.value
        S["footAmbiguous"] = self._footAmb.value
        S["wingNotes"] = self._wingNotes.value
        S["m3Comments"] = self._m3Comments.value
        for i in range(1, 5):
            S[f"wTilt{i}"] = self._w_tilt[i].value if self._w_tilt[i] else None
            S[f"wPosV{i}"] = self._w_posv[i].value if self._w_posv[i] else None
            S[f"wPosL{i}"] = self._w_posl[i].value if self._w_posl[i] else None
            S[f"wPlan{i}"] = self._w_plan[i].value if self._w_plan[i] else None
            S[f"wPlanOth{i}"] = self._w_planoth[i].value if self._w_planoth[i] else ""
        for i in range(2, 5):
            S[f"wRole{i}"] = self._w_role[i].value if self._w_role[i] else None
        # M3 live widgets
        for full_key, widget_ref in self._m3_live.items():
            if isinstance(widget_ref, _IntStepper):
                S[full_key] = widget_ref.value
            elif isinstance(widget_ref, (widgets.ToggleButtons, widgets.Dropdown)):
                S[full_key] = widget_ref.value
            elif isinstance(widget_ref, widgets.Checkbox):
                S[full_key] = widget_ref.value
            elif isinstance(widget_ref, widgets.Textarea):
                S[full_key] = widget_ref.value
            elif isinstance(widget_ref, str):
                S[full_key] = widget_ref

    def _push_state_to_widgets(self):
        self._loading = True
        S = self.S
        try:
            approved = S.get("isApproved")
            self._refresh_approval_buttons(approved)
            if approved is True:
                self._t1_approved_box.layout.display = ""
                self._t1_disapproved_box.layout.display = "none"
            elif approved is False:
                self._t1_approved_box.layout.display = "none"
                self._t1_disapproved_box.layout.display = ""
            else:
                self._t1_approved_box.layout.display = "none"
                self._t1_disapproved_box.layout.display = "none"
            self._t1_reject_dd.value = S.get("t1DisapproveReason")
            self._t1_reject_other.value = S.get("t1DisapproveOther", "")
            self._t1_dup_chk.value = S.get("isDuplicate", False)
            self._t1_dup_id.value = S.get("duplicateId", "")
            self._t1_dup_id.layout.display = "" if S.get("isDuplicate") else "none"
            self._arch_stepper.value = S.get("archCount", 1)
            self._t1_scope.value = S.get("t1Scope")
            self._t1_field.value = S.get("t1Field")
            self._t1_target.value = S.get("t1Target")
            self._comments.value = S.get("comments", "")
            # G1
            tt = S.get("topType")
            for uid, b in self._g1_btns.items():
                b.button_style = "success" if uid == tt else ""
            self._update_wing_section_visibility()
            # M1+M2
            self._wingConf.value = S.get("wingConf")
            self._wCount_stepper.value = S.get("wCount", 1)
            self._latSym.value = S.get("latSym", True)
            self._longSym.value = S.get("longSym", False)
            for i in range(1, 5):
                if self._w_tilt[i]:
                    self._w_tilt[i].value = S.get(f"wTilt{i}")
                if self._w_posv[i]:
                    self._w_posv[i].value = S.get(f"wPosV{i}")
                if self._w_posl[i]:
                    self._w_posl[i].value = S.get(f"wPosL{i}")
                if self._w_plan[i]:
                    self._w_plan[i].value = S.get(f"wPlan{i}")
                    p_oth = S.get(f"wPlanOth{i}", "")
                    self._w_planoth[i].value = p_oth
                    self._w_planoth[i].layout.display = "" if S.get(f"wPlan{i}") == "Oth" else "none"
            for i in range(2, 5):
                if self._w_role[i]:
                    self._w_role[i].value = S.get(f"wRole{i}")
            self._empType.value = S.get("empType")
            et = S.get("empType")
            self._empKin_box.layout.display = "none" if et in (None, "Tailless", "Fins") else ""
            self._empKin.value = S.get("empKin")
            self._empNotes.value = S.get("empNotes", "")
            self._fusShape.value = S.get("fusShape")
            self._fusKin.value = S.get("fusKin")
            self._fusNotes.value = S.get("fusNotes", "")
            self._gearArch.value = S.get("gearArch")
            self._gearNotes.value = S.get("gearNotes", "")
            self._footLen.value = S.get("footLen", 0.0)
            self._footWid.value = S.get("footWid", 0.0)
            self._footHgt.value = S.get("footHgt", 0.0)
            self._footAmb.value = S.get("footAmbiguous", False)
            self._wingNotes.value = S.get("wingNotes", "")
            self._m3Comments.value = S.get("m3Comments", "")
            # T2
            fnum = S.get("t2figNum", "1")
            total = max(1, len(S.get("figData", {})) or 1)
            self._t2_fig_label.value = f"Figure {fnum}"
            self._t2_fig_of.value = f"of {total}"
            self._t2_load_fig(fnum)
            self._refresh_custom_tags()
        finally:
            self._loading = False

    def _restore_from_export(self, saved: dict):
        self.S = fresh_state()
        S = self.S
        S["isApproved"] = saved.get("isApproved")
        S["t1DisapproveReason"] = saved.get("t1DisapproveReason")
        S["t1DisapproveOther"] = saved.get("t1DisapproveOther", "")
        S["isDuplicate"] = saved.get("isDuplicate", False)
        S["duplicateId"] = saved.get("duplicateId", "")
        S["archCount"] = saved.get("archCount", 1)
        S["t1Scope"] = saved.get("t1Scope")
        S["t1Field"] = saved.get("t1Field")
        S["t1Target"] = saved.get("t1Target")
        S["comments"] = saved.get("comments", "")
        S["t2figNum"] = str(saved.get("t2figNum", "1"))
        S["mainFigure"] = saved.get("mainFigure")
        S["figData"] = {str(k): v for k, v in saved.get("figData", {}).items()}
        S["t2customParts"] = saved.get("t2customParts", [])
        S["topType"] = saved.get("topologyClass")
        S["wingConf"] = saved.get("wingConf")
        S["wCount"] = saved.get("wCount", 1)
        S["latSym"] = saved.get("latSym", True)
        S["longSym"] = saved.get("longSym", False)
        wings = saved.get("wings", [])
        for i, w in enumerate(wings[:4], start=1):
            S[f"wTilt{i}"] = w.get("tilt")
            S[f"wPosV{i}"] = w.get("posV")
            S[f"wPosL{i}"] = w.get("posL")
            S[f"wPlan{i}"] = w.get("plan")
            S[f"wPlanOth{i}"] = w.get("planOth", "")
            if i > 1:
                S[f"wRole{i}"] = w.get("role")
        S["empType"] = saved.get("empType")
        S["empKin"] = saved.get("empKin")
        S["empNotes"] = saved.get("empNotes", "")
        S["fusShape"] = saved.get("fusShape")
        S["fusKin"] = saved.get("fusKin")
        S["fusNotes"] = saved.get("fusNotes", "")
        S["gearArch"] = saved.get("gearArch")
        S["gearNotes"] = saved.get("gearNotes", "")
        S["footLen"] = saved.get("footLen", 0.0)
        S["footWid"] = saved.get("footWid", 0.0)
        S["footHgt"] = saved.get("footHgt", 0.0)
        S["footAmbiguous"] = saved.get("footAmbiguous", False)
        S["wingNotes"] = saved.get("wingNotes", "")
        S["m3Comments"] = saved.get("m3Comments", "")
        for card in saved.get("propulsionCards", []):
            key = card.get("key", "")
            for field in ("count","sym","chord","orient","bmech","retract","zone",
                          "zoneChord","zoneSpan","notes"):
                if field in card:
                    S[f"m3_{key}_{field}"] = card[field]

    def _build_export_dict(self) -> dict:
        S = self.S
        wings = []
        for i in range(1, S.get("wCount", 1) + 1):
            w = {
                "tilt": S.get(f"wTilt{i}"),
                "posV": S.get(f"wPosV{i}"),
                "posL": S.get(f"wPosL{i}"),
                "plan": S.get(f"wPlan{i}"),
                "planOth": S.get(f"wPlanOth{i}", ""),
            }
            if i > 1:
                w["role"] = S.get(f"wRole{i}")
            wings.append(w)
        # build propulsion cards list
        seen_keys: list[str] = []
        for k in S:
            if k.startswith("m3_") and "_" in k[3:]:
                parts = k[3:].split("_", 1)
                card_key = parts[0] + "_" + parts[1].split("_")[0] if "/" not in parts[0] else \
                    k[3:].rsplit("_", 1)[0]
                # Use full key prefix up to last underscore
                prefix = k.rsplit("_", 1)[0][3:]
                if prefix not in seen_keys:
                    seen_keys.append(prefix)
        prop_cards = []
        for prefix in seen_keys:
            card: dict[str, Any] = {"key": prefix}
            for field in ("count","sym","chord","orient","bmech","retract","zone",
                          "zoneChord","zoneSpan","notes"):
                fk = f"m3_{prefix}_{field}"
                if fk in S:
                    val = S[fk]
                    if isinstance(val, _IntStepper):
                        val = val.value
                    card[field] = val
            prop_cards.append(card)
        token = build_label_token(S)
        return {
            "recordId": self._df.iloc[self._idx][self._id_col],
            "labelTimestamp": datetime.now(timezone.utc).isoformat(),
            "isApproved": S.get("isApproved"),
            "t1DisapproveReason": S.get("t1DisapproveReason"),
            "t1DisapproveOther": S.get("t1DisapproveOther", ""),
            "isDuplicate": S.get("isDuplicate", False),
            "duplicateId": S.get("duplicateId", ""),
            "archCount": S.get("archCount", 1),
            "t1Scope": S.get("t1Scope"),
            "t1Field": S.get("t1Field"),
            "t1Target": S.get("t1Target"),
            "comments": S.get("comments", ""),
            "t2figNum": S.get("t2figNum", "1"),
            "mainFigure": S.get("mainFigure"),
            "figData": S.get("figData", {}),
            "t2customParts": S.get("t2customParts", []),
            "topologyClass": S.get("topType"),
            "wingConf": S.get("wingConf"),
            "wCount": S.get("wCount", 1),
            "wings": wings,
            "latSym": S.get("latSym", True),
            "longSym": S.get("longSym", False),
            "empType": S.get("empType"),
            "empKin": S.get("empKin"),
            "empNotes": S.get("empNotes", ""),
            "fusShape": S.get("fusShape"),
            "fusKin": S.get("fusKin"),
            "fusNotes": S.get("fusNotes", ""),
            "gearArch": S.get("gearArch"),
            "gearNotes": S.get("gearNotes", ""),
            "footLen": S.get("footLen", 0.0),
            "footWid": S.get("footWid", 0.0),
            "footHgt": S.get("footHgt", 0.0),
            "footAmbiguous": S.get("footAmbiguous", False),
            "wingNotes": S.get("wingNotes", ""),
            "m3Comments": S.get("m3Comments", ""),
            "propulsionCards": prop_cards,
            "labelToken": token,
        }

    def _do_save(self):
        self._sync_widgets_to_state()
        export = self._build_export_dict()
        token = export["labelToken"]
        self._df.at[self._idx, self._save_col] = json.dumps(export)
        self._df.at[self._idx, self._token_col] = token

    def _load_record(self, idx: int):
        self._idx = idx
        row = self._df.iloc[idx]
        pid = row[self._id_col]
        n = len(self._df)
        self._header.value = (
            f'<h3>Patent: <code>{pid}</code> &nbsp; '
            f'<span style="color:gray">{idx + 1} / {n}</span></h3>')
        self._progress.value = idx
        raw = row.get(self._save_col, "")
        if isinstance(raw, str) and raw.strip().startswith("{"):
            try:
                saved = json.loads(raw)
                self._restore_from_export(saved)
            except Exception:
                self.S = fresh_state()
        else:
            self.S = fresh_state()
        self._m3_live = {}
        self._push_state_to_widgets()
        tt = self.S.get("topType")
        if tt:
            self._apply_physics_locks(tt)
        self._render_m3()

    def go_to(self, idx: int):
        self._do_save()
        idx = max(0, min(len(self._df) - 1, idx))
        self._load_record(idx)

    # ------------------------------------------------------------------
    # Approval helpers
    # ------------------------------------------------------------------

    def _approval_state(self):
        a = self._t1_approve_btn.button_style == "success"
        d = self._t1_disapprove_btn.button_style == "danger"
        if a:
            return True
        if d:
            return False
        return None

    def _refresh_approval_buttons(self, state):
        if state is True:
            self._t1_approve_btn.button_style = "success"
            self._t1_disapprove_btn.button_style = ""
        elif state is False:
            self._t1_approve_btn.button_style = ""
            self._t1_disapprove_btn.button_style = "danger"
        else:
            self._t1_approve_btn.button_style = ""
            self._t1_disapprove_btn.button_style = ""

    def _set_approval(self, approved: bool):
        self.S["isApproved"] = approved
        self._refresh_approval_buttons(approved)
        if approved:
            self._t1_approved_box.layout.display = ""
            self._t1_disapproved_box.layout.display = "none"
        else:
            self._t1_approved_box.layout.display = "none"
            self._t1_disapproved_box.layout.display = ""

    # ------------------------------------------------------------------
    # Summary tab
    # ------------------------------------------------------------------

    def _on_tab_change(self, change):
        if change["new"] == 5:
            self._refresh_summary()

    def _refresh_summary(self):
        self._sync_widgets_to_state()
        export = self._build_export_dict()
        token = export["labelToken"]
        self._sum_token.value = (
            f'<div style="background:#222;color:#0f0;font-family:monospace;'
            f'padding:6px 10px;border-radius:4px;word-break:break-all">{token}</div>')
        self._sum_json.value = json.dumps(export, indent=2)
        warnings = self._validate()
        if warnings:
            html = '<ul style="color:red">' + "".join(f"<li>{w}</li>" for w in warnings) + "</ul>"
        else:
            html = '<span style="color:green">&#10003; No validation issues</span>'
        self._sum_warnings.value = html

    def _validate(self) -> list[str]:
        S = self.S
        w = []
        if S.get("isApproved") is None:
            w.append("Approval not set")
        if S.get("isApproved") is True:
            if not S.get("t1Scope"):
                w.append("T1 Scope not set")
            if not S.get("t1Field"):
                w.append("T1 Field not set")
        if not S.get("topType"):
            w.append("Topology not selected")
        tt = S.get("topType")
        if tt in WINGED and not S.get("wingConf"):
            w.append("Wing configuration not set")
        if not S.get("empType"):
            w.append("Empennage type not set")
        if not S.get("fusShape"):
            w.append("Fuselage shape not set")
        if not S.get("gearArch"):
            w.append("Landing gear not set")
        fig_data = S.get("figData", {})
        approved_figs = [f for f, d in fig_data.items() if d.get("status") == "approved"]
        if not approved_figs:
            w.append("No approved figures")
        if not S.get("mainFigure"):
            w.append("Main figure not set")
        return w

    # ------------------------------------------------------------------
    # Save / navigation buttons
    # ------------------------------------------------------------------

    def _on_save_next(self, _):
        self._do_save()
        next_idx = self._idx + 1
        if next_idx < len(self._df):
            self._load_record(next_idx)

    def _on_save_stay(self, _):
        self._do_save()
        self._refresh_summary()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def display(self):
        ipy_display(self._root)

    @property
    def labeled_df(self) -> pd.DataFrame:
        self._do_save()
        return self._df.copy()
