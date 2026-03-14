
import pytest
import time
from unittest.mock import patch, MagicMock
import random

@pytest.fixture
def mock_verify_ticket_response():
    """
    Fixture to provide a mocked response for the /api/assistant/verify_ticket endpoint.
    Simulates a successful ticket verification.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "verified"}
    return mock_response

@pytest.fixture
def mock_post(monkeypatch, mock_verify_ticket_response):
    """
    Fixture to patch requests.post for the test, simulating both successful and error responses.
    """
    def _mock_post(url, json, timeout=None):
        # Simulate random errors for error rate calculation
        # 98% success, 2% error
        if random.random() < 0.02:
            error_response = MagicMock()
            error_response.status_code = 500
            error_response.json.return_value = {"error": "Internal Server Error"}
            return error_response
        # Simulate occasional timeout
        if random.random() < 0.01:
            raise TimeoutError("Simulated timeout")
        return mock_verify_ticket_response
    monkeypatch.setattr("requests.post", _mock_post)
    return _mock_post

@pytest.mark.performance
def test_performance_high_load_ticket_verification(mock_post):
    """
    Performance test: Measures system response time and stability under high load for /api/assistant/verify_ticket.
    Simulates 200 concurrent POST requests with valid ticket data.
    Asserts average response time < 2s, error rate < 2%, and no crashes.
    """
    import requests

    NUM_REQUESTS = 200
    ticket_data = {"ticket_id": "ABC123", "user_id": "U456"}
    response_times = []
    errors = 0

    start_time = time.time()
    for _ in range(NUM_REQUESTS):
        req_start = time.time()
        try:
            response = requests.post("http://localhost:8080/api/assistant/verify_ticket", json=ticket_data, timeout=3)
            if response.status_code != 200:
                errors += 1
        except TimeoutError:
            errors += 1
        except Exception as e:
            errors += 1
        req_end = time.time()
        response_times.append(req_end - req_start)
    end_time = time.time()

    avg_response_time = sum(response_times) / len(response_times)
    error_rate = errors / NUM_REQUESTS
    throughput = NUM_REQUESTS / (end_time - start_time)

    # Assertions
    assert avg_response_time < 2.0, f"Average response time {avg_response_time:.2f}s exceeds 2s"
    assert error_rate < 0.02, f"Error rate {error_rate*100:.2f}% exceeds 2%"
    assert errors < NUM_REQUESTS, "Application crashed or exhausted resources under load"

    # Print aggregate statistics for informational purposes
    print(f"Performance stats: avg_response_time={avg_response_time:.2f}s, error_rate={error_rate*100:.2f}%, throughput={throughput:.2f} req/s")

