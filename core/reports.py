"""
core/reports.py
================
PDF report generator using ReportLab.
Generates daily/weekly uptime, RTT graphs,
and bandwidth usage summary.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
from datetime import datetime, timedelta
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, PageBreak)
from reportlab.graphics.shapes import Drawing, Rect, Line, String, PolyLine
from reportlab.graphics import renderPDF
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib.colors import HexColor

from db.queries import (get_devices_with_status, get_all_uptimes,
                        get_rtt_history, get_bandwidth_totals,
                        get_state_changes)
from config import DB_FILE

# ─────────────────────────────────────────
# Color palette
# ─────────────────────────────────────────
C_PRIMARY   = HexColor("#0f1117")
C_SURFACE   = HexColor("#1a1d27")
C_BLUE      = HexColor("#3b82f6")
C_GREEN     = HexColor("#22c55e")
C_RED       = HexColor("#ef4444")
C_AMBER     = HexColor("#f59e0b")
C_MUTED     = HexColor("#64748b")
C_BORDER    = HexColor("#e2e8f0")
C_BG        = HexColor("#f8fafc")
C_WHITE     = colors.white
C_BLACK     = colors.black

# ─────────────────────────────────────────
# Styles
# ─────────────────────────────────────────

def _get_styles():
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("title", fontSize=22, fontName="Helvetica-Bold",
                                 textColor=C_PRIMARY, spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", fontSize=12, fontName="Helvetica",
                                    textColor=C_MUTED, spaceAfter=20),
        "section": ParagraphStyle("section", fontSize=14, fontName="Helvetica-Bold",
                                   textColor=C_PRIMARY, spaceBefore=16, spaceAfter=8),
        "body": ParagraphStyle("body", fontSize=10, fontName="Helvetica",
                                textColor=C_PRIMARY, spaceAfter=6),
        "small": ParagraphStyle("small", fontSize=9, fontName="Helvetica",
                                 textColor=C_MUTED),
        "caption": ParagraphStyle("caption", fontSize=9, fontName="Helvetica",
                                   textColor=C_MUTED, alignment=1),
    }
    return styles


# ─────────────────────────────────────────
# Table helpers
# ─────────────────────────────────────────

def _base_table_style():
    return TableStyle([
        ("BACKGROUND",   (0,0), (-1,0), C_SURFACE),
        ("TEXTCOLOR",    (0,0), (-1,0), C_WHITE),
        ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,0), 9),
        ("FONTNAME",     (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE",     (0,1), (-1,-1), 9),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_BG]),
        ("TEXTCOLOR",    (0,1), (-1,-1), C_PRIMARY),
        ("GRID",         (0,0), (-1,-1), 0.5, C_BORDER),
        ("TOPPADDING",   (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0), (-1,-1), 6),
        ("LEFTPADDING",  (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
    ])


def _status_color(status: str):
    return {
        "UP":      C_GREEN,
        "DOWN":    C_RED,
        "DEGRADED":C_AMBER,
        "UNKNOWN": C_MUTED,
    }.get(status, C_MUTED)


def _uptime_color(pct: Optional[float]):
    if pct is None:
        return C_MUTED
    if pct >= 90:
        return C_GREEN
    if pct >= 50:
        return C_AMBER
    return C_RED


# ─────────────────────────────────────────
# RTT sparkline (simple line drawing)
# ─────────────────────────────────────────

def _rtt_sparkline(ip: str, width: float = 120, height: float = 30) -> Optional[Drawing]:
    """Draw a tiny RTT history line for a device."""
    try:
        history = get_rtt_history(ip, minutes=1440)  # 24h
        values  = [h["rtt_avg_ms"] for h in history if h["rtt_avg_ms"] is not None]
        if len(values) < 2:
            return None

        d     = Drawing(width, height)
        max_v = max(values) or 1
        min_v = min(values)
        rng   = max_v - min_v or 1
        pad   = 4

        points = []
        for i, v in enumerate(values):
            x = pad + (i / (len(values)-1)) * (width - 2*pad)
            y = pad + ((v - min_v) / rng) * (height - 2*pad)
            points.extend([x, y])

        line = PolyLine(points, strokeColor=C_BLUE, strokeWidth=1, fillColor=None)
        d.add(line)
        return d
    except Exception:
        return None


# ─────────────────────────────────────────
# Report sections
# ─────────────────────────────────────────

def _header_section(styles: dict, period: str, generated: str) -> list:
    elements = []
    elements.append(Paragraph("Network Monitor Report", styles["title"]))
    elements.append(Paragraph(f"Period: {period}  |  Generated: {generated}", styles["subtitle"]))
    elements.append(HRFlowable(width="100%", thickness=1, color=C_BORDER))
    elements.append(Spacer(1, 12))
    return elements


def _summary_section(styles: dict, devices: list, uptimes: dict) -> list:
    elements = []
    elements.append(Paragraph("Network Summary", styles["section"]))

    total   = len(devices)
    up      = sum(1 for d in devices if d["is_alive"] == 1)
    down    = sum(1 for d in devices if d["is_alive"] == 0)
    unknown = total - up - down
    rtts    = [d["rtt_avg_ms"] for d in devices if d["rtt_avg_ms"]]
    avg_rtt = round(sum(rtts)/len(rtts), 1) if rtts else None
    avg_up  = round(sum(uptimes.values())/len(uptimes), 1) if uptimes else None

    data = [
        ["Metric", "Value"],
        ["Total devices monitored", str(total)],
        ["Currently online",        f"{up} / {total}"],
        ["Currently offline",       str(down)],
        ["Average RTT",             f"{avg_rtt} ms" if avg_rtt else "—"],
        ["Average uptime (24h)",    f"{avg_up}%" if avg_up else "—"],
    ]
    t = Table(data, colWidths=[9*cm, 8*cm])
    t.setStyle(_base_table_style())
    elements.append(t)
    elements.append(Spacer(1, 16))
    return elements


def _device_uptime_section(styles: dict, devices: list, uptimes: dict) -> list:
    elements = []
    elements.append(Paragraph("Device Uptime", styles["section"]))

    data = [["Device", "IP Address", "Status", "Uptime 24h", "Avg RTT"]]
    for d in sorted(devices, key=lambda x: x["name"] or ""):
        uptime = uptimes.get(d["ip"])
        rtt    = f"{d['rtt_avg_ms']:.1f} ms" if d["rtt_avg_ms"] else "—"
        status = "UP" if d["is_alive"]==1 else ("DOWN" if d["is_alive"]==0 else "UNKNOWN")
        data.append([
            d["name"] or d["ip"],
            d["ip"],
            status,
            f"{uptime}%" if uptime is not None else "—",
            rtt,
        ])

    col_w = [5.5*cm, 3.5*cm, 2.5*cm, 3*cm, 3*cm]
    t     = Table(data, colWidths=col_w)
    style = _base_table_style()

    # Color status column
    for i, d in enumerate(devices, start=1):
        status = "UP" if d["is_alive"]==1 else ("DOWN" if d["is_alive"]==0 else "UNKNOWN")
        style.add("TEXTCOLOR", (2, i), (2, i), _status_color(status))
        style.add("FONTNAME",  (2, i), (2, i), "Helvetica-Bold")

        uptime = uptimes.get(d["ip"])
        style.add("TEXTCOLOR", (3, i), (3, i), _uptime_color(uptime))

    t.setStyle(style)
    elements.append(t)
    elements.append(Spacer(1, 16))
    return elements


def _rtt_section(styles: dict, devices: list) -> list:
    elements = []
    elements.append(Paragraph("RTT History (24h)", styles["section"]))

    data = [["Device", "IP", "Min RTT", "Avg RTT", "Max RTT", "Trend"]]
    sparklines = []

    for d in devices:
        if not d["rtt_avg_ms"]:
            continue
        hist   = get_rtt_history(d["ip"], minutes=1440)
        values = [h["rtt_avg_ms"] for h in hist if h["rtt_avg_ms"]]
        if not values:
            continue
        spark = _rtt_sparkline(d["ip"])
        sparklines.append(spark)
        data.append([
            d["name"] or d["ip"],
            d["ip"],
            f"{min(values):.1f}",
            f"{sum(values)/len(values):.1f}",
            f"{max(values):.1f}",
            spark if spark else "—",
        ])

    if len(data) == 1:
        elements.append(Paragraph("No RTT data available yet.", styles["body"]))
        return elements

    col_w = [4.5*cm, 3*cm, 2.5*cm, 2.5*cm, 2.5*cm, 3.5*cm]
    t     = Table(data, colWidths=col_w, rowHeights=[None] + [36]*len(sparklines))
    t.setStyle(_base_table_style())
    elements.append(t)
    elements.append(Spacer(1, 16))
    return elements


def _alert_history_section(styles: dict, limit: int = 20) -> list:
    elements = []
    elements.append(Paragraph("Alert History", styles["section"]))
    alerts = get_state_changes(limit=limit)

    if not alerts:
        elements.append(Paragraph("No alerts recorded in this period.", styles["body"]))
        return elements

    data = [["Time", "Device", "IP", "Change"]]
    for a in alerts:
        ts     = datetime.fromisoformat(a["timestamp"]).strftime("%d/%m %H:%M")
        change = f"{a['old_status'] or '—'} → {a['new_status']}"
        data.append([ts, a["name"], a["host"], change])

    col_w = [3*cm, 5*cm, 3.5*cm, 6*cm]
    t     = Table(data, colWidths=col_w)
    style = _base_table_style()

    for i, a in enumerate(alerts, start=1):
        color = _status_color(a["new_status"])
        style.add("TEXTCOLOR", (3, i), (3, i), color)
        style.add("FONTNAME",  (3, i), (3, i), "Helvetica-Bold")

    t.setStyle(style)
    elements.append(t)
    elements.append(Spacer(1, 16))
    return elements


def _bandwidth_section(styles: dict) -> list:
    elements = []
    elements.append(Paragraph("Bandwidth Usage", styles["section"]))

    try:
        totals = get_bandwidth_totals()
        daily  = totals.get("daily",  [])
        weekly = totals.get("weekly", [])
    except Exception:
        elements.append(Paragraph("No bandwidth data available yet.", styles["body"]))
        return elements

    def fmt(b):
        if b >= 1e9: return f"{b/1e9:.2f} GB"
        if b >= 1e6: return f"{b/1e6:.1f} MB"
        if b >= 1e3: return f"{b/1e3:.1f} KB"
        return f"{int(b)} B"

    # Daily table
    elements.append(Paragraph("Last 24 hours", styles["body"]))
    if daily:
        data = [["Device", "Downloaded", "Uploaded", "Total"]]
        for r in daily[:15]:
            total = (r["total_in"] or 0) + (r["total_out"] or 0)
            data.append([r["name"] or r["ip"],
                         fmt(r["total_in"] or 0),
                         fmt(r["total_out"] or 0),
                         fmt(total)])
        col_w = [6*cm, 4*cm, 4*cm, 4*cm]
        t     = Table(data, colWidths=col_w)
        t.setStyle(_base_table_style())
        elements.append(t)
    else:
        elements.append(Paragraph("No bandwidth data for last 24 hours.", styles["small"]))

    elements.append(Spacer(1, 12))

    # Weekly table
    elements.append(Paragraph("Last 7 days", styles["body"]))
    if weekly:
        data = [["Device", "Downloaded", "Uploaded", "Total"]]
        for r in weekly[:15]:
            total = (r["total_in"] or 0) + (r["total_out"] or 0)
            data.append([r["name"] or r["ip"],
                         fmt(r["total_in"] or 0),
                         fmt(r["total_out"] or 0),
                         fmt(total)])
        col_w = [6*cm, 4*cm, 4*cm, 4*cm]
        t     = Table(data, colWidths=col_w)
        t.setStyle(_base_table_style())
        elements.append(t)
    else:
        elements.append(Paragraph("No bandwidth data for last 7 days.", styles["small"]))

    elements.append(Spacer(1, 16))
    return elements


def _footer(canvas, doc):
    """Add page number and timestamp to every page."""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(C_MUTED)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    canvas.drawString(2*cm, 1.2*cm, f"Network Monitor Report — Generated {ts}")
    canvas.drawRightString(A4[0]-2*cm, 1.2*cm, f"Page {doc.page}")
    canvas.restoreState()


# ─────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────

def generate_report(period: str = "daily") -> bytes:
    """
    Generate a PDF report and return as bytes.
    period: 'daily' or 'weekly'
    """
    buf       = io.BytesIO()
    doc       = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm,  bottomMargin=2*cm
    )
    styles    = _get_styles()
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    period_label = "Last 24 hours" if period == "daily" else "Last 7 days"

    devices = get_devices_with_status()
    uptimes = get_all_uptimes(hours=24 if period == "daily" else 168)

    elements = []
    elements += _header_section(styles, period_label, generated)
    elements += _summary_section(styles, devices, uptimes)
    elements += _device_uptime_section(styles, devices, uptimes)
    elements += _rtt_section(styles, devices)
    elements += _alert_history_section(styles)
    elements.append(PageBreak())
    elements += _bandwidth_section(styles)

    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


if __name__ == "__main__":
    print("Generating daily report...")
    pdf = generate_report("daily")
    with open("report_daily.pdf", "wb") as f:
        f.write(pdf)
    print(f"Saved: report_daily.pdf ({len(pdf):,} bytes)")
