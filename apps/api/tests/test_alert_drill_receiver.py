import pytest

from app.monitoring.alert_drill_receiver import MAX_EVENTS, DrillState, summarize_webhook


def test_alert_drill_receiver_keeps_only_low_cardinality_fields():
    payload = {
        "status": "firing",
        "receiver": "local-drill-webhook",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "SapAiFlowAcceptanceDrill",
                    "severity": "critical",
                    "project_id": "project-secret-123",
                    "tenant_id": "tenant-secret-456",
                },
                "annotations": {
                    "description": "customer secret@example.com token Bearer raw-secret"
                },
            }
        ],
    }

    summaries = summarize_webhook(payload)

    assert summaries == [
        {
            "alertname": "SapAiFlowAcceptanceDrill",
            "severity": "critical",
            "status": "firing",
        }
    ]
    serialized = str(summaries)
    assert "project-secret" not in serialized
    assert "tenant-secret" not in serialized
    assert "secret@example.com" not in serialized
    assert "raw-secret" not in serialized


def test_alert_drill_receiver_bounds_memory_and_rejects_invalid_payloads():
    state = DrillState()
    for index in range(MAX_EVENTS + 5):
        state.record(
            [
                {
                    "alertname": f"SapAiFlowDrill{index}",
                    "severity": "warning",
                    "status": "resolved",
                }
            ]
        )

    report = state.report()

    assert report["event_count"] == MAX_EVENTS
    assert report["events"][0]["alertname"] == "SapAiFlowDrill5"

    for invalid in ({}, {"alerts": []}, {"alerts": ["invalid"]}):
        with pytest.raises(ValueError):
            summarize_webhook(invalid)
