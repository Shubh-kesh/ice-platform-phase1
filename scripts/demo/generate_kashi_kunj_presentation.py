#!/usr/bin/env python3
"""
Generate docs/demo/KASHI_KUNJ_STAKEHOLDER_PRESENTATION.pptx — the Sparkbuild
client deck, from the same content as KASHI_KUNJ_STAKEHOLDER_PRESENTATION.md.

Run (from the repo root) with a throwaway venv so python-pptx never enters the
backend/frontend dependency sets:

    python3 -m venv /tmp/demo-pptx-venv
    /tmp/demo-pptx-venv/bin/pip install -r scripts/demo/requirements.txt
    /tmp/demo-pptx-venv/bin/python scripts/demo/generate_kashi_kunj_presentation.py

Output: docs/demo/KASHI_KUNJ_STAKEHOLDER_PRESENTATION.pptx
"""
from __future__ import annotations

import os
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Emu, Pt

REPO_ROOT = Path(__file__).resolve().parents[2]
LOGO = REPO_ROOT / "docs" / "demo" / "assets" / "sparkbuild-logo.png"
OUT = REPO_ROOT / "docs" / "demo" / "KASHI_KUNJ_STAKEHOLDER_PRESENTATION.pptx"

NAVY = RGBColor(0x0F, 0x2A, 0x43)
BLUE = RGBColor(0x1A, 0x7E, 0xFB)
YELLOW = RGBColor(0xFF, 0xF2, 0x00)
ORANGE = RGBColor(0xFF, 0x69, 0x00)
GRAY_BG = RGBColor(0xF6, 0xF7, 0xF7)
DARK = RGBColor(0x1F, 0x29, 0x37)
MUTED = RGBColor(0x5B, 0x6B, 0x7B)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

SLIDE_W = Emu(12192000)  # 13.333in
SLIDE_H = Emu(6858000)   # 7.5in

