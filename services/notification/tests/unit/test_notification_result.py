from services.notification.notifiers.base import NotificationResult


def test_notification_result_or_operation():
    result_default = NotificationResult()
    result_explanation = NotificationResult(explanation="some_explanation")
    result_not_attempted = NotificationResult(
        notification_attempted=False,
        notification_successful=False,
        explanation="dont_want",
    )
    result_attempted = NotificationResult(
        notification_attempted=True,
        notification_successful=True,
        explanation=None,
    )
    result_some_data = NotificationResult(
        data_sent={"comment": "hi"}, data_received={"response": "hi"}
    )
    assert result_default.merge(result_explanation) == result_explanation
    assert result_default.merge(result_not_attempted) == result_not_attempted
    assert result_attempted.merge(result_some_data) == NotificationResult(
        notification_attempted=True,
        notification_successful=True,
        explanation=None,
        data_sent={"comment": "hi"},
        data_received={"response": "hi"},
    )
    assert result_not_attempted.merge(result_some_data) == NotificationResult(
        notification_attempted=False,
        notification_successful=False,
        explanation="dont_want",
        data_sent={"comment": "hi"},
        data_received={"response": "hi"},
    )
