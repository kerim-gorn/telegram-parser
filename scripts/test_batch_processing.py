"""
Test script for batch message processing functionality.
Tests batch LLM analyzer, prefilter integration, signal detection, and batch persistence logic.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Ensure project root is on sys.path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Mock aio_pika before importing workers (since it might not be installed in test environment)
sys.modules["aio_pika"] = Mock()
sys.modules["aio_pika.abc"] = Mock()

from app.batch_llm_analyzer import analyze_messages_batch
from workers.ingestor_worker import (
    _extract_message_data,
    _is_signal_from_classification,
    _process_batch,
    _persist_batch,
)


def create_mock_payload(chat_id: int, message_id: int, text: str, sender_id: int | None = None) -> dict[str, Any]:
    """Create a mock message payload."""
    return {
        "chat_id": chat_id,
        "message_id": message_id,
        "sender_username": f"@user{message_id}",
        "chat_username": "@test_chat",
        "message": {
            "id": message_id,
            "message": text,
            "from_id": {"_": "PeerUser", "user_id": sender_id} if sender_id else None,
            "date": datetime.now(tz=timezone.utc).isoformat(),
            "peer_id": {"_": "PeerChannel", "channel_id": chat_id},
        },
    }


INTENT_CODE = {
    "REQUEST": 1,
    "OFFER": 2,
    "RECOMMENDATION": 3,
    "COMPLAINT": 4,
    "INFO": 5,
    "OTHER": 6,
}

DOMAIN_CODE = {
    "CONSTRUCTION_AND_REPAIR": 1,
    "RENTAL_OF_REAL_ESTATE": 2,
    "PURCHASE_OF_REAL_ESTATE": 3,
    "REAL_ESTATE_AGENT": 4,
    "LAW": 5,
    "SERVICES": 6,
    "AUTO": 7,
    "MARKETPLACE": 8,
    "SOCIAL_CAPITAL": 9,
    "OPERATIONAL_MANAGEMENT": 10,
    "REPUTATION": 11,
    "NONE": 12,
}

SUBCATEGORY_CODE = {
    "CONSTRUCTION_AND_REPAIR": {"REPAIR_SERVICES": 2},
    "OPERATIONAL_MANAGEMENT": {"SECURITY": 2},
    "MARKETPLACE": {"BUY_SELL_GOODS": 1},
}


def create_mock_llm_response(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Create a mock LLM response in full (decoded) format."""
    classified = []
    for msg in messages:
        msg_id = msg["id"]
        text = msg.get("text", "")
        
        # Simple logic for testing
        if "электрик" in text.lower() or "мастер" in text.lower():
            intents = ["REQUEST"]
            domains = [{"domain": "CONSTRUCTION_AND_REPAIR", "subcategories": ["REPAIR_SERVICES"]}]
            urgency = 3
        elif "срочно" in text.lower() or "пожар" in text.lower():
            intents = ["COMPLAINT", "INFO"]
            domains = [
                {"domain": "OPERATIONAL_MANAGEMENT", "subcategories": ["SECURITY"]},
                {"domain": "CONSTRUCTION_AND_REPAIR", "subcategories": ["REPAIR_SERVICES"]},
            ]
            urgency = 5
        elif "продам" in text.lower() or "куплю" in text.lower():
            intents = ["OFFER", "REQUEST"]
            domains = [{"domain": "MARKETPLACE", "subcategories": ["BUY_SELL_GOODS"]}]
            urgency = 1
        else:
            intents = ["INFO"]
            domains = [{"domain": "NONE", "subcategories": []}]
            urgency = 1
        
        classified.append({
            "id": msg_id,
            "intents": intents,
            "domains": domains,
            "is_spam": False,
            "urgency_score": urgency,
            "reasoning": f"Test classification for message {msg_id}",
        })
    
    return {
        "ok": True,
        "data": {"classified_messages": classified},
        "raw": {"choices": [{"message": {"content": json.dumps({"classified_messages": classified})}}]},
    }