SLIDES = [
    # (title, subtitle, [bullet points], notes)
    (
        "Smarter Construction Management",
        "Sparkbuild Construction  ·  Kashi Kunj, Jabalpur  ·  Live demonstration",
        [
            "One platform to run every project",
            "Schedule · Site · Materials · Money · Communication",
        ],
        "Good morning. We are Sparkbuild, and this is how we will run our projects - every schedule, every site, every rupee and every conversation, in one place. Everything shown here is live, on a real project called Kashi Kunj in Jabalpur.",
    ),
    (
        "The way construction usually works",
        "Sound familiar?",
        [
            "Plans live in spreadsheets, progress lives in someone's head",
            "Material shortages surface on the morning they're needed",
            "Site photos travel by WhatsApp, costs are reconciled weeks later",
            "The owner hears about delays after they happen",
            "Result: lots of firefighting, very little control",
        ],
        "Be honest: how much of today's project status lives in spreadsheets and in people's heads? How often do you discover a material shortage the morning it's needed? That is the world we all know. Pause, let them nod, keep it short.",
    ),
    (
        "The way it should work",
        "One dashboard for the whole company and every site",
        [
            "Every project's health at a glance - green, amber, red",
            "One source of truth for schedule, site, materials and money",
            "Alerts before small problems become big ones",
        ],
        "We set one rule: one screen, one truth, alerts before problems. This is the platform that does that. Today we show it on one project - but the same screen manages every project we run.",
    ),
    (
        "Meet Kashi Kunj",
        "Our demo project - a residential building in Jabalpur",
        [
            "47% built · budget ₹90 lakh · handover target Mar 2027",
            "16 construction tasks · 8 daily site logs",
            "10 material lines · 5 suppliers · 3 invoices issued",
            "Four real users: Owner, Site Supervisor, Procurement, Client",
        ],
        "This is the project we'll walk through. Establish the cast now: the owner, the site supervisor, procurement, and the client. You will switch between them live.",
    ),
    (
        "One screen, every project",
        "The Command Center computes health from real data",
        [
            "Kashi Kunj is AMBER today - and the system says why",
            "Progress 47% vs 52% of the schedule elapsed (SPI 0.91)",
            "2 of 16 tasks overdue - flagged for the team to act",
            "No one picked that colour: the data did",
        ],
        "Open the Command Center: every project, with a health light. Kashi Kunj is amber today because we are 47% complete against 52% of the schedule. Nobody painted this colour - the data did.",
    ),
    (
        "A schedule that thinks",
        "Linked tasks, automatic fixes, honest flags",
        [
            "16 tasks linked like a real construction plan",
            "Plan one task too early? The system shifts it and tells the team",
            "Today: 2 overdue tasks show exactly where to focus",
        ],
        "Sixteen linked tasks, like the real plan. Internal Plaster was planned too early - the system caught it, shifted it, and alerted the team. Two tasks are overdue today, so everyone knows where to focus tomorrow.",
    ),
    (
        "Every day on site, captured",
        "Daily logs that become decisions",
        [
            "What was done, who was there, what was flagged",
            "8 dated entries across the build",
            "Recent log: \"Cement stock running low at site\"",
            "A small note that becomes a real alert",
        ],
        "The supervisor's daily log: work done, weather, headcount, issues. Notice the note from a few days ago - cement running low. A small complaint the system turns into an actual alert.",
    ),
    (
        "Materials without surprises",
        "Live stock, honest ledgers, automatic alerts",
        [
            "10 material lines with live balances and reorder levels",
            "Cement is low today: 25 bags, reorder at 30 - alert raised by itself",
            "Every bag sits on an unchangeable ledger: received, used, remaining",
            "What the screen says is what the store really holds",
        ],
        "Ten material lines with live balances. Cement is at 25 bags, below its reorder level of 30, and the system raised the alarm by itself. Every bag sits on a ledger that cannot be edited - what the screen says is what the store holds.",
    ),
    (
        "Buying with controls",
        "Purchase orders with a real workflow",
        [
            "Draft → submitted → approved / rejected → received",
            "Today: one received, one half-received, one approved",
            "One waiting on the owner's desk - approve live",
            "One rejected (rate too high) with the reason recorded",
            "Approval is a decision, and it belongs to the owner",
        ],
        "Purchases run a real workflow. Five orders, five states - including one sitting on the owner's desk for approval, and one rejected because the rate was too high, with the reason recorded. Approvals belong to the owner alone.",
    ),
    (
        "Money you can trust",
        "The number on screen equals the cost ledger",
        [
            "Budget ₹90,00,000 · Spent ₹32,98,150 · Remaining ₹57,01,850",
            "Every rupee traceable to labour, material, or a supplier receipt",
            "Spent is derived from the ledger - never hand-typed",
        ],
        "Budget 90 lakh, spent 32.98 lakh, remaining 57 lakh. That spent figure is not typed by anyone - it's the sum of the cost ledger, every rupee traceable to a labour line, a material line, or a supplier receipt. No hand-typed totals.",
    ),
    (
        "Client confidence",
        "A clean portal, exactly what the client should see",
        [
            "Progress, schedule, and their invoices - nothing more",
            "3 invoices issued: 2 paid, 1 outstanding",
            "No internal costs, suppliers or stock",
            "Enforced by the system, not by a promise",
        ],
        "The client sees a clean portal: progress, schedule, and their invoices. Two paid, one outstanding. They never see our internal costs or suppliers - and the system enforces that, not a promise.",
    ),
    (
        "The right view for the right role",
        "Access that is verified, not assumed",
        [
            "Owner - everything, every project",
            "Site Supervisor - their site, schedule, logs; no money figures",
            "Procurement - suppliers, orders, stock, finance reads",
            "Client - progress and invoices only",
            "Wrong access is refused instantly, every time",
        ],
        "Owner sees everything. Supervisor sees the site but no money. Procurement sees suppliers, orders and stock. Client sees progress and invoices. Access is enforced by the system - the wrong role is refused instantly and every time.",
    ),
    (
        "AI that helps - with guardrails",
        "Ask in plain language; changes need a human",
        [
            "Ask: \"What is low in stock?\" - it answers from live data",
            "Ask: \"Show open purchase orders\" - it opens them",
            "Want it to change something? It must ask for approval first",
            "Watch: we'll create a task live - and reject it",
        ],
        "Ask in plain words: what is low in stock - it answers. But when the assistant wants to change something, it must ask a human first. Watch: I'll ask it to create a task, it proposes, and I'll reject it so the project stays exactly as it is.",
    ),
    (
        "The proof is in the trail",
        "Audited, controlled, repeatable",
        [
            "Every change logged: who, what, when - nothing can be rewritten",
            "Every alert raised by the system, not typed in",
            "The same dataset can be reset and re-run identically",
            "Rehearsed this morning - rebuildable for you tomorrow",
        ],
        "Every change is audited - who, what, when. Every alert you saw was raised by the system, not typed in. And this whole dataset can be reset and re-run identically: we rehearsed it this morning, and we can rebuild it for you tomorrow.",
    ),
    (
        "Let's build this for you",
        "From one project to the whole portfolio",
        [
            "Today you saw the full cycle on one project",
            "Tomorrow: every Sparkbuild project on the same Command Center",
            "Thank you - questions welcome",
        ],
        "You saw the full cycle on one project. The same Command Center runs every Sparkbuild site. We'd like to run a pilot on your live projects. Thank you - questions?",
    ),
]


