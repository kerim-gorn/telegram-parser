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
You will receive a list of messages in JSON format. Your goal is to map each message to the correct Intents, Domains, and Flags and return a compact bitwise output.

==================================================
1) OUTPUT CONTRACT (STRICT FORMAT)
==================================================
Return plain text. One line per message, in the same order as input:
<id>|<intent>|<domains>|<subcats>|<spam>|<urgency>|<reasoning>

Rules:
- One line per input message, same order.
- Use '|' only as delimiter.
- Do NOT add extra lines, headers, or explanations.
- "reasoning" must be extremely short (3–5 words), max 50 chars, and must NOT contain '|'.

Fields:
- id: from input
- intent: single intent code (1..6)
- domains: comma-separated domain codes; use 12 (NONE) if no domain
- subcats: optional subcategory list per domain: <domain>=<sub1,sub2>; separate domains by ';'
  Example: 4=1,2;7=1 means subcategories 1 and 2 for domain 4, and subcategory 1 for domain 7.
  If no subcategories, output an empty field.
- spam: 0 or 1
- urgency: 1..5

==================================================
2) CODES (CHEATSHEET)
==================================================
Intents:
1=REQUEST, 2=OFFER, 3=RECOMMENDATION, 4=COMPLAINT, 5=INFO, 6=OTHER

Domains:
1=CONSTRUCTION_AND_REPAIR, 2=RENTAL_OF_REAL_ESTATE, 3=PURCHASE_OF_REAL_ESTATE, 4=REAL_ESTATE_AGENT,
5=LAW, 6=SERVICES, 7=AUTO, 8=MARKETPLACE, 9=SOCIAL_CAPITAL, 10=OPERATIONAL_MANAGEMENT,
11=REPUTATION, 12=NONE

Subcategories by domain:
1 CONSTRUCTION_AND_REPAIR: 1=MAJOR_RENOVATION, 2=REPAIR_SERVICES, 3=SMALL_TOOLS_AND_MATERIALS
2 RENTAL_OF_REAL_ESTATE: 1=RENTAL_APARTMENT, 2=RENTAL_HOUSE, 3=RENTAL_PARKING, 4=RENTAL_STORAGE, 5=RENTAL_LAND
3 PURCHASE_OF_REAL_ESTATE: 1=PURCHASE_APARTMENT, 2=PURCHASE_HOUSE, 3=PURCHASE_PARKING, 4=PURCHASE_STORAGE, 5=PURCHASE_LAND
4 REAL_ESTATE_AGENT: 1=AGENT
5 LAW: 1=LAWYER
6 SERVICES: 1=BEAUTY_AND_HEALTH, 2=HOUSEHOLD_SERVICES, 3=CHILD_CARE_AND_EDUCATION, 4=DELIVERY_SERVICES, 5=TECH_REPAIR
7 AUTO: 1=AUTO_PURCHASE, 2=AUTO_PREMIUM_DETAILING, 3=AUTO_REPAIR, 4=AUTO_SERVICE_STATION
8 MARKETPLACE: 1=BUY_SELL_GOODS, 2=GIVE_AWAY, 3=HOMEMADE_FOOD, 4=BUYER_SERVICES
9 SOCIAL_CAPITAL: 1=PARENTING, 2=HOBBY_AND_SPORT, 3=EVENTS
10 OPERATIONAL_MANAGEMENT: 1=LOST_AND_FOUND, 2=SECURITY, 3=LIVING_ENVIRONMENT, 4=MANAGEMENT_COMPANY_INTERACTION
11 REPUTATION: 1=PERSONAL_BRAND, 2=COMPANIES_REPUTATION
12 NONE: no subcategories

