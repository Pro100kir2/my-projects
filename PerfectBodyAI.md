Ты senior staff/principal engineer и product architect. 
Нужно спроектировать и реализовать production-ready AI fitness application уровня коммерческого продукта.

КРИТИЧЕСКИ ВАЖНО:
- Писать ЧИСТЫЙ production-ready код
- НЕ делать mock-архитектуру
- НЕ делать toy-проект
- НЕ упрощать архитектуру
- Код должен быть масштабируемым
- Строгая типизация
- SOLID
- Clean Architecture
- Feature-based architecture
- Максимум комментариев
- Объяснять зачем нужен каждый слой
- Избегать technical debt
- Делать enterprise-level структуру проекта
- Никаких legacy-patterns
- Никакого god-object/god-service
- Никаких огромных файлов
- Максимальная декомпозиция
- Все env variables через .env
- Все секреты только через env
- Полная dockerized инфраструктура
- Обязательно писать README
- Обязательно писать Swagger/OpenAPI
- Обязательно healthchecks
- Обязательно migrations
- Обязательно logging
- Обязательно tracing hooks
- Обязательно retry policy
- Обязательно graceful shutdown
- Обязательно rate limiting
- Обязательно caching strategy
- Обязательно async architecture
- Обязательно websocket support
- Обязательно unit tests
- Обязательно integration tests
- Обязательно CI-ready структура
- Обязательно pre-commit hooks
- Обязательно linting
- Обязательно formatting
- Обязательно DTO validation
- Обязательно centralized error handling
- Обязательно RBAC-ready architecture
- Обязательно scalable AI pipeline
- Обязательно background jobs
- Обязательно queue system
- Обязательно event-driven architecture где нужно


ПРОЕКТ


Название:
Perfect Body AI
Описание:
Мобильное AI fitness приложение с:
- AI генерацией тренировок
- AI nutrition planner
- AI exercise assistant
- AI real-time trainer
- GPS tracking
- Device integrations
- Calorie tracking
- Exercise video recommendations
- Progress analytics


ОСНОВНОЙ FLOW


1. Регистрация пользователя
2. Онбординг
3. Главный экран
4. Генерация тренировок
5. Nutrition tracking
6. Video trainer
7. AI corrections during exercises
8. Analytics and progress


ОНБОРДИНГ


После регистрации пользователь отвечает на вопросы:

- возраст
- рост
- вес
- пол
- процент жира
- цель:
  - похудение
  - набор массы
  - поддержание
  - endurance
  - strength
- уровень подготовки
- ограничения по здоровью
- травмы
- доступный инвентарь
- бюджет на питание
- предпочтения в еде
- аллергии
- количество тренировок в неделю
- желаемое время тренировки
- виды спорта:
  - бег
  - лыжи
  - зал
  - велосипед
  - плавание
  - функциональные тренировки
  - HIIT
  - и тд

Все данные сохраняются в PostgreSQL.


ТАБЫ ПРИЛОЖЕНИЯ


Нижний tab bar:

1. Главная
2. Питание
3. Мои тренировки
4. Настройки


ГЛАВНАЯ


На главной:

- выбор типа тренировки
- кнопка "Начать тренировку"
- пульс
- подключение wearable devices
- GPS tracking если нужен outdoor sport
- summary card
- рекомендации AI
- active workout card
- weekly progress

Подключения:
- Polar
- Zepp
- Garmin
- Apple Health
- Google Fit
- Health Connect

Сделать architecture-ready integrations layer.


START WORKOUT FLOW


После нажатия "Начать тренировку":

1. Создать тренировку
2. Загрузить тренировку


СОЗДАТЬ ТРЕНИРОВКУ


AI должен:

- анализировать профиль пользователя
- анализировать историю тренировок
- анализировать recovery/load
- генерировать профессиональный workout plan
- учитывать progressive overload
- учитывать fatigue
- учитывать goals
- учитывать equipment
- учитывать duration

После генерации:
- workout разбивается на exercise blocks
- к каждому упражнению подтягивается exercise video
- exercise explanations
- common mistakes
- safety comments
- breathing comments
- tempo comments
- muscle activation comments


ЗАГРУЗИТЬ ТРЕНИРОВКУ


Пользователь может:
- вставить текст тренировки
- загрузить PDF
- загрузить screenshot
- загрузить фото

AI должен:
- распарсить тренировку
- разбить на exercises
- определить exercise types
- подобрать exercise videos
- добавить AI comments
- определить estimated calories
- определить difficulty


VIDEO TRAINER (КРИТИЧЕСКИ ВАЖНАЯ ФУНКЦИЯ)