def create_mock_llm_compact_payload(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Create a mock LLM API response in compact format."""
    compact_messages = []
    for msg in messages:
        msg_id = msg["id"]
        text = msg.get("text", "")
        
        if "электрик" in text.lower() or "мастер" in text.lower():
            intents = ["REQUEST"]
            domains = [{"domain": "CONSTRUCTION_AND_REPAIR", "subcategories": ["REPAIR_SERVICES"]}]
            urgency = 3
        elif "срочно" in text.lower() or "пожар" in text.lower():
            intents = ["COMPLAINT", "INFO"]
            domains = [
                {"domain": "OPERATIONAL_MANAGEMENT", "subcategories": ["SECURITY"]},
                {"domain": "CONSTRUCTION_AND_REPAIR", "subcategories": ["REPAIR_SERVICES"]},
            ]
            urgency = 5
        elif "продам" in text.lower() or "куплю" in text.lower():
            intents = ["OFFER", "REQUEST"]
            domains = [{"domain": "MARKETPLACE", "subcategories": ["BUY_SELL_GOODS"]}]
            urgency = 1
        else:
            intents = ["INFO"]
            domains = [{"domain": "NONE", "subcategories": []}]
            urgency = 1
        
        compact_domains = []
        for domain in domains:
            domain_name = domain["domain"]
            subcats = domain.get("subcategories", [])
            subcat_map = SUBCATEGORY_CODE.get(domain_name, {})
            subcat_codes = []
            for subcat in subcats:
                code = subcat_map.get(subcat)
                if code is None:
                    raise AssertionError(f"Missing subcategory code for {domain_name}:{subcat}")
                subcat_codes.append(code)
            compact_domains.append({
                "d": DOMAIN_CODE[domain_name],
                "s": subcat_codes,
            })
        
        compact_messages.append({
            "i": msg_id,
            "t": [INTENT_CODE[intent] for intent in intents],
            "d": compact_domains,
            "p": False,
            "u": urgency,
            "r": f"Test msg {msg_id}",
        })
    
    return {
        "choices": [{"message": {"content": json.dumps({"m": compact_messages})}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }


async def test_extract_message_data() -> None:
    """Test message data extraction."""
    print("\n[TEST] test_extract_message_data")
    
    payload = create_mock_payload(chat_id=12345, message_id=1, text="Test message", sender_id=67890)
    data = _extract_message_data(payload)
    
    assert data is not None, "Should extract message data"
    assert data["chat_id"] == 12345
    assert data["message_id"] == 1
    assert data["text"] == "Test message"
    assert data["sender_id"] == 67890
    assert data["sender_username"] == "@user1"
    assert data["chat_username"] == "@test_chat"
    
    print("  ✓ Message data extraction works correctly")


def test_is_signal_from_classification() -> None:
    """Test signal detection logic."""
    print("\n[TEST] test_is_signal_from_classification")
    
    # Test REQUEST + CONSTRUCTION_AND_REPAIR (should be signal)
    assert _is_signal_from_classification(
        ["REQUEST"],
        [{"domain": "CONSTRUCTION_AND_REPAIR", "subcategories": ["REPAIR_SERVICES"]}],
    ), "REQUEST + CONSTRUCTION_AND_REPAIR should be signal"
    
    # Test REQUEST + SERVICES (should be signal)
    assert _is_signal_from_classification(
        ["REQUEST"],
        [{"domain": "SERVICES", "subcategories": ["BEAUTY_AND_HEALTH"]}],
    ), "REQUEST + SERVICES should be signal"
    
    # Test REQUEST + MARKETPLACE (should NOT be signal)
    assert not _is_signal_from_classification(
        ["REQUEST"],
        [{"domain": "MARKETPLACE", "subcategories": ["BUY_SELL_GOODS"]}],
    ), "REQUEST + MARKETPLACE should NOT be signal"
    
    # Test OFFER (should NOT be signal)
    assert not _is_signal_from_classification(
        ["OFFER"],
        [{"domain": "CONSTRUCTION_AND_REPAIR", "subcategories": []}],
    ), "OFFER should NOT be signal"
    
    # Test empty intents/domains
    assert not _is_signal_from_classification(None, None), "Empty should NOT be signal"
    assert not _is_signal_from_classification([], []), "Empty lists should NOT be signal"
    
    print("  ✓ Signal detection logic works correctly")


async def test_batch_llm_analyzer() -> None:
    """Test batch LLM analyzer with mocked API."""
    print("\n[TEST] test_batch_llm_analyzer")
    
    messages = [
        {"id": "12345_1", "text": "Нужен электрик для ремонта"},
        {"id": "12345_2", "text": "Срочно! Пожар в подъезде!"},
        {"id": "12345_3", "text": "Продам диван"},
    ]
    
    mock_response = create_mock_llm_response(messages)
    
    with patch("app.batch_llm_analyzer.get_openrouter_client") as mock_client:
        # Mock httpx client
        mock_http_client = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json.return_value = create_mock_llm_compact_payload(messages)
        mock_response_obj.raise_for_status = MagicMock()
        mock_http_client.post = AsyncMock(return_value=mock_response_obj)
        mock_client.return_value = mock_http_client
        
        # Set API key
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test_key", "LLM_MODEL_NAME": "test_model"}):
            result = await analyze_messages_batch(messages)
        
        assert result["ok"] is True, "LLM analysis should succeed"
        assert "data" in result, "Result should contain data"
        assert "classified_messages" in result["data"], "Data should contain classified_messages"
        assert len(result["data"]["classified_messages"]) == 3, "Should classify all 3 messages"
        
        # Check first message (should be REQUEST + CONSTRUCTION_AND_REPAIR)
        first = result["data"]["classified_messages"][0]
        assert "REQUEST" in first["intents"], "First message should have REQUEST intent"
        
        print("  ✓ Batch LLM analyzer works correctly")


async def test_process_batch_with_prefilter() -> None:
    """Test batch processing with prefilter."""
    print("\n[TEST] test_process_batch_with_prefilter")
    
    payloads = [
        create_mock_payload(12345, 1, "Срочно нужен электрик"),  # Should match force rule
        create_mock_payload(12345, 2, "Продам диван"),  # Should match skip rule
        create_mock_payload(12345, 3, "Нужен мастер по ремонту"),  # Should go to LLM
        create_mock_payload(12345, 4, ""),  # Empty text
    ]
    
    # Mock prefilter
    async def mock_prefilter_match(text: str) -> tuple[str | None, list[str]]:
        if "электрик" in text.lower() or "срочно" in text.lower():
            return "force", ["test_force_rule"]
        elif "продам" in text.lower():
            return "skip", ["test_skip_rule"]
        return None, []
    
    # Mock LLM analyzer
    async def mock_analyze_batch(msgs: list[dict[str, str]]) -> dict[str, Any]:
        return create_mock_llm_response(msgs)
    
    with patch("workers.ingestor_worker.get_prefilter") as mock_prefilter_class, patch(
        "workers.ingestor_worker.analyze_messages_batch", side_effect=mock_analyze_batch
    ):
        mock_prefilter_instance = MagicMock()
        mock_prefilter_instance.match = AsyncMock(side_effect=mock_prefilter_match)
        mock_prefilter_class.return_value = mock_prefilter_instance
        
        results = await _process_batch(payloads)
    
    assert len(results) == 4, "Should process all 4 messages"
    
    # Check forced message
    forced_result = results[0]
    assert forced_result["prefilter_decision"] == "force"
    assert forced_result["intents"] == ["REQUEST"]
    assert forced_result["urgency_score"] == 3
    
    # Check skipped message
    skipped_result = results[1]
    assert skipped_result["prefilter_decision"] == "skip"
    assert skipped_result["intents"] == ["OTHER"]
    assert skipped_result["urgency_score"] == 1
    
    # Check LLM processed message
    llm_result = results[2]
    assert llm_result["prefilter_decision"] is None
    assert "REQUEST" in llm_result["intents"] or "REQUEST" in llm_result.get("intents", [])
    
    # Check empty text message
    empty_result = results[3]
    assert empty_result["intents"] == ["OTHER"]
    assert empty_result["urgency_score"] == 1
    
    print("  ✓ Batch processing with prefilter works correctly")


async def test_persist_batch_logic() -> None:
    """Test batch persistence logic (without actual DB)."""
    print("\n[TEST] test_persist_batch_logic")
    
    # Create mock results
    results = [
        {
            "msg_data": {
                "chat_id": 12345,
                "message_id": 1,
                "sender_id": 67890,
                "sender_username": "@user1",
                "chat_username": "@test_chat",
                "text": "Нужен электрик",
                "message_date": datetime.now(tz=timezone.utc),
            },
            "prefilter_decision": None,
            "intents": ["REQUEST"],
            "domains": [{"domain": "CONSTRUCTION_AND_REPAIR", "subcategories": ["REPAIR_SERVICES"]}],
            "is_spam": False,
            "urgency_score": 3,
            "reasoning": "Test reasoning",
            "llm_analysis": {"ok": True},
        },
        {
            "msg_data": {
                "chat_id": 12345,
                "message_id": 2,
                "sender_id": 67891,
                "sender_username": "@user2",
                "chat_username": "@test_chat",
                "text": "Привет",
                "message_date": datetime.now(tz=timezone.utc),
            },
            "prefilter_decision": "skip",
            "intents": ["OTHER"],
            "domains": [{"domain": "NONE", "subcategories": []}],
            "is_spam": False,
            "urgency_score": 1,
            "reasoning": "Filtered",
            "llm_analysis": {"ok": True, "filtered": True},
        },
    ]
    
    from collections import defaultdict
    
    stats: dict[str, Any] = {
        "persisted": 0,
        "failed": 0,
        "notifications_sent": 0,
        "forced": 0,
        "filtered": 0,
        "urgency_distribution": defaultdict(int),
    }
    
    # Mock database operations - create proper async context manager
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    
    mock_engine = AsyncMock()
    # Mock begin() to return an async context manager
    @asynccontextmanager
    async def mock_begin():
        yield mock_conn
    
    mock_engine.begin = mock_begin
    mock_engine.dispose = AsyncMock()
    
    with patch("workers.ingestor_worker.create_loop_bound_session_factory") as mock_factory, patch(
        "workers.ingestor_worker.signal_notifier"
    ) as mock_notifier:
        mock_factory.return_value = (mock_engine, None)
        mock_notifier.send_signal = AsyncMock()
        
        # Mock asyncio.create_task for notifications
        with patch("asyncio.create_task") as mock_create_task:
            await _persist_batch(results, stats)
            
            # Check stats
            assert stats["persisted"] == 2, "Should persist 2 messages"
            assert stats["filtered"] == 1, "Should count 1 filtered message"
            assert 3 in stats["urgency_distribution"], "Should track urgency_score=3"
            assert stats["notifications_sent"] == 1, "Should send 1 notification (REQUEST + CONSTRUCTION_AND_REPAIR)"
            
            # Check that notification was triggered for signal message
            assert mock_create_task.called, "Should create task for notification"
    
    print("  ✓ Batch persistence logic works correctly")


async def test_full_batch_flow() -> None:
    """Test full batch processing flow."""
    print("\n[TEST] test_full_batch_flow")
    
    # Create batch of messages
    payloads = [
        create_mock_payload(12345, i, f"Message {i}: Нужен мастер по ремонту") for i in range(1, 6)
    ]
    
    # Mock LLM
    async def mock_analyze_batch(msgs: list[dict[str, str]]) -> dict[str, Any]:
        return create_mock_llm_response(msgs)
    
    # Mock prefilter (no matches)
    async def mock_prefilter_match(text: str) -> tuple[str | None, list[str]]:
        return None, []
    
    with patch("workers.ingestor_worker.get_prefilter") as mock_prefilter_class, patch(
        "workers.ingestor_worker.analyze_messages_batch", side_effect=mock_analyze_batch
    ):
        mock_prefilter_instance = MagicMock()
        mock_prefilter_instance.match = AsyncMock(side_effect=mock_prefilter_match)
        mock_prefilter_class.return_value = mock_prefilter_instance
        
        results = await _process_batch(payloads)
    
    assert len(results) == 5, "Should process all 5 messages"
    
    # Check that all messages were classified
    for result in results:
        assert "intents" in result, "Each result should have intents"
        assert "domains" in result, "Each result should have domains"
        assert "urgency_score" in result, "Each result should have urgency_score"
        assert result["prefilter_decision"] is None, "No prefilter matches expected"
    
    print("  ✓ Full batch flow works correctly")


async def main() -> None:
    """Run all tests."""
    print("=" * 70)
    print("Testing Batch Message Processing Functionality")
    print("=" * 70)
    
    try:
        # Unit tests (synchronous)
        test_extract_message_data()
        test_is_signal_from_classification()
        
        # Integration tests
        await test_batch_llm_analyzer()
        await test_process_batch_with_prefilter()
        await test_persist_batch_logic()
        await test_full_batch_flow()
        
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