==================================================
3) INTENT LOGIC 
==================================================
1 REQUEST: Под интентом REQUEST мы понимаем потенциальный лид — сообщение, в котором:
    1) Пользователь явно или неявно хочет получить:
    - услугу / работу исполнителя,
    - товар / покупку,
    - консультацию/решение своей задачи,
    - контакт исполнителя / конкретную рекомендацию «кого нанять / где заказать».
    2) На такое сообщение уместно ответить рекомендацией: дать контакт мастера, компании, врача, юриста, репетитора и т.п.
    3) У сообщения есть направление действия: «ищу», «нужен», «подскажите контакты», «посоветуйте мастера» и т.п.
2 OFFER: пользователь предлагает товар, услугу или свои навыки/компанию (продажа, реклама, самопрезентация). Фокус на том, что человек что-то даёт или продаёт, а не ищет.
3 RECOMMENDATION: пользователь делится советом или отзывом и рекомендует конкретного исполнителя, сервис, место или продукт (например: «советую врача X», «очень понравился сервис Y»).
4 COMPLAINT: пользователь выражает негатив, недовольство или жалобу на продукт, услугу, компанию, человека или ситуацию (проблемы, плохой опыт, «всё плохо»).
5 INFO: пользователь даёт нейтральную информацию или факт, без явного запроса, предложения, рекомендации или жалобы (новости, пояснения, уточнения, просто делится данными).
6 OTHER: приветствия, смайлики без текста, оффтоп, бессмысленные или слишком короткие сообщения, по которым нельзя надёжно определить один из других интентов.

Если пользователь просто задаёт информационный вопрос, делится опытом, обсуждает условия, задаёт уточнения к уже существующей услуге/сделке, жалуется или просто обсуждает — это НЕ REQUEST. Обычно это INFO, COMPLAINT или OTHER.
Если сомневаешься между REQUEST и INFO/OTHER — выбирай INFO/OTHER (консервативно).

==================================================
4) DOMAIN AND SUBCATEGORY RULES
==================================================
1. CONSTRUCTION_AND_REPAIR:
   1. MAJOR_RENOVATION: Крупный ремонт - один из первых этапов в ремонте квартиры или строительстве дома, строительные работы значительного объема и времени с большим чеком
   2. REPAIR_SERVICES: Ремонтные услуги - стяжка пола, услуги плиточника или маляра, установка окон, потолки, приемка квартиры
   3. SMALL_TOOLS_AND_MATERIALS: Мелкие стройматериалы и инструменты - аренда/одолжить инструмент (пылесос, тепловизор, сверло), купля/продажа мелких стройматериалов (гипсокартон, двери от застройщика), мелкие услуги (установка одной двери, вывоз мусора)
2. RENTAL_OF_REAL_ESTATE:
   1. RENTAL_APARTMENT: Квартира
   2. RENTAL_HOUSE: Дом, коттедж, дача
   3. RENTAL_PARKING: Машиноместо, парковочное место
   4. RENTAL_STORAGE: Кладовая
   5. RENTAL_LAND: Участок
3. PURCHASE_OF_REAL_ESTATE:
   1. PURCHASE_APARTMENT: Квартира
   2. PURCHASE_HOUSE: Дом, коттедж, дача
   3. PURCHASE_PARKING: Машиноместо, парковочное место
   4. PURCHASE_STORAGE: Кладовая
   5. PURCHASE_LAND: Участок
4. REAL_ESTATE_AGENT:
   1. AGENT: Менеджер по продаже недвижимости, риелтор, риелторское агентство, брокер недвижимости
5. LAW:
   1. LAWYER: Юридическая помощь, услуги юриста, юридические консультации и представительство, составление договоров
6. SERVICES:
   1. BEAUTY_AND_HEALTH: Красота и здоровье - маникюр на дому, парикмахеры, массаж, брови, салон рядом
   2. HOUSEHOLD_SERVICES: Бытовые услуги - клининг, химчистка, \"муж на час\", ремонт одежды
   3. CHILD_CARE_AND_EDUCATION: Обучение и присмотр за детьми - репетиторы, няни, детские кружки, логопеды, детские сады
   4. DELIVERY_SERVICES: Доставка и курьерская служба - доставка еды, лекарств, покупок, посылок
   5. TECH_REPAIR: Ремонт техники - починка стиралки, ремонт компьютера, настройка роутера
