"""
Message classification schema and types for LLM batch processing.
"""
from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, Field


# System prompt for LLM classification
SYSTEM_PROMPT_TEXT = """
Role:
You are an advanced AI classifier specializing in analyzing community chat messages.

Task:
You will receive a list of messages in JSON format. Your goal is to map each message to the correct Intents, Domains, and Flags according to the strict JSON Schema provided in the output format.

### Guidelines
1. **Multi-labeling:** A message can have multiple Intents and Domains.
2. **Subcategories:** Only specify subcategories if they are clearly inferred from the text. If a domain is clear but the subcategory is vague, leave the subcategories list empty.
3. **Reasoning:** Be concise. Focus on *why* a specific urgency or intent was chosen (e.g., "Contains 'SOS', implies danger" or "User asks for price, so it's a REQUEST").
4. **Accuracy:** Pay special attention to the `is_spam` flag and `urgency_score` definitions provided in the schema descriptions.

### Few-Shot Examples

User Input:
[
  {"id": "1", "text": "Срочно! В 3 подъезде прорвало трубу, вода хлещет на площадку!"},
  {"id": "2", "text": "Посоветуйте хорошего мастера по маникюру, который выезжает на дом."}
]

Model Output:
{
  "classified_messages": [
    {
      "id": "1",
      "intents": ["COMPLAINT", "INFO"],
      "domains": [
        {"domain": "CONSTRUCTION_AND_REPAIR", "subcategories": ["REPAIR_SERVICES"]},
        {"domain": "OPERATIONAL_MANAGEMENT", "subcategories": ["LIVING_ENVIRONMENT"]}
      ],
      "is_spam": false,
      "urgency_score": 5,
      "reasoning": "Direct report of a major accident (flood), highly urgent."
    },
    {
      "id": "2",
      "intents": ["REQUEST"],
      "domains": [{"domain": "SERVICES", "subcategories": ["BEAUTY_AND_HEALTH"]}],
      "is_spam": false,
      "urgency_score": 1,
      "reasoning": "User is asking for a beauty service recommendation."
    }
  ]
}
"""


# Enums for classification
class IntentType(str, Enum):
    """Message intent types."""
    REQUEST = "REQUEST"
    OFFER = "OFFER"
    RECOMMENDATION = "RECOMMENDATION"
    COMPLAINT = "COMPLAINT"
    INFO = "INFO"
    OTHER = "OTHER"


class DomainType(str, Enum):
    """Message domain types."""
    CONSTRUCTION_AND_REPAIR = "CONSTRUCTION_AND_REPAIR"
    RENTAL_OF_REAL_ESTATE = "RENTAL_OF_REAL_ESTATE"
    PURCHASE_OF_REAL_ESTATE = "PURCHASE_OF_REAL_ESTATE"
    SERVICES = "SERVICES"
    MARKETPLACE = "MARKETPLACE"
    SOCIAL_CAPITAL = "SOCIAL_CAPITAL"
    OPERATIONAL_MANAGEMENT = "OPERATIONAL_MANAGEMENT"
    REPUTATION = "REPUTATION"
    NONE = "NONE"


# Pydantic models for classification
class DomainInfo(BaseModel):
    """Domain information with optional subcategories."""
    domain: DomainType = Field(
        ..., 
        description="Select the most relevant high-level domain."
    )
    subcategories: List[str] = Field(
        default_factory=list,
        description=(
            "Specific subcategories inferred from text. Use EXACT names from this list based on the domain:\n"
            "1. CONSTRUCTION_AND_REPAIR: [MAJOR_RENOVATION, REPAIR_SERVICES]\n"
            "2. RENTAL_OF_REAL_ESTATE: [RENTAL_APARTMENT, RENTAL_HOUSE, RENTAL_PARKING, RENTAL_STORAGE, RENTAL_LAND]\n"
            "3. PURCHASE_OF_REAL_ESTATE: [PURCHASE_APARTMENT, PURCHASE_HOUSE, PURCHASE_PARKING, PURCHASE_STORAGE, PURCHASE_LAND]\n"
            "4. SERVICES: [BEAUTY_AND_HEALTH, HOUSEHOLD_SERVICES, CHILD_CARE_AND_EDUCATION, AUTO_SERVICES, DELIVERY_SERVICES, TECH_REPAIR]\n"
            "5. MARKETPLACE: [BUY_SELL_GOODS, GIVE_AWAY, HOMEMADE_FOOD, BUYER_SERVICES]\n"
            "6. SOCIAL_CAPITAL: [PARENTING, HOBBY_AND_SPORT, EVENTS]\n"
            "7. OPERATIONAL_MANAGEMENT: [LOST_AND_FOUND, SECURITY, LIVING_ENVIRONMENT, MANAGEMENT_COMPANY_INTERACTION]\n"
            "8. REPUTATION: [PERSONAL_BRAND, COMPANIES_REPUTATION]"
        )
    )


class ClassifiedMessage(BaseModel):
    """Classification result for a single message."""
    id: str = Field(..., description="Unique message ID from input.")
    
    intents: List[IntentType] = Field(
        ..., 
        description=(
            "Detect user intentions:\n"
            "- REQUEST: Looking for product/service/info (Lead).\n"
            "- OFFER: Offering product/service.\n"
            "- RECOMMENDATION: Advising a specific performer/place.\n"
            "- COMPLAINT: Negative feedback or problem report.\n"
            "- INFO: Neutral information.\n"
            "- OTHER: Greetings, emojis, meaningless."
        )
    )
    
    domains: List[DomainInfo] = Field(..., description="List of relevant domains and their subcategories.")
    
    is_spam: bool = Field(
        ..., 
        description="True if message has signs of mass mailing, excessive emojis, external links, or is clearly not from a resident."
    )
    
    urgency_score: int = Field(
        ..., 
        description=(
            "Urgency level (1-5):\n"
            "5: Emergency (fire, flood, fight, danger).\n"
            "4: Urgent problem (elevator stuck, no water).\n"
            "3: Standard question/problem.\n"
            "1-2: Non-urgent chatter/info."
        )
    )
    
    reasoning: str = Field(
        ..., 
        description="Very brief logic (max 1 sentence) explaining the chosen Intents and Urgency."
    )


class ClassificationBatchResult(BaseModel):
    """Batch classification result containing multiple classified messages."""
    classified_messages: List[ClassifiedMessage]


def get_json_schema() -> dict:
    """
    Generate JSON schema for OpenRouter/OpenAI structured output.
    
    Returns:
        Dictionary with JSON schema format compatible with OpenRouter API.
    """
    schema = ClassificationBatchResult.model_json_schema()
    
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "classification_result",
            "strict": True,
            "schema": schema
        }
    }