Во время тренировки пользователь включает камеру.

AI в реальном времени:
- анализирует движения
- анализирует posture
- анализирует ROM
- анализирует symmetry
- анализирует tempo
- анализирует technique

AI голосом и текстом говорит:
- что неправильно
- как исправить
- что опасно
- как улучшить форму
- когда пользователь делает правильно

Нужна low latency architecture.


NUTRITION TAB


Функции:

- calories
- protein/fat/carbs
- water tracking
- meal history
- weekly nutrition analytics
- adaptive nutrition planning

AI должен:
- адаптировать nutrition plan weekly
- учитывать прогресс
- учитывать бюджет
- учитывать goal


FOOD PHOTO ANALYSIS


Пользователь фотографирует еду.

AI должен:
- определить блюдо
- определить ingredients
- определить calories
- определить protein/fat/carbs
- определить estimated weight
- сохранить meal entry


MEAL PLAN GENERATION


AI генерирует план питания на неделю.

Учитывать:
- бюджет
- allergies
- preferences
- calories target
- macros
- country/local food availability

Бюджеты:
- low budget
- medium budget
- premium budget


МОИ ТРЕНИРОВКИ


Раздел:
- история тренировок
- статистика
- графики
- вес
- body fat
- progress photos
- PR tracking
- streaks
- recovery trends


НАСТРОЙКИ


Настройки:
- тема
- язык
- permissions
- connected devices
- privacy
- notifications
- subscriptions
- AI preferences

ТЕХНОЛОГИЧЕСКИЙ СТЕК

Frontend:
- React Native Expo
- TypeScript
- React Query
- Zustand
- React Navigation
- Reanimated
- NativeWind/Tailwind
- WebSocket support

Backend:
- Python
- Clean Architecture
- CQRS where useful
(An Important Point : CQRS не надо везде лепить — только где есть нагрузка и сложные read/write сценарии)
- Event-driven modules

Database:
- PostgreSQL

ORM:
- Prisma

Cache:
- Redis

Broker:
- RabbitMQ

AI:
- GigaChat для:
  - workout generation
  - nutrition planning
  - recommendations
  - parsing
  - AI comments
  - coaching text

Для video trainer:
Выбери лучший production-ready stack:
- MediaPipe
- MoveNet
- TensorFlow Lite
- ONNX Runtime
- BlazePose
- OpenCV

Нужен realistic scalable choice.

Для food analysis:
Выбери лучший production-ready multimodal model/API.

AI VIDEO STRATEGY

НЕ генерировать видео realtime.

Использовать:
- pregenerated exercise videos
- exercise video library
- CDN delivery
- metadata tagging
- AI mapping exercises to videos

Продумать:
- exercise taxonomy
- exercise search engine
- exercise metadata structure

ТРЕБОВАНИЯ К АРХИТЕКТУРЕ

Нужно:

1. Полная структура монорепозитория

2. Продуманная folder architecture

3. Backend modules

4. Frontend modules

5. AI services

6. WebSocket architecture

7. Queue architecture

8. Event flows

9. Database schema

10. Prisma schema

11. Docker compose

12. CI/CD strategy

13. Security strategy

14. Scaling strategy

15. Offline-first considerations

16. Mobile optimization

17. Cost optimization

18. Observability

19. Monitoring

20. AI rate limiting

21. AI caching

22. Background processing

23. GPU/offloading strategy

24. Edge cases

25. Failure handling

ВАЖНО

Нужно НЕ просто описание.

Нужно:
- production architecture
- реальные файлы
- реальная структура
- примеры кода
- DTO
- entities
- services
- controllers
- hooks
- repositories
- queue processors
- websocket gateways
- Prisma models
- Docker configs
- env examples
- API examples


КОД СТАЙЛ


- Максимально читаемый код
- Строгая типизация
- Всегда interfaces
- Всегда DTO
- Всегда validation
- Всегда comments
- Всегда explain why
- Не использовать any
- Не использовать magic numbers
- Не использовать hardcoded values
- Все configurable


РЕЗУЛЬТАТ


Пошагово реализуй:
1. Архитектуру
2. Backend
3. Frontend
4. AI layer
5. Real-time trainer
6. Nutrition system
7. Device integrations
8. Deployment
9. Monitoring
10. Scaling

После каждого большого шага:
- объясняй почему принято именно такое решение
- объясняй tradeoffs
- объясняй scalability implications
- объясняй cost implications

Не сокращай ответы.
Не упрощай.
Думай как architect уровня FAANG/staff engineer.