
import pytest
import json
from unittest.mock import patch, Mock
from flask import Flask, request, jsonify

# --- Fixtures ---

@pytest.fixture
def app():
    """
    Fixture to provide a Flask app instance for integration testing.
    """
    app = Flask(__name__)

    @app.route('/api/assistant/escalate', methods=['POST'])
    def escalate():
        data = request.get_json()
        if not data or 'issue_details' not in data:
            return jsonify({'success': False, 'response': 'Missing issue details'}), 400

        # Simulate notification and audit logging services
        try:
            notify_result = app.config['notify_service'](data['issue_details'], data.get('user_context'))
            audit_result = app.config['audit_log_service'](data)
        except Exception as e:
            return jsonify({'success': False, 'response': str(e)}), 500

        return jsonify({
            'success': True,
            'response': 'Issue escalated to human staff'
        }), 200

    return app

@pytest.fixture
def client(app):
    """
    Fixture to provide a test client for the Flask app.
    """
    return app.test_client()

@pytest.fixture
def mock_notify_service():
    """
    Fixture to mock the notification service.
    """
    def notify(issue_details, user_context):
        return True
    return notify

@pytest.fixture
def mock_audit_log_service():
    """
    Fixture to mock the audit logging service.
    """
    def audit(data):
        return True
    return audit

@pytest.fixture(autouse=True)
def configure_services(app, mock_notify_service, mock_audit_log_service):
    """
    Fixture to configure the app with mocked external services.
    """
    app.config['notify_service'] = mock_notify_service
    app.config['audit_log_service'] = mock_audit_log_service

# --- Integration Test ---

def test_integration_escalation_endpoint_with_complete_data(client):
    """
    Validates that the /api/assistant/escalate endpoint successfully escalates an issue
    when provided with all required data.
    """
    payload = {
        'issue_details': {'id': 123, 'description': 'User cannot access account'},
        'user_context': {'user_id': 'abc', 'role': 'customer'}
    }
    response = client.post('/api/assistant/escalate', data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 200, "Expected HTTP 200 for successful escalation"
    resp_json = response.get_json()
    assert resp_json['success'] is True, "Expected success=True in response"
    assert 'escalated to human staff' in resp_json['response'], "Expected escalation confirmation message"

# --- Error Scenarios ---

def test_integration_escalation_notification_service_unavailable(client, app, mock_audit_log_service):
    """
    Tests escalation endpoint when notification service is unavailable.
    """
    def failing_notify(issue_details, user_context):
        raise Exception("Notification service unavailable")
    app.config['notify_service'] = failing_notify
    app.config['audit_log_service'] = mock_audit_log_service

    payload = {
        'issue_details': {'id': 123, 'description': 'User cannot access account'},
        'user_context': {'user_id': 'abc', 'role': 'customer'}
    }
    response = client.post('/api/assistant/escalate', data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 500, "Expected HTTP 500 when notification service fails"
    resp_json = response.get_json()
    assert resp_json['success'] is False
    assert 'Notification service unavailable' in resp_json['response']

def test_integration_escalation_audit_logging_service_failure(client, app, mock_notify_service):
    """
    Tests escalation endpoint when audit logging service fails.
    """
    def failing_audit(data):
        raise Exception("Audit logging service failure")
    app.config['notify_service'] = mock_notify_service
    app.config['audit_log_service'] = failing_audit

    payload = {
        'issue_details': {'id': 123, 'description': 'User cannot access account'},
        'user_context': {'user_id': 'abc', 'role': 'customer'}
    }
    response = client.post('/api/assistant/escalate', data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 500, "Expected HTTP 500 when audit logging service fails"
    resp_json = response.get_json()
    assert resp_json['success'] is False
    assert 'Audit logging service failure' in resp_json['response']

def test_integration_escalation_missing_issue_details(client):
    """
    Tests escalation endpoint when 'issue_details' is missing from request.
    """
    payload = {
        'user_context': {'user_id': 'abc', 'role': 'customer'}
    }
    response = client.post('/api/assistant/escalate', data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 400, "Expected HTTP 400 for missing issue_details"
    resp_json = response.get_json()
    assert resp_json['success'] is False
    assert 'Missing issue details' in resp_json['response']