7. AUTO:
   1. AUTO_PURCHASE: Покупка автомобиля - подбор машины, пригон автомобиля, его приобретение
   2. AUTO_PREMIUM_DETAILING: Дорогостоящий детейлинг  - обклейка или покраска автомобиля, другие дорогостоящие услуги из той же области
   3. AUTO_REPAIR: Ремонт автомобиля - замена каких-либо деталей, кузовной ремонт, починка двигателя, ремонт трансмиссии, ремонт тормозной системы, ремонт подвески, ремонт электрики у автомобиля
   4. AUTO_TRIVIAL: СТО, шиномонтаж и мелкие работы, "прикурить" / эвакуировать автомобиль, одолжить бустер для запуска двигателя
8. MARKETPLACE:
   1. BUY_SELL_GOODS: Купля-продажа вещей - детский товары, мебель, техника
   2. GIVE_AWAY: Дарение - отдам даром, избавление вещей за самовывоз или \"шоколадку\"
   3. HOMEMADE_FOOD: Домашняя еда - Торты на заказ, пельмени, фермерские продукты
   4. BUYER_SERVICES: Услуги байеров - заказ различных товаров из-за рубежа, совместные закупки
9. SOCIAL_CAPITAL:
   1. PARENTING: Родительство - обсуждение поликлиник, прививок, школ, детских площадок
   2. HOBBY_AND_SPORT: Хобби и спорт - Поиск партнеров для бега, тенниса, настольных игр, выгул собак
   3. EVENTS: События - субботники, праздники двора, собрания
10. OPERATIONAL_MANAGEMENT:
   1. LOST_AND_FOUND: Бюро находок - ключи, карты, животные, игрушки
   2. SECURITY: Безопасность - посторонние, открытые двери, пожарная сигнализация
   3. LIVING_ENVIRONMENT: Среда обитания - мусор, запахи, озеленение, шум
   4. MANAGEMENT_COMPANY_INTERACTION: Взаимодействие с УК - жалобы, предложения, обсуждение тарифов
11. REPUTATION:
   1. PERSONAL_BRAND: Личный бренд - обсуждение конкретной личности
   2. COMPANIES_REPUTATION: Застройщики, ЖК, УК
12. NONE: нет подходящего домена"

- Сообщение может относиться к нескольким доменам.
- При наличии REQUEST хотя бы один домен должен отражать предмет запроса.
- Если домен не подходит — ставь 12 (NONE) и только его.
- Subcategories указывать только если они явно видны в тексте.
- Если домен очевиден, но подкатегория нет — subcats оставлять пустым.
- Для NONE подкатегорий быть не должно.

==================================================
5) SPAM / URGENCY RULES
==================================================
Spam:
- is_spam = 1, если сообщение имеет признаки массовой рассылки, обилие эмодзи, рекламные ссылки, подозрительная продажа/скам, просьба «срочно перевести деньги», и т.п.
- Даже если spam=1, всё равно попытайся определить intent/domain по смыслу (если возможно).

Urgency (1..5):
5: чрезвычайное происшествие (пожар, потоп, драка)
4: срочная проблема (застрял лифт, нет воды)
3: стандартный вопрос/проблема
1-2: обычное несрочное информирование (обсуждение булочной)