def _add_rect(slide, x, y, w, h, fill, line=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(1)
    shape.shadow.inherit = False
    return shape


def _add_text(slide, x, y, w, h, text, size, color, bold=False, align=PP_ALIGN.LEFT,
              anchor=MSO_ANCHOR.TOP, wrap=True):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = Emu(0)
    tf.margin_right = Emu(0)
    tf.margin_top = Emu(0)
    tf.margin_bottom = Emu(0)
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.bold = bold
    return box


def _add_bullets(slide, x, y, w, h, bullets, size=18, gap=12):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Emu(0)
    tf.margin_right = Emu(0)
    tf.margin_top = Emu(0)
    tf.margin_bottom = Emu(0)
    for i, bullet in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(gap)
        run = p.add_run()
        run.text = bullet
        run.font.size = Pt(size)
        run.font.color.rgb = DARK
    return box


def build() -> None:
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    blank = prs.slide_layouts[6]

    for idx, (title, subtitle, bullets, notes) in enumerate(SLIDES):
        slide = prs.slides.add_slide(blank)

        if idx == 0:
            _add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, NAVY)
            _add_rect(slide, 0, Emu(4762500), SLIDE_W, Pt(6), YELLOW)
            _add_text(slide, Emu(685800), Emu(914400), Emu(10668000), Emu(1100000),
                      title, 52, WHITE, bold=True)
            _add_text(slide, Emu(685800), Emu(2133600), Emu(10668000), Emu(600000),
                      subtitle, 22, RGBColor(0xCF, 0xE3, 0xFF))
            _add_bullets(slide, Emu(685800), Emu(3124200), Emu(10668000), Emu(1200000),
                         bullets, size=20)
            if LOGO.exists():
                try:
                    slide.shapes.add_picture(str(LOGO), Emu(685800), Emu(480000), height=Emu(1200000))
                except Exception:
                    pass
            _add_text(slide, Emu(685800), Emu(6250000), Emu(10668000), Emu(400000),
                      "Sparkbuild Construction  ·  www.sparkbuild.in  ·  Jabalpur, Madhya Pradesh",
                      12, RGBColor(0x9F, 0xB4, 0xCC))
        else:
            _add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, GRAY_BG)
            _add_rect(slide, 0, 0, SLIDE_W, Emu(1080000), NAVY)
            _add_rect(slide, Emu(685800), Emu(1193800), Emu(2286000), Pt(4), ORANGE)
            _add_text(slide, Emu(685800), Emu(220000), Emu(10668000), Emu(700000),
                      title, 34, WHITE, bold=True)
            _add_text(slide, Emu(685800), Emu(860000), Emu(10668000), Emu(300000),
                      subtitle, 16, RGBColor(0xCF, 0xE3, 0xFF))
            _add_bullets(slide, Emu(685800), Emu(1900000), Emu(10668000), Emu(4300000),
                         bullets, size=21, gap=16)
            _add_rect(slide, 0, Emu(6320000), SLIDE_W, Emu(538000), NAVY)
            _add_text(slide, Emu(685800), Emu(6480000), Emu(10668000), Emu(300000),
                      f"Sparkbuild Construction  ·  Kashi Kunj, Jabalpur   ({idx:02d}/15)",
                      11, RGBColor(0x9F, 0xB4, 0xCC))

        slide.notes_slide.notes_text_frame.text = notes

    prs.save(OUT)
    print(f"Wrote {OUT} ({len(SLIDES)} slides)")


if __name__ == "__main__":
    build()