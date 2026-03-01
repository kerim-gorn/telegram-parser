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
1 CONSTRUCTION_AND_REPAIR: 1=TURNKEY_RENOVATION_CREWS, 2=DESIGN_AND_PLANNING, 3=APARTMENT_HANDOVER_INSPECTION, 4=WALL_FINISHING_PLASTER_PAINT, 5=BALCONY_AND_LOGGIA_WORKS, 6=TILING_WORKS, 7=WINDOWS_REPAIR_AND_ADJUSTMENT, 8=PLUMBING_SERVICES, 9=CUSTOM_FURNITURE, 10=AIR_CONDITIONING_SERVICES, 11=INTERIOR_DOORS_INSTALLATION, 12=ELECTRICAL_WORKS, 13=STRETCH_CEILINGS, 14=FLOORING_SCREED_AND_LAMINATE, 15=COTTAGE_AND_HOUSE_STRUCTURAL_WORKS, 16=TOOLS_AND_MATERIALS, 17=IRRELEVANT_WORKS_AND_QUESTIONS
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
   1. TURNKEY_RENOVATION_CREWS: Бригады для черновых и отделочных работ, ремонт под ключ в домах, квартирах и студиях.
   2. DESIGN_AND_PLANNING: Дизайн и проектирование — подбор дизайнера, проектировщика, разработка планировочных решений.
   3. APARTMENT_HANDOVER_INSPECTION: Приемка квартиры — услуги приемщиков, проверки тепловизором и т.п.
   4. WALL_FINISHING_PLASTER_PAINT: Работы со стенами — штукатурка, малярные работы, поклейка и покраска обоев.
   5. BALCONY_AND_LOGGIA_WORKS: Работы с лоджией/балконом — остекление, утепление, отделка.
   6. TILING_WORKS: Плиточные работы — укладка/снятие плитки, керамогранита и т.п.
   7. WINDOWS_REPAIR_AND_ADJUSTMENT: Окна — регулировка, ремонт, утепление.
   8. PLUMBING_SERVICES: Сантехника — установка и ремонт сантехнического оборудования, отопление.
   9. CUSTOM_FURNITURE: Мебель на заказ — шкафы, кухни, мебельные конструкции.
   10. AIR_CONDITIONING_SERVICES: Кондиционирование — установка, обслуживание и доработка трасс кондиционеров.
   11. INTERIOR_DOORS_INSTALLATION: Межкомнатные двери — установка и мелкий ремонт дверей.
   12. ELECTRICAL_WORKS: Электрика — разводка, замена проводки, сборка щитков, работы по слаботочке.
   13. STRETCH_CEILINGS: Потолки — натяжные и иные потолочные решения.
   14. FLOORING_SCREED_AND_LAMINATE: Полы — стяжка, укладка ламината, инженерной доски и т.п.
   15. COTTAGE_AND_HOUSE_STRUCTURAL_WORKS: Коттеджи и частные дома — строительство домов, кровля, фасад, фундамент, скважины и прочие крупные работы.
   16. TOOLS_AND_MATERIALS: Мелкие стройматериалы и инструменты — аренда/одолжить инструмент, купля/продажа мелких стройматериалов, мелкие разовые работы (установка одной двери, вывоз мусора).
   17. IRRELEVANT_WORKS_AND_QUESTIONS: Очень мелкие работы и вопросы «сделать самому» — задачи на пару часов и обсуждения, где чаще нужен совет, а не подрядчик.
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
1) Настоящие REQUEST-лиды (REQUEST + CONSTRUCTION_AND_REPAIR) по подкатегориям (НЕ СПАМ):
    - 1. TURNKEY_RENOVATION_CREWS: Бригады для черновых и отделочных работ, ремонт под ключ в домах, квартирах и студиях.
        - Добрый вечер. Можете кого-то посоветовать для ремонта студии Дзен? Сдают без отделки
        - Соседи, добрый вечер!Порекомендуйте пожалуйста ☝🏼☝🏼проверенную бригаду ремонтников? Хотелось бы посмотреть на результат их работы вживую, если возможно.
        - Добрый день, скиньте пожалуйста бригады по отделке у нас . Под ключ желательно. Буду признательна
        - Доброго всем дня! Подскажите пожалуйств хорошего мастера отделочника
        - Добрый день, посоветуйте, пожалуйста, подрядчиков по ремонту/бригады
        - Добрый день. Ищу хорошую бригаду для ремонта. Скиньте номер у кого есть такие мастера.
    - 2. DESIGN_AND_PLANNING: Дизайн и проектирование
        - Всем привет! Порекомендуйте дизайнера за адекватные деньги в личку. Без перепланировок, квартира с ремонтом от пик.
        - Всем привет 👋 Кто делал ремонт с дизайнером? Можете дать рекомендации в лс? Не за оверпрайс желательно
        - Может дадите контакты проектировщиков если есть проверенные ребята)
        - Не поделитесь контактами проектировщиков?)
    - 3. APARTMENT_HANDOVER_INSPECTION: Приемка квартиры
        - Добрый день, пришлите пожалуйста контакт приемщика, спасибо!
        - Добрый день! Порекомендуйте, пожалуйста хорошего приемщика. И еще я не совсем понимаю как определять пустоты и мостики холода летом. 7 корпус обещали сдать летом.
        - Здравствуйте, подскажите контакты внимательных приемщиков.
        - Добрый день! Посоветуйте приемщика с тепловизором пжлст.
    - 4. WALL_FINISHING_PLASTER_PAINT: Работы со стенами: штукатурка, малярные работы, обои и прочее
        - Ищу мастера на послейку обоев. Пишите в лк.
        - Приветствую , соседи ! Кто клеит обои? Нужно оклеить студию
        - Здравствуйте, подскажите пожалуйста кто то сможет поклеить обои?
        - Добрый день. Есть у кого опыт с покраской обоев . Из информации в нашем чате , нашел только рекламное предложение. Хотелось сравнить варианты. Если у кого есть проверенные контакты и описание работ которые делали специалисты , буду очень рад и признателен. Всем хорошего дня и успехов в переезде и быту 😊😊😊.
        - Здравствуйте! Требуется мастер по штукатурке, под маяки. Первичка, студия, 40 квадратов по полу. Писать в лс
        - Ищу штукатура в квартиру под ключ, пиши обсудим
        - Малярные работы
        - Добрый день! Поделитесь, пожалуйста, в лс контактами проверенного маляра. Благодарю!🌸
        - Может кто-то посоветовать маляров? Или может хотя-бы подскажите чем стены красят?))
        - Уважаемые соседи, подскажите, пожалуйста, может у кого-нибудь есть проверенный   маляр-штукатур, готовый выполнять небольшой объём работ? Прошу поделиться контактом.
    - 5. BALCONY_AND_LOGGIA_WORKS: Лоджия или балкон
        - Добрый день! Подскажите контакты, у кого можно качественно и приемлемо по цене утеплить балкон🙏🏾
        - Уважаемые соседи, приветствую! Есть небольшой вопрос по поводу панорамных окон от застройщика. Как считаете, при объединении балкона и жилой комнаты их крайне, необходимо менять или можно оставить те что есть? Если вы меняли - подскажите контакты компаний/мастеров, кого можете рекомендовать, исходя из вашего опыта.
        - Здравствуйте  соседи🤝 Подскажите пожалуйста 🙏 кто-нибудь знает хорошего мастера по утеплению и застеклению балконов
        - Добрый день. Подскажите кто-нибудь делал отделку балкона «под ключ» с остеклением и внутренней отделкой . Поделитесь контактом и стоимостью
    - 6. TILING_WORKS: Плитка
        - Добрый вечер! Подскажите номер проверенного, хорошего специалиста по укладке керамогранита в ванной комнате? Заранее благодарен вам
        - Добрый день! Ищу мастера, который снимет старую плитку в ванной от застройщика и уложит полностью новым керамогранитом. В л.с., пожалуйста
        - Подскажите номер плиточника
    - 7. WINDOWS_REPAIR_AND_ADJUSTMENT: Окна
        - Кто нибудь сталкивался с проблемой окон ? Есть контакт регулировщика пластиковых окон?
        - Добрый день. Соседи, порекомендуйте, пожалуйста, фирму/мастера, кто сможет по окнам сделать оценку и утеплить.
        - Всем доброе утро! Поделитесь, пожалуйста, контактами, кто может оперативно отрегулировать окна
        - Добрый день всем! Нужен номер специалиста по регулировке окон, можете в личку отправить?
        - Здравствуйте, подскажите, кто может  отрегулировать окна в квартире новой очень сильно дует, есть номер мастеров
        - Добрый день, кто то знает кто занимается у нас окнами в ЖК? Нужен ремонт - куда обращаться
        - Соседи, здравствуйте! Подскажите есть ли у кого контакты регулировки окон, на зимний режим перестроить , сильно свистеть начало при морозах.
    - 8. PLUMBING_SERVICES: Сантехника
        - Соседи, добрый день. Посоветуйте сантехника в нашем ЖК, спасибо
        - Здравствуйте, у кого есть контакт сантехника? Буду очень благодарна за рекомендации
        - Здравствуйте! Может кто-нибудь поделиться контактом нормального сантехника?
        - Приветствую! Соседи, посоветуете нормального сантехника в плюс минус окрестности чтобы мог оперативно подойти?
        - Здравствуйте, всех С новым годом подскажите пожалуйста есть ли кто занимается сантехникой и отоплением в частных домах?
    - 9. CUSTOM_FURNITURE: Мебель
        - Добрый день! Подскажите пожалуйста контакты проверенных мебельщиков? Нужен шкаф распашонку в коридор
        - Ребята с первой и второй очереди, посоветуйте , пожалуйста, хорошего меблировщика по своему опыту?
    - 10. AIR_CONDITIONING_SERVICES: Кондиционер
        - Здравствуйте,подскажите пожалуйста,есть ли контакты кондиционеровщиков в коммерческое помещение, кто поможет, проконсультирует
        - Добрый день. Интересует установка кондиционера.
        - Соседи, как «укоротить» / убрать трассу для кондишена в КОМНАТЕ над дверью ? Сейчас не буду устанавливать кондишен, но мб в будущем решусь его повесить, тогда и понадобится трасса, а сейчас ее необходимо спрятать. Мб у кого- то в квартире так сделано ? Поделитесь или посоветуйте спецов по кондиционерам. Спс
    - 11. INTERIOR_DOORS_INSTALLATION: Межкомнатные двери
        - Здравствуйте. Подскажите, пожалуйста, кто у нас на районе занимается установкой межкомнатных дверей
    - 12. ELECTRICAL_WORKS: Электрика
        - Всем привет соседи 👋 Случайно нет знакомого электрика шарящего в умных домах?
        - Нужен электрик для который может приехать сегодня. Пожалуйста пришлите в личку контакт
        - Добрый день, нужно сделать проводку в квартире, порекомендуйте контакты
        - Ищу контакты, кто сможет проложить коммуникации по электрике
        - Привет! Нужна замена электросети и собрать щиток, дайте контакты электрика
        - Всем добрый вечер! Подскажите, пожалуйста, контакты хорошего электрика, если имеются. Большое спасибо!
    - 13. STRETCH_CEILINGS: Потолки
        - Натяжные потолки отзовитесь пожалуйста в личку, вроде тут писали 🙏🙏🙏
        - Соседи, привет! У кого есть хорошие потолочники за адекватные деньги (натяжной)?
        - Добрый день. Поделитесь, пожалуйста, в личку проверенными контактами кто делает натяжные потолки
    - 14. FLOORING_SCREED_AND_LAMINATE: Полы: стяжка пола, ламинат, инженерная доска
        - Добрый день. Подскажите контакты стяжки?
        - Соседи, кто-то может порекомендовать мастера по заливке пола?
        - Соседи, кто то может сейчас стяжку делает? Могли бы дать контакты ваших рабочих?
        - Добрый день! Поделитесь, пожалуйста, в личку проверенными контактами кто кладет ламинат / инженерную доску
    - 15. COTTAGE_AND_HOUSE_STRUCTURAL_WORKS: Коттеджи и частные дома: строительство домов целиком, кровля, фасад, скважина, фундамент, коробка, перекрытия и другие работы той же категории
        - Ребят у кого нибудь есть проверенные рабочие по фасадным делам (обшить дом сайдингом)
        - Добрый день. Соседи, поделитесь контактами кому делали скважину и что вышло по деньгам.  Если можно фото что по  итогу  получилось.  Заранее спасибо 😁
        - Всем привет, соседи. Есть важный вопрос, вижу, что многие построили каркасники, поделитесь пожалуйста застройщиком, сейчас выбираем у кого строиться, очень буду благодарна за ваш опыт.
        - Добрый вечер! Я хочу заказать утепление внутренних отделка на 1и 2 этажа! Не дороже)))
    - 16. TOOLS_AND_MATERIALS: Мелкие стройматериалы и инструменты - аренда/одолжить инструмент (пылесос, тепловизор, сверло), купля/продажа мелких стройматериалов (гипсокартон, двери от застройщика), мелкие услуги (установка одной двери, вывоз мусора)
        - «может кто-то одолжить строительный пылесос на выходные?»
        - «Куплю строительный унитаз. Предложения в личку)»
        - «Заберу самовывозом дверь от застройщика»
        - «Может ли кто-то дать в аренду тепловизор? Будем очень благодарны!»
        - «есть у кого сверло для перфоратора на 10 по бетону?»
        - «Кто нибудь планирует строительный мусор свой вывозить?»
        - «Есть кто нибудь дверь установить межкомнатную? У нас в ЖК»
        - «у кого остался гипсокартон, куплю целый или остатки»
    - 17. IRRELEVANT_WORKS_AND_QUESTIONS: очень мелкие работы – какие-то задачи на пару часов, которые стоят незначительных средств; вопрос может касаться дорогостроящих услуг, но люди явно просят совет, как им самим решить задачу без надобности в привлечении других людей
        - Соседи, у кого-нибудь плиточники работают? Можно попросить разрезать 2 плинтуса кафельных?
        - Здравствуйте, соседи. Скажите, кто-то пробовал сажать пиковскую ручку межкомнатной двери на стяжной винт? А то я как не вкручиваю штатные саморезы, все равно вываливаются😐
        - Добрый день. Подскажите как быть с проветривателями окон. Сифонит сильно. Спасибо
        - Добрый день! В квартире дует из окон (принимали  летом), холодный пол, сейчас на окнах даже внизу у резинок образовался лед. Под подоконниками вообще холод. Писали в Заявки на сайт Пик Комфорт в  тему Гарантийные случаи.( до этого заявки и по отоплению делали и по окнам), отправляют на официальный сат в "Замечания". У кого -то есть аналогичная история? Застройщик  реагирует на это? И кто-нибудь пользовался услугами Ситипроф (т хотим сделать услугу по тепловизии).
        - Соседи, добрый день! Кто может посоветовать специалиста по поклейке обоев. Приходили подрядчики от гарантийного отдела, немного отодрали обои и плинтус, нужно вернуть на место.
        - Добрый день! Посоветуйте, пожалуйста, местных электриков или кто живет относительно недалеко. Люстры нужно повесить
        - Друзья а кто нибудь знает что у нас за профиль окна ? Может кто нибудь сфотографировать ?
        - Добрый день. Может у кого есть знакомые мебельщики? В спецификации кухни не могу разобраться.
        - Добрый день! 26.02. Записаны на приемку. На 9-00 Есть еще кто на эту дату? Скооперироваться на приемщика
        - Всем привет. Подскажите, пожалуйста, контакт сантехника снять заглушки на кухне.
        - Товарищи, добрый день! А в доме 13 уже кто-то ставил Кондеи?
        - Соседи подскажите. А кто нибудь балкон утеплил? Если да то чем?
        - Мы можем сделать отдельный кондиционер на стене? 500 т отдавать не планируем
        - ищу электрика, для подключения. Дайте пожалуйста телефон
        - Соседи, всем добрый вечер. Поделитесь контактом толкового электрика кто разбирается в слаботочке, надо проверить трансформатор подсветки
        - Доброе утро соседи, есть тут кто электрик в ЖК у нас?
        - Добрый вечер! Соседи, есть у нас в ЖК хороший электрик? Порекомендуйте пожалуйста.
        - Есть тут кто-то с электрокотлом и тремя однофазными инверторными стабилизаторами? У соседа в такой схеме котёл или не греет или стабилизаторы в защиту уходят. Отсутствие корректного чередования фаз? Некорректно собрана нейтраль? Какие есть мысли по этому поводу?

2) НЕ REQUEST (INFO/OTHER/COMPLAINT):
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


3) Мелкие стройматериалы/инструменты (REQUEST, subcategory TOOLS_AND_MATERIALS):
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
1|1|1|1=1|0|3|Ищет ремонтную бригаду
2|5|1||0|1|Уточняет высоту потолка
3|1|3,5|5=1|0|3|Ищет юриста по договору
4|2|1||0|1|Мелкая подработка, не лид
5|6|12||0|1|Обрывок фразы
6|1|1|1=16|0|2|Просит одолжить инструмент
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
        1: "TURNKEY_RENOVATION_CREWS",
        2: "DESIGN_AND_PLANNING",
        3: "APARTMENT_HANDOVER_INSPECTION",
        4: "WALL_FINISHING_PLASTER_PAINT",
        5: "BALCONY_AND_LOGGIA_WORKS",
        6: "TILING_WORKS",
        7: "WINDOWS_REPAIR_AND_ADJUSTMENT",
        8: "PLUMBING_SERVICES",
        9: "CUSTOM_FURNITURE",
        10: "AIR_CONDITIONING_SERVICES",
        11: "INTERIOR_DOORS_INSTALLATION",
        12: "ELECTRICAL_WORKS",
        13: "STRETCH_CEILINGS",
        14: "FLOORING_SCREED_AND_LAMINATE",
        15: "COTTAGE_AND_HOUSE_STRUCTURAL_WORKS",
        16: "TOOLS_AND_MATERIALS",
        17: "IRRELEVANT_WORKS_AND_QUESTIONS",
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

