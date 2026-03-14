
import pytest
import time
from unittest.mock import patch, Mock

@pytest.fixture
def valid_ticket_data():
    """Fixture providing valid ticket data for verification."""
    return {
        "ticket_id": "ABC123",
        "user_id": "user456",
        "event_id": "event789"
    }

@pytest.fixture
def mock_external_ticket_db_api():
    """Fixture to mock external ticket DB API calls."""
    with patch('myapp.ticket_verification.external_ticket_db_api') as mock_api:
        # Simulate normal latency (0.5s) and peak latency (1.2s)
        def side_effect(ticket_id):
            time.sleep(0.5)  # Normal load
            return {"status": "valid", "ticket_id": ticket_id}
        mock_api.verify_ticket.side_effect = side_effect
        yield mock_api

@pytest.fixture
def mock_external_ticket_db_api_peak():
    """Fixture to mock external ticket DB API calls under peak load."""
    with patch('myapp.ticket_verification.external_ticket_db_api') as mock_api:
        # Simulate peak latency (1.2s)
        def side_effect(ticket_id):
            time.sleep(1.2)  # Peak load
            return {"status": "valid", "ticket_id": ticket_id}
        mock_api.verify_ticket.side_effect = side_effect
        yield mock_api

@pytest.fixture
def mock_external_ticket_db_api_timeout():
    """Fixture to simulate timeout in external ticket DB API."""
    with patch('myapp.ticket_verification.external_ticket_db_api') as mock_api:
        def side_effect(ticket_id):
            time.sleep(2.5)  # Simulate timeout (>1.5s)
            raise TimeoutError("External API timeout")
        mock_api.verify_ticket.side_effect = side_effect
        yield mock_api

@pytest.fixture
def client():
    """Fixture for test client (mocked, no real HTTP calls)."""
    # Replace with your actual test client setup, e.g., Flask/Django test client
    class MockClient:
        def post(self, url, json):
            # Simulate calling the ticket verification workflow
            from myapp.ticket_verification import verify_ticket_workflow
            return verify_ticket_workflow(json)
    return MockClient()

@pytest.mark.performance
def test_performance_ticket_verification_api_latency_normal(client, valid_ticket_data, mock_external_ticket_db_api):
    """
    Performance test: Measures latency of ticket verification API under normal load.
    Asserts 95th percentile latency is below 1.5 seconds and no timeouts occur.
    """
    latencies = []
    num_requests = 20
    failed_requests = 0

    for _ in range(num_requests):
        start = time.time()
        try:
            response = client.post("/api/assistant/verify_ticket", json=valid_ticket_data)
            assert response["status"] == "valid"
        except Exception:
            failed_requests += 1
        end = time.time()
        latencies.append(end - start)

    latencies.sort()
    p95_latency = latencies[int(0.95 * num_requests) - 1]
    assert p95_latency < 1.5, f"95th percentile latency {p95_latency:.2f}s exceeds 1.5s"
    assert failed_requests == 0, f"{failed_requests} requests failed due to timeouts"

@pytest.mark.performance
def test_performance_ticket_verification_api_latency_peak(client, valid_ticket_data, mock_external_ticket_db_api_peak):
    """
    Performance test: Measures latency of ticket verification API under peak load.
    Asserts 95th percentile latency is below 1.5 seconds and no timeouts occur.
    """
    latencies = []
    num_requests = 20
    failed_requests = 0

    for _ in range(num_requests):
        start = time.time()
        try:
            response = client.post("/api/assistant/verify_ticket", json=valid_ticket_data)
            assert response["status"] == "valid"
        except Exception:
            failed_requests += 1
        end = time.time()
        latencies.append(end - start)

    latencies.sort()
    p95_latency = latencies[int(0.95 * num_requests) - 1]
    assert p95_latency < 1.5, f"95th percentile latency {p95_latency:.2f}s exceeds 1.5s under peak load"
    assert failed_requests == 0, f"{failed_requests} requests failed due to timeouts under peak load"

@pytest.mark.performance
def test_performance_ticket_verification_api_latency_no_failed_requests(client, valid_ticket_data, mock_external_ticket_db_api):
    """
    Performance test: Ensures no failed requests due to timeouts during ticket verification.
    """
    num_requests = 20
    failed_requests = 0

    for _ in range(num_requests):
        try:
            response = client.post("/api/assistant/verify_ticket", json=valid_ticket_data)
            assert response["status"] == "valid"
        except Exception:
            failed_requests += 1

    assert failed_requests == 0, f"{failed_requests} requests failed due to timeouts"

@pytest.mark.performance
def test_performance_ticket_verification_api_latency_timeout_handling(client, valid_ticket_data, mock_external_ticket_db_api_timeout):
    """
    Performance test: Simulates external API timeout and verifies proper error handling.
    """
    try:
        client.post("/api/assistant/verify_ticket", json=valid_ticket_data)
        pytest.fail("Expected TimeoutError but request succeeded")
    except TimeoutError as e:
        assert "timeout" in str(e).lower(), "TimeoutError not raised as expected"

