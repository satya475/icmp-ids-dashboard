"""
ids/signature/engine.py
========================
Runs all signature rules on every packet.
Think of this as the rule checker.
"""

from ids.signature.rules import ALL_RULES


def check_packet(features):
    """
    Run every rule against a single packet.
    Returns a list of alerts (can be empty if no rules matched).
    """
    alerts = []

    for rule in ALL_RULES:
        try:
            result = rule(features)
            if result is not None:
                alerts.append(result)
        except Exception as e:
            print(f"[SIGNATURE ENGINE ERROR] {e}")

    return alerts


def run_signature_ids(features, on_alert):
    """
    Check packet against all rules.
    If any rule fires → send alert to on_alert callback.
    """
    alerts = check_packet(features)

    for alert in alerts:
        severity = alert["severity"].upper()
        print(f"[SIGNATURE] [{severity}] {alert['message']}")
        on_alert(alert)