
import pytest
import json
from unittest.mock import patch, Mock
from flask import Flask, jsonify, request

@pytest.fixture
def app():
    """
    Fixture to create a Flask app instance with the /api/assistant/llm endpoint.
    The endpoint interacts with a mocked LLM API.
    """
    app = Flask(__name__)

    @app.route('/api/assistant/llm', methods=['POST'])
    def llm_endpoint():
        try:
            data = request.get_json(force=True)
        except Exception:
            return jsonify({'success': False, 'error': 'Malformed JSON'}), 400

        user_prompt = data.get('user_prompt')
        context = data.get('context', '')

        if not user_prompt:
            return jsonify({'success': False, 'error': 'Missing user_prompt'}), 400

        try:
            # Simulate LLM API call
            from my_llm_module import generate_llm_response
            llm_response = generate_llm_response(user_prompt, context)
        except Exception as e:
            return jsonify({'success': False, 'error': 'LLM API unavailable'}), 503

        return jsonify({'success': True, 'response': llm_response}), 200

    return app

@pytest.fixture
def client(app):
    """
    Fixture to provide a test client for the Flask app.
    """
    return app.test_client()

@patch('my_llm_module.generate_llm_response')
def test_integration_llm_endpoint_returns_model_response(mock_generate_llm_response, client):
    """
    Integration test:
    Verifies that the /api/assistant/llm endpoint interacts with the LLM and returns a generated response.
    Success criteria:
      - HTTP status is 200
      - response['success'] is True
      - response['response'] is a non-empty string
    """
    mock_generate_llm_response.return_value = "This is a generated LLM response."

    payload = {
        "user_prompt": "Tell me a joke.",
        "context": "Humor"
    }
    response = client.post('/api/assistant/llm', data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 200
    resp_json = response.get_json()
    assert resp_json['success'] is True
    assert isinstance(resp_json['response'], str)
    assert resp_json['response'] != ""

def test_integration_llm_endpoint_missing_user_prompt(client):
    """
    Integration test:
    Verifies that the endpoint returns an error when user_prompt is missing.
    """
    payload = {
        "context": "Humor"
    }
    response = client.post('/api/assistant/llm', data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 400
    resp_json = response.get_json()
    assert resp_json['success'] is False
    assert resp_json['error'] == 'Missing user_prompt'

@patch('my_llm_module.generate_llm_response')
def test_integration_llm_endpoint_llm_api_unavailable(mock_generate_llm_response, client):
    """
    Integration test:
    Verifies that the endpoint returns an error when the LLM API is unavailable.
    """
    mock_generate_llm_response.side_effect = Exception("LLM API down")
    payload = {
        "user_prompt": "Tell me a joke.",
        "context": "Humor"
    }
    response = client.post('/api/assistant/llm', data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 503
    resp_json = response.get_json()
    assert resp_json['success'] is False
    assert resp_json['error'] == 'LLM API unavailable'

def test_integration_llm_endpoint_malformed_json(client):
    """
    Integration test:
    Verifies that the endpoint returns an error when the input JSON is malformed.
    """
    malformed_json = '{"user_prompt": "Tell me a joke.", "context": "Humor"'  # Missing closing }
    response = client.post('/api/assistant/llm', data=malformed_json, content_type='application/json')
    assert response.status_code == 400
    resp_json = response.get_json()
    assert resp_json['success'] is False
    assert resp_json['error'] == 'Malformed JSON'