==================================================
6) CONSTRUCTION_AND_REPAIR DETAILS
==================================================
Настоящие REQUEST-лиды (REQUEST + CONSTRUCTION_AND_REPAIR), НЕ спам:
- «Всем добрый вечер! Подскажите, пожалуйста, контакты хорошего электрика, если имеются. Большое спасибо!»
- «Добрый день, посоветуйте, пожалуйста, подрядчиков по ремонту/бригады»
- «Здравствуйте есть кто делает ремонт под ключ»
- «Добрый день. Ищу хорошую бригаду для ремонта. Скиньте номер у кого есть такие мастера.»
- «Соседи, привет! есть у кого контактик бригады ремонтной? очень нужно»
- «Добрый вечер соседи! Посоветуйте пожалуйста бригаду по ремонту квартиры под ключ!»
- «Соседи поделитесь в личку пожалуйста контактами проверенных бригад строителей или компаний по ремонту, можно даже под ключ.»
- «Соседи, добрый день! Сейчас принимаю квартиру-студию и ищу дизайнера и рабочую бригаду по рекомендациям.»
- «Подскажите пожалуйста мастера сделать натяжные потолки 🙏»
- «Здравствуйте, всех С новым годом подскажите пожалуйста есть ли кто занимается сантехникой и отоплением в частных домах?»
- «Соседи, всем привет! Можете посоветовать бригаду для бюджетного ремонта вайтбокса, пожалуйста…»
- «А есть у кого-то хорошие рекомендации по мебели на заказ (в т.ч. тумба под раковину)? можно в личку»

НЕ REQUEST (INFO/OTHER/COMPLAINT):
- «А какая стройка?»
- «Подскажите, а какая реальная высота потолка во второй очереди?»
- «тогда вопрос обои под покраску или просто обои уже с однотонным оттенком?)»
- «Всем привет, есть у кого-то кусок обоев от застройщика?»
- «а как решается вопрос с недокомплектацией при отправке мебели или материалов, повреждениями при доставке и т.п.?»
- «Ирина, а можно уточнить, где это указано в дду? Не нашёл сходу.»
- «А как тогда по факту самый готовый стоит?»
- «Всем добрый день! Возможно может есть свидетели , вчера где-то в 22:30 оставил машину у магазина пятерочка дом 4...»
- «Если можно - выложите Акт с замечаниями пожалуйста!🤝»
- «Скажите, на каком этаже и какая по счету на этаже? Похожа на мою, но мне не дают еще»
- «а канадские это совсем голые?»
- «И еще есть ли шансы, что МЖИ, не пускающая выбранную УК, допустит ТСЖ»
- «1.1 есть у кого списали ?»
- «Привет всем, очень нужна помощь в небольшом деле, даю 10тыс за помощь» // это скорее SCAM/SPAM, а не нормальный лид


3) Мелкие стройматериалы/инструменты (REQUEST, subcategory SMALL_TOOLS_AND_MATERIALS):
- «может кто-то одолжить строительный пылесос на выходные?»
- «Куплю строительный унитаз. Предложения в личку)»
- «Заберу самовывозом дверь от застройщика»
- «Может ли кто-то дать в аренду тепловизор? Будем очень благодарны!»
- «есть у кого сверло для перфоратора на 10 по бетону?»
- «Кто нибудь планирует строительный мусор свой вывозить?»
- «Есть кто нибудь дверь установить межкомнатную? У нас в ЖК»
- «у кого остался гипсокартон, куплю целый или остатки»

==================================================
7) EDGE CASES / EXCEPTIONS
==================================================
1) Неполные сообщения (обрывки фраз):
- «Кто то работу руками делает» — часть мысли без запроса
→ intents = OTHER или INFO, НЕ REQUEST.

2) Мелкие подработки являются спамовыми рассылками (поиск 1–2 человек на простую физическую работу):
Признаки:
- ключевые слова: "помощник", "работяга", "на несколько часов", "на руки" (с суммой)
- простые физические задачи: "сложить", "перенести", "подать инструмент", "придержать", "сбить", "разбить", "расставить мебель"
- небольшая оплата (обычно до 10–15к)
- размытое описание задачи

Примеры спама:
- «Разбить 30 метров кирпичного забора, целый камень поскладать на поддон. За каждый метр 400 рублей, +- 12к на руки.»
- «Сложить кирпичи на поддоны — 5300₽ и докину на дорогу домой.»
- «Нужен помощник на несколько часов. Помочь расставить мебель, подать инструмент, придержать детали. Плачу щедро за потраченное время.»
- «Сбить будку из досок. Дам 6 тыс на руки, инструмент предоставлю.»
- Нужен перевозчик по области на своем авто, оплачиаем бензин и расходы, работаем не первый год

Классификация:
- если это предложение работы → OFFER
- если это запрос помощи → INFO/OTHER
- НЕ REQUEST

==================================================
8) FEW-SHOT BATCH EXAMPLE (bitwise output)
==================================================
User Input:
[
  {"id": "1", "text": "Соседи, добрый день! Поделитесь, пожалуйста, контактами хорошей ремонтной бригады для чистовой отделки."},
  {"id": "2", "text": "Подскажите, а какая реальная высота потолка во второй очереди?"},
  {"id": "3", "text": "Посоветуйте, пожалуйста, хорошего юриста по недвижимости для консультации по договору."},
  {"id": "4", "text": "Нужен помощник на несколько часов. Помочь расставить мебель, подать инструмент, придержать детали. Плачу щедро за потраченное время."},
  {"id": "5", "text": "Кто то работу руками делает"},
  {"id": "6", "text": "может кто-то одолжить строительный пылесос на выходные?"}
]

Model Output:
1|1|1|1=2|0|3|Ищет ремонтную бригаду
2|5|1||0|1|Уточняет высоту потолка
3|1|3,5|5=1|0|3|Ищет юриста по договору
4|2|1||0|1|Мелкая подработка, не лид
5|6|12||0|1|Обрывок фразы
6|1|1|1=3|0|2|Просит одолжить инструмент
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


INTENT_CODE_TO_VALUE: dict[int, IntentType] = {
    1: IntentType.REQUEST,
    2: IntentType.OFFER,
    3: IntentType.RECOMMENDATION,
    4: IntentType.COMPLAINT,
    5: IntentType.INFO,
    6: IntentType.OTHER,
}
INTENT_VALUE_TO_CODE: dict[IntentType, int] = {v: k for k, v in INTENT_CODE_TO_VALUE.items()}

DOMAIN_CODE_TO_VALUE: dict[int, DomainType] = {
    1: DomainType.CONSTRUCTION_AND_REPAIR,
    2: DomainType.RENTAL_OF_REAL_ESTATE,
    3: DomainType.PURCHASE_OF_REAL_ESTATE,
    4: DomainType.REAL_ESTATE_AGENT,
    5: DomainType.LAW,
    6: DomainType.SERVICES,
    7: DomainType.AUTO,
    8: DomainType.MARKETPLACE,
    9: DomainType.SOCIAL_CAPITAL,
    10: DomainType.OPERATIONAL_MANAGEMENT,
    11: DomainType.REPUTATION,
    12: DomainType.NONE,
}
DOMAIN_VALUE_TO_CODE: dict[DomainType, int] = {v: k for k, v in DOMAIN_CODE_TO_VALUE.items()}

