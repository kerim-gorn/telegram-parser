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
2. **Subcategories:** Only specify subcategories if they are clearly inferred from the text. If a domain is clear but the subcategory is vague, leave the subcategories list empty. Подкатегории доменов необходимо указывать, только если они однозначно определяются из сообщения (их также может быть несколько).
3. **Reasoning:** Be concise. Focus on *why* a specific urgency or intent was chosen (e.g., "Contains 'SOS', implies danger" or "User asks for price, so it's a REQUEST").
4. **Accuracy:** Pay special attention to the `is_spam` flag and `urgency_score` definitions provided in the schema descriptions.
5. **Instruction:** Для каждого сообщения необходимо определить его принадлежность к интентам и доменам, включая подкатегории доменов. Сообщение может относиться к нескольким интентам и доменам одновременно.

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
    REAL_ESTATE_AGENT = "REAL_ESTATE_AGENT"
    LAW = "LAW"
    SERVICES = "SERVICES"
    AUTO = "AUTO"
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
            "1. CONSTRUCTION_AND_REPAIR:\n"
            "   - MAJOR_RENOVATION: Крупный ремонт - один из первых этапов в ремонте квартиры или строительстве дома, длительные работы с большим чеком\n"
            "   - REPAIR_SERVICES: Ремонтные услуги - стяжка пола, услуги плиточника или маляра, установка окон, потолки, приемка квартиры\n"
            "2. RENTAL_OF_REAL_ESTATE:\n"
            "   - RENTAL_APARTMENT: Квартира\n"
            "   - RENTAL_HOUSE: Дом, коттедж, дача\n"
            "   - RENTAL_PARKING: Машиноместо, парковочное место\n"
            "   - RENTAL_STORAGE: Кладовая\n"
            "   - RENTAL_LAND: Участок\n"
            "3. PURCHASE_OF_REAL_ESTATE:\n"
            "   - PURCHASE_APARTMENT: Квартира\n"
            "   - PURCHASE_HOUSE: Дом, коттедж, дача\n"
            "   - PURCHASE_PARKING: Машиноместо, парковочное место\n"
            "   - PURCHASE_STORAGE: Кладовая\n"
            "   - PURCHASE_LAND: Участок\n"
            "4. REAL_ESTATE_AGENT:\n"
            "   - AGENT: Менеджер по продаже недвижимости, риелтор, риелторское агентство, брокер недвижимости\n"
            "5. LAW:\n"
            "   - LAWYER: Юридическая помощь, услуги юриста, юридические консультации и представительство, составление договоров\n"
            "6. SERVICES:\n"
            "   - BEAUTY_AND_HEALTH: Красота и здоровье - маникюр на дому, парикмахеры, массаж, брови, салон рядом\n"
            "   - HOUSEHOLD_SERVICES: Бытовые услуги - клининг, химчистка, \"муж на час\", ремонт одежды\n"
            "   - CHILD_CARE_AND_EDUCATION: Обучение и присмотр за детьми - репетиторы, няни, детские кружки, логопеды, детские сады\n"
            "   - DELIVERY_SERVICES: Доставка и курьерская служба - доставка еды, лекарств, покупок, посылок\n"
            "   - TECH_REPAIR: Ремонт техники - починка стиралки, ремонт компьютера, настройка роутера\n"
            "7. AUTO:\n"
            "   - AUTO_PURCHASE: Покупка автомобиля - подбор машины, пригон автомобиля, его приобретение\n"
            "   - AUTO_PREMIUM_DETAILING: Дорогостоящий детейлинг - обклейка или покраска автомобиля, другие дорогостоящие услуги из той же области\n"
            "   - AUTO_REPAIR: Ремонт автомобиля - замена каких-либо деталей, работа с кузовом и подобное\n"
            "   - AUTO_SERVICE_STATION: СТО, шиномонтаж и мелкие работы - шиномонтаж, мелкий ремонт, техническое обслуживание\n"
            "8. MARKETPLACE:\n"
            "   - BUY_SELL_GOODS: Купля-продажа вещей - детский товары, мебель, техника\n"
            "   - GIVE_AWAY: Дарение - отдам даром, избавление вещей за самовывоз или \"шоколадку\"\n"
            "   - HOMEMADE_FOOD: Домашняя еда - Торты на заказ, пельмени, фермерские продукты\n"
            "   - BUYER_SERVICES: Услуги байеров - заказ различных товаров из-за рубежа, совместные закупки\n"
            "9. SOCIAL_CAPITAL:\n"
            "   - PARENTING: Родительство - обсуждение поликлиник, прививок, школ, детских площадок\n"
            "   - HOBBY_AND_SPORT: Хобби и спорт - Поиск партнеров для бега, тенниса, настольных игр, выгул собак\n"
            "   - EVENTS: События - субботники, праздники двора, собрания\n"
            "10. OPERATIONAL_MANAGEMENT:\n"
            "   - LOST_AND_FOUND: Бюро находок - ключи, карты, животные, игрушки\n"
            "   - SECURITY: Безопасность - посторонние, открытые двери, пожарная сигнализация\n"
            "   - LIVING_ENVIRONMENT: Среда обитания - мусор, запахи, озеленение, шум\n"
            "   - MANAGEMENT_COMPANY_INTERACTION: Взаимодействие с УК - жалобы, предложения, обсуждение тарифов\n"
            "11. REPUTATION:\n"
            "   - PERSONAL_BRAND: Личный бренд - обсуждение конкретной личности\n"
            "   - COMPANIES_REPUTATION: Застройщики, ЖК, УК\n"
            "12. NONE: нет подходящего домена"
        )
    )


