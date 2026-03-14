
import pytest
import time
import asyncio
from unittest.mock import patch, Mock, MagicMock

@pytest.fixture
def mock_llm_primary():
    """
    Fixture to mock the primary LLM API endpoint.
    Simulates successful and failed responses based on input.
    """
    def _mock_llm_api(user_prompt):
        # Simulate rate limit or timeout for certain prompts
        if "timeout" in user_prompt:
            raise Exception("LLM API timeout")
        elif "fail" in user_prompt:
            raise Exception("LLM API failure")
        else:
            # Simulate latency between 0.5s and 2s
            time.sleep(0.5 + (hash(user_prompt) % 1500) / 1000)
            return {"result": f"Primary LLM response for: {user_prompt}"}
    return _mock_llm_api

@pytest.fixture
def mock_llm_fallback():
    """
    Fixture to mock the fallback LLM API endpoint.
    Simulates successful and failed responses based on input.
    """
    def _mock_llm_api(user_prompt):
        if "fallback_fail" in user_prompt:
            raise Exception("LLM Fallback failure")
        else:
            # Simulate latency between 0.3s and 1.5s
            time.sleep(0.3 + (hash(user_prompt) % 1200) / 1000)
            return {"result": f"Fallback LLM response for: {user_prompt}"}
    return _mock_llm_api

@pytest.fixture
def mock_llm_endpoint(mock_llm_primary, mock_llm_fallback):
    """
    Fixture to mock the /api/assistant/llm endpoint logic.
    Handles primary and fallback LLM calls, simulates error handling.
    """
    def _endpoint(user_prompt):
        try:
            return mock_llm_primary(user_prompt)
        except Exception as e:
            # Try fallback model
            try:
                return mock_llm_fallback(user_prompt)
            except Exception as fallback_e:
                # Simulate 500 error response
                return {"error": "LLM service unavailable"}, 500
    return _endpoint

@pytest.mark.performance
def test_performance_llm_endpoint_latency(mock_llm_endpoint):
    """
    Performance test for /api/assistant/llm endpoint.
    - Sends multiple concurrent POST requests with varied user_prompt payloads.
    - Measures latency distribution and error rate.
    - Asserts 95th percentile latency < 5s, error rate <= 5%, and fallback model is used if primary fails.
    """
    NUM_REQUESTS = 50
    prompts = [
        f"user_prompt_{i}" for i in range(NUM_REQUESTS // 2)
    ] + [
        f"user_prompt_timeout_{i}" for i in range(NUM_REQUESTS // 4)
    ] + [
        f"user_prompt_fail_{i}" for i in range(NUM_REQUESTS // 8)
    ] + [
        f"user_prompt_fallback_fail_{i}" for i in range(NUM_REQUESTS // 8)
    ]
    # Shuffle prompts for randomness
    import random
    random.shuffle(prompts)

    latencies = []
    errors = 0
    fallback_used = 0

    def call_llm(prompt):
        start = time.time()
        response = mock_llm_endpoint(prompt)
        latency = time.time() - start
        latencies.append(latency)
        # Check for error response
        if isinstance(response, tuple) and response[1] == 500:
            errors += 1
        elif isinstance(response, dict) and "Fallback" in response.get("result", ""):
            fallback_used += 1
        return response

    # Run requests concurrently using asyncio
    async def run_requests():
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, call_llm, prompt)
            for prompt in prompts
        ]
        await asyncio.gather(*tasks)

    # Run the async test
    asyncio.run(run_requests())

    # Calculate metrics
    latencies_sorted = sorted(latencies)
    p95_latency = latencies_sorted[int(0.95 * len(latencies)) - 1]
    error_rate = errors / len(prompts)

    # Assertions
    assert p95_latency < 5.0, f"95th percentile latency {p95_latency:.2f}s exceeds 5s"
    assert error_rate <= 0.05, f"Error rate {error_rate*100:.1f}% exceeds 5%"
    # Fallback model should be used for failed primary calls, but no user-facing errors except fallback failures
    assert fallback_used > 0, "Fallback model was not used for failed primary LLM calls"

    # Check that only fallback_fail prompts resulted in user-facing errors
    fallback_fail_count = sum(1 for p in prompts if "fallback_fail" in p)
    assert errors == fallback_fail_count, (
        f"Expected {fallback_fail_count} fallback failures, got {errors} errors"
    )