SUBCATEGORY_CODE_TO_VALUE: dict[DomainType, dict[int, str]] = {
    DomainType.CONSTRUCTION_AND_REPAIR: {
        1: "MAJOR_RENOVATION",
        2: "REPAIR_SERVICES",
        3: "SMALL_TOOLS_AND_MATERIALS",
    },
    DomainType.RENTAL_OF_REAL_ESTATE: {
        1: "RENTAL_APARTMENT",
        2: "RENTAL_HOUSE",
        3: "RENTAL_PARKING",
        4: "RENTAL_STORAGE",
        5: "RENTAL_LAND",
    },
    DomainType.PURCHASE_OF_REAL_ESTATE: {
        1: "PURCHASE_APARTMENT",
        2: "PURCHASE_HOUSE",
        3: "PURCHASE_PARKING",
        4: "PURCHASE_STORAGE",
        5: "PURCHASE_LAND",
    },
    DomainType.REAL_ESTATE_AGENT: {
        1: "AGENT",
    },
    DomainType.LAW: {
        1: "LAWYER",
    },
    DomainType.SERVICES: {
        1: "BEAUTY_AND_HEALTH",
        2: "HOUSEHOLD_SERVICES",
        3: "CHILD_CARE_AND_EDUCATION",
        4: "DELIVERY_SERVICES",
        5: "TECH_REPAIR",
    },
    DomainType.AUTO: {
        1: "AUTO_PURCHASE",
        2: "AUTO_PREMIUM_DETAILING",
        3: "AUTO_REPAIR",
        4: "AUTO_SERVICE_STATION",
    },
    DomainType.MARKETPLACE: {
        1: "BUY_SELL_GOODS",
        2: "GIVE_AWAY",
        3: "HOMEMADE_FOOD",
        4: "BUYER_SERVICES",
    },
    DomainType.SOCIAL_CAPITAL: {
        1: "PARENTING",
        2: "HOBBY_AND_SPORT",
        3: "EVENTS",
    },
    DomainType.OPERATIONAL_MANAGEMENT: {
        1: "LOST_AND_FOUND",
        2: "SECURITY",
        3: "LIVING_ENVIRONMENT",
        4: "MANAGEMENT_COMPANY_INTERACTION",
    },
    DomainType.REPUTATION: {
        1: "PERSONAL_BRAND",
        2: "COMPANIES_REPUTATION",
    },
    DomainType.NONE: {},
}
SUBCATEGORY_VALUE_TO_CODE: dict[DomainType, dict[str, int]] = {
    domain: {value: code for code, value in mapping.items()}
    for domain, mapping in SUBCATEGORY_CODE_TO_VALUE.items()
}


# Pydantic models for classification
class DomainInfo(BaseModel):
    """Domain information with optional subcategories."""
    domain: DomainType = Field(
        ..., 
        description="Select the most relevant high-level domain."
    )
    subcategories: List[str] = Field(
        default_factory=list,
    )


class ClassifiedMessage(BaseModel):
    """Classification result for a single message."""
    id: str = Field(..., description="Unique message ID from input.")
    
    intents: List[IntentType] = Field(
        ...
    )
    
    domains: List[DomainInfo] = Field(..., description="List of relevant domains and their subcategories.")
    
    is_spam: bool = Field(
        ...
    )
    
    urgency_score: int = Field(
        ...
    )
    
    reasoning: str = Field(
        ...
    )


class ClassificationBatchResult(BaseModel):
    """Batch classification result containing multiple classified messages."""
    classified_messages: List[ClassifiedMessage]


def _parse_int_code(value: int | str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise ValueError(f"Invalid code value: {value}")


def _parse_code_list(value: str, label: str) -> list[int]:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    items = [item.strip() for item in value.split(",") if item.strip()]
    codes: list[int] = []
    for item in items:
        if not item.isdigit():
            raise ValueError(f"Invalid {label} code: {item}")
        codes.append(int(item))
    return codes


def _parse_subcategory_map(segment: str) -> dict[int, list[int]]:
    subcats: dict[int, list[int]] = {}
    if not isinstance(segment, str) or not segment.strip():
        return subcats
    tokens: list[str] = []
    for part in segment.split(";"):
        part = part.strip()
        if not part:
            continue
        tokens.extend([item.strip() for item in part.split(",") if item.strip()])
    current_domain: int | None = None
    for token in tokens:
        if "=" in token:
            domain_str, sub_str = token.split("=", 1)
            domain_code = _parse_int_code(domain_str.strip())
            if not sub_str.strip():
                raise ValueError(f"Invalid subcategory entry: {token}")
            current_domain = domain_code
            subcodes = _parse_code_list(sub_str, f"S{domain_code}")
            subcats.setdefault(domain_code, []).extend(subcodes)
        else:
            if current_domain is None:
                raise ValueError(f"Subcategory code without domain: {token}")
            subcodes = _parse_code_list(token, f"S{current_domain}")
            subcats.setdefault(current_domain, []).extend(subcodes)
    return subcats


def _parse_compact_line(line: str) -> dict[str, object]:
    parts = line.split("|", 6)
    if len(parts) != 7:
        raise ValueError(f"Invalid line format (expected 7 parts): {line}")
    msg_id, intent_raw, domains_raw, subcats_raw, spam_raw, urgency_raw, reasoning = [
        part.strip() for part in parts
    ]
    if not msg_id:
        raise ValueError(f"Missing message id in line: {line}")

    intent_code = _parse_int_code(intent_raw)
    intent_value = INTENT_CODE_TO_VALUE.get(intent_code)
    if intent_value is None:
        raise ValueError(f"Unknown intent code: {intent_code}")
    intents = [intent_value]

    domain_codes = _parse_code_list(domains_raw, "D") if domains_raw else []
    if not domain_codes:
        domain_codes = [DOMAIN_VALUE_TO_CODE[DomainType.NONE]]
    subcategory_map = _parse_subcategory_map(subcats_raw)
    if DOMAIN_VALUE_TO_CODE[DomainType.NONE] in domain_codes and len(domain_codes) > 1:
        # LLM sometimes returns NONE alongside real domains. Ignore NONE in that case.
        domain_codes = [
            code for code in domain_codes
            if code != DOMAIN_VALUE_TO_CODE[DomainType.NONE]
        ]
        subcategory_map.pop(DOMAIN_VALUE_TO_CODE[DomainType.NONE], None)
    extra_subcats = set(subcategory_map.keys()) - set(domain_codes)
    if extra_subcats:
        raise ValueError(f"Subcategory entries for non-selected domains: {sorted(extra_subcats)}")

    domains: list[dict[str, object]] = []
    for domain_code in domain_codes:
        domain_value = DOMAIN_CODE_TO_VALUE.get(domain_code)
        if domain_value is None:
            raise ValueError(f"Unknown domain code: {domain_code}")
        if domain_value == DomainType.NONE and domain_code in subcategory_map:
            raise ValueError("Subcategories not allowed for NONE domain")
        allowed_subcats = SUBCATEGORY_CODE_TO_VALUE.get(domain_value, {})
        subcodes = subcategory_map.get(domain_code, [])
        subcategories: list[str] = []
        for sub_code in subcodes:
            sub_value = allowed_subcats.get(sub_code)
            if sub_value is None:
                raise ValueError(f"Unknown subcategory code: {sub_code} for {domain_value}")
            subcategories.append(sub_value)
        domains.append({"domain": domain_value, "subcategories": subcategories})

    if spam_raw not in {"0", "1"}:
        raise ValueError(f"Invalid spam flag: {spam_raw}")
    is_spam = spam_raw == "1"

    urgency_code = _parse_int_code(urgency_raw)
    if urgency_code < 1 or urgency_code > 5:
        raise ValueError(f"Urgency out of range (1..5): {urgency_code}")

    return {
        "id": msg_id,
        "intents": intents,
        "domains": domains,
        "is_spam": is_spam,
        "urgency_score": urgency_code,
        "reasoning": reasoning,
    }


def parse_compact_batch(text: str) -> ClassificationBatchResult:
    """
    Parse compact numeric batch output into full classification schema.

    Expected line format:
    <id>|<intent>|<domains>|<subcats>|<spam>|<urgency>|<reasoning>
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Empty compact output")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("No compact lines found")

    decoded_messages: list[dict[str, object]] = []
    for line in lines:
        decoded_messages.append(_parse_compact_line(line))

    return ClassificationBatchResult.model_validate({"classified_messages": decoded_messages})


def parse_compact_batch_partial(
    text: str,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """
    Best-effort parsing: returns successfully parsed messages and per-line errors.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Empty compact output")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("No compact lines found")

    decoded_messages: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    for line in lines:
        try:
            parsed = _parse_compact_line(line)
            validated = ClassifiedMessage.model_validate(parsed).model_dump()
            decoded_messages.append(validated)
        except Exception as exc:
            msg_id = ""
            try:
                msg_id = line.split("|", 1)[0].strip()
            except Exception:
                msg_id = ""
            errors.append(
                {
                    "id": msg_id,
                    "line": line,
                    "error": str(exc),
                }
            )

    return decoded_messages, errors