class ClassifiedMessage(BaseModel):
    """Classification result for a single message."""
    id: str = Field(..., description="Unique message ID from input.")
    
    intents: List[IntentType] = Field(
        ..., 
        description=(
            "Detect user intentions:\n"
            "- REQUEST: пользователь ищет или запрашивает товар, услугу, исполнителя или конкретную информацию для решения своей задачи. Это ценные сообщения‑лиды: в тексте явно или неявно есть потребность, и на такое сообщение уместно ответить рекомендацией (поделиться контактом, к кому обратиться; что и где выбрать).\n"
            "- OFFER: пользователь предлагает товар, услугу или свои навыки/компанию (продажа, реклама, самопрезентация). Фокус на том, что человек что-то даёт или продаёт, а не ищет.\n"
            "- RECOMMENDATION: пользователь делится советом или отзывом и рекомендует конкретного исполнителя, сервис, место или продукт (например: «советую врача X», «очень понравился сервис Y»).\n"
            "- COMPLAINT: пользователь выражает негатив, недовольство или жалобу на продукт, услугу, компанию, человека или ситуацию (проблемы, плохой опыт, «всё плохо»).\n"
            "- INFO: пользователь даёт нейтральную информацию или факт, без явного запроса, предложения, рекомендации или жалобы (новости, пояснения, уточнения, просто делится данными).\n"
            "- OTHER: приветствия, смайлики без текста, оффтоп, бессмысленные или слишком короткие сообщения, по которым нельзя надёжно определить один из других интентов."
        )
    )
    
    domains: List[DomainInfo] = Field(..., description="List of relevant domains and their subcategories.")
    
    is_spam: bool = Field(
        ..., 
        description="True, если сообщение имеет признаки массовой рассылки, обилие эмодзи, ссылки на внешние каналы, и явно не от жителя."
    )
    
    urgency_score: int = Field(
        ..., 
        description=(
            "Значение в диапазоне [1, 5], где:\n"
            "5: чрезвычайное происшествие (пожар, потоп, драка)\n"
            "4: срочная проблема (застрял лифт, нет воды)\n"
            "3: стандартный вопрос/проблема\n"
            "1-2: обычное несрочное информирование (обсуждение булочной)"
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

