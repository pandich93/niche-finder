# niche-finder — backend

[![CI](https://img.shields.io/github/actions/workflow/status/pandich93/niche-finder/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/pandich93/niche-finder/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fpandich93%2Fniche-finder%2Fmain%2Fassets%2Fcoverage.json&query=%24.totals.percent_covered_display&suffix=%25&label=coverage&style=flat-square)](../assets/coverage.json)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square&logo=python&logoColor=white)](Dockerfile)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](interfaces/http/api.py)
[![PostgreSQL 16](https://img.shields.io/badge/postgres-16-336791?style=flat-square&logo=postgresql&logoColor=white)](../docker-compose.yml)
[![MCP](https://img.shields.io/badge/MCP-24%20tools-8A2BE2?style=flat-square)](interfaces/mcp/server.py)

Свой аналог NexLev / vidIQ / ViewStats: поиск ниш, вирусных видео у маленьких
каналов, трендовых категорий и ключевых слов **за произвольные периоды**
(24 часа, 48 часов, 7/30/90 дней), плюс полноценный трекинг и разбор каналов.
Всё на бесплатном YouTube Data API v3 и локальном PostgreSQL.

Классификацию вида «faceless / AI / подходит по смыслу» делает не сервер, а
модель, которая вызывает эти инструменты: сервер отдаёт сырые заголовки,
описания и обложки, решение принимается в диалоге. Отдельный платный ключ к
LLM не нужен.

Разбор рынка и формулы конкурентов (`docs/research-tools.md`) — внутренние
заметки, в этот репозиторий не входят.

---

## Главное про квоты (изменилось 1 июня 2026)

| Метод | Стоимость |
|---|---|
| `search.list` | 1 unit, но **всего 100 вызовов в сутки**, отдельная корзина |
| всё остальное | 1 unit из общего пула на **10 000 units в сутки** |

Поиск — дефицит, чтение — почти бесплатно. Поэтому:

- `collect_niche` — единственный, кто тратит поиск. Используйте для новых тем.
- `collect_channel` — идёт через uploads-плейлист: **1 unit за 50 видео**, без
  обрезки на 500 результатах, поиск не трогает. Основной способ набрать корпус.
- `refresh_stats` — через `videos.batchGetStats`, ~1 unit за 50 видео.

Каждый сборщик возвращает поле `quota` с фактическим расходом.

И ещё: с 21 июля 2025 `chart=mostPopular` отдаёт только чарты Музыки, Фильмов
и Игр — общей вкладки Trending у YouTube больше нет. Поэтому
`most_popular_categories` и `trending_keywords` считаются по вашему
собственному корпусу, а не по чарту.

---

## Запуск в Docker (рекомендуется)

```bash
cd ~/Desktop/projects/youtube/analytic
cp .env.example .env          # впишите YOUTUBE_API_KEY — без него соберётся,
                              # но собирать данные будет нечем
docker compose build
docker compose up -d web worker   # поднимет и postgres тоже (depends_on)
open http://localhost:8080        # или make open
docker compose logs -f worker
```

Обновляетесь со старой SQLite-версии и хотите сохранить собранные данные?
`python3 backend/migrate_sqlite_to_postgres.py path/to/old/niches.db` (один
раз, после `docker compose up -d postgres`; безопасно запускать повторно).

Дашборд — это `frontend/`, см. [frontend/README.md](../frontend/README.md).
Он показывает те же секции, что и MCP-инструменты, и слушает только localhost.

Ключ нужен только на запуске, не на сборке: `docker compose build` проходит и с
пустым `.env`. Если ключа нет, воркер скажет об этом и выйдет, а инструменты
чтения продолжат работать по тому, что уже собрано.

Воркер — не опция, а необходимость: YouTube API отдаёт только «сколько
просмотров прямо сейчас». Скорость набора просмотров, ускорение, рост
подписчиков, сравнение периодов и детект смены обложки существуют только
потому, что кто-то регулярно записывает цифры. Этим и занимается воркер.

Подключение к Claude Desktop — в
`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "niche-finder": {
      "command": "/Users/kamola/Desktop/projects/youtube/analytic/scripts/mcp-docker.sh"
    }
  }
}
```

Скрипт сам подставит `--env-file` и подключит те же тома, что и воркер, так
что инструменты сразу видят всё собранное. Если хотите без скрипта:

```json
{
  "mcpServers": {
    "niche-finder": {
      "command": "docker",
      "args": ["run", "--rm", "-i",
               "--network", "niche-finder_default",
               "--env-file", "/Users/kamola/Desktop/projects/youtube/analytic/.env",
               "-v", "niche-finder-models:/models",
               "niche-finder:latest", "python", "server.py"]
    }
  }
}
```

### Если сборка падает на Docker Hub

```
failed to fetch anonymous token: ... lookup auth.docker.io: i/o timeout
```

Это сеть, а не код: Docker не может достучаться до реестра образов. Чаще всего
виноват включённый VPN (корпоративные клиенты вроде AnyConnect регулярно
заворачивают или роняют трафик к registry) — отключите и повторите. Если VPN ни
при чём, перезапустите Docker Desktop: `i/o timeout` именно на `auth.docker.io`
почти всегда лечится этим. Проверить, в Docker ли дело:

```bash
curl -sI https://auth.docker.io/token | head -1   # с Mac напрямую
docker pull hello-world                            # через Docker
```

Если первое работает, а второе нет — проблема в DNS Docker Desktop.

**Пересборка при этом почти никогда не нужна.** Все сервисы запускают код прямо
из `backend/` и `frontend/` (папки смонтированы в контейнер только для чтения),
поэтому образ нужен лишь ради Python и зависимостей. `docker compose build`
обязателен только когда меняется `requirements.txt`; в остальных случаях хватает
`docker compose restart`. А если образ собран старой версией `requirements.txt`,
web-сервис доставит недостающие `fastapi`/`uvicorn` с pypi при старте сам —
pypi.org и registry.docker.io это разные хосты, и первый обычно доступен, даже
когда второй нет.

### Первым делом — `doctor`

```bash
docker compose run --rm mcp python cli.py doctor
# или просто: make doctor
```

Он по порядку проверяет ключ (форму и что API реально отвечает), доступность
`googleapis.com`, состояние базы и покрытие окна 24 часа — и в конце печатает
список того, что чинить, конкретными словами: не включён YouTube Data API v3,
ограничение по IP/referrer у ключа, исчерпана квота, пустая база, нет истории.
Одна проверка стоит 1 unit квоты.

### CLI: всё то же самое без Claude Desktop

```bash
make cli ARGS="collect-channel @somechannel"      # набрать корпус, дёшево
make cli ARGS="collect 'ai automation' --period 24h"
make cli ARGS="refresh"                           # обновить счётчики → история
make cli ARGS="viral --period 24h"
make cli ARGS="viral --period 24h --period-by discovered"
make cli ARGS="categories --period 7d --rank-by channels"
make cli ARGS="keywords --period 24h"
make cli ARGS="channels --period 24h"             # outlier-каналы
make cli ARGS="seed"                              # синтетика, чтобы просто посмотреть
```

Полезные команды (`make help` покажет все):

```bash
make up          # поднять воркер
make logs        # смотреть, что он собирает
make test        # смоук-тесты внутри образа, без ключа и без сети
make seed        # налить синтетические данные и пощупать инструменты
make stats       # что сейчас в базе
make http        # поднять MCP по HTTP на :8765 вместо stdio
```

Сервис `mcp` (то есть `make cli` и `make doctor`) монтирует `./backend` внутрь
контейнера только для чтения, поэтому правки в коде видны сразу, без пересборки.
Воркер, `mcp-http` и `scripts/mcp-docker.sh` работают с кодом, запечённым в
образ — для них нужен `docker compose build`.

База лежит в томе `niche-finder-postgres-data` (сервис `postgres`), кэш модели
эмбеддингов — в `niche-finder-models`. Пересборка образа их не трогает.

`docker compose build --build-arg PREFETCH_MODEL=1` запечёт модель
эмбеддингов (~220 МБ) прямо в образ, если не хотите ждать скачивания при
первом семантическом поиске.

---

## Запуск без Docker

```bash
cd ~/Desktop/projects/youtube/analytic/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # впишите YOUTUBE_API_KEY
python3 tests/test_smoke.py   # должно быть 17/17 passed -- нужен доступный Postgres
                              # (docker compose up -d postgres, или свой; см. infrastructure/postgres/connection.py)
```

То же самое короче, через Makefile (из корня проекта):

```bash
make local-install   # venv + зависимости, один раз
make local-test      # смоук-тесты на хосте
make local-run       # MCP-сервер на хосте (без Docker)
make dev             # HTTP-дашборд на хосте: uvicorn api:app --reload на :8080
```

Конфиг Claude Desktop:

```json
{
  "mcpServers": {
    "niche-finder": {
      "command": "/Users/kamola/Desktop/projects/youtube/analytic/backend/.venv/bin/python3",
      "args": ["/Users/kamola/Desktop/projects/youtube/analytic/backend/server.py"]
    }
  }
}
```

История в этом режиме не собирается сама — запускайте `python3 worker.py`
отдельно (или по cron), иначе поля скорости останутся пустыми.

---

## Инструменты

### Сбор (тратят квоту)

| Инструмент | Что делает | Цена |
|---|---|---|
| `collect_niche` | поиск по теме → видео + каналы + эмбеддинги в базу. `period="24h"` вместо ручной даты | 1 поиск/страница из 100 в сутки |
| `collect_channel` | загрузки канала через uploads-плейлист; принимает UC-id, @handle или URL | ~1 unit / 50 видео |
| `collect_trending` | снапшот чарта mostPopular (Музыка/Фильмы/Игры) | ~1 unit / страница |
| `refresh_stats` | перечитать счётчики и дописать снапшот — то, из чего берутся скорости | ~1 unit / 50 видео |
| `refresh_channels` | снапшот подписчиков/просмотров каналов | ~1 unit / 50 каналов |
| `refresh_categories` | актуальная карта id → название категории | 1 unit / регион |

### Разделы (бесплатно, сколько угодно)

| Инструмент | Что даёт |
|---|---|
| `viral_videos_small_channels` | вирусные видео у маленьких каналов за период; VSR, age-adjusted outlier, VPH, ускорение |
| `recently_added_outlier_channels` | то же, но на уровне каналов: множитель + полоса силы 0–4 |
| `high_future_competition` | молодые быстрорастущие каналы, которые вот-вот станут вашими конкурентами |
| `most_popular_categories` | рейтинг категорий за период + сдвиг доли против предыдущего окна; `rank_by="views"` или `"channels"` |
| `trending_keywords` | растущие фразы с momentum и outlier-lift |
| `search_outliers` | outlier-поиск по базе, с семантическим ранжированием по `query` |
| `niche_overview` | насыщенность ниши: распределение каналов по размеру, viral skew, доля Shorts |
| `list_niches`, `db_stats` | что собрано |
| `data_coverage` | хватает ли данных на запрошенное окно — вызывайте первым, если раздел пустой |

### Трекинг и анализ каналов

| Инструмент | Что даёт |
|---|---|
| `track_channel` / `untrack_channel` / `list_tracked_channels` | вотчлист для истории |
| `channel_analytics` | профиль, каденс, медиана vs среднее, viral skew, рост 24h/7d/30d/90d, momentum, грейд, проекции, две модели дохода, топ-outliers |
| `compare_channels` | сравнение, ранжирование по просмотрам на подписчика |
| `channel_velocity` | VPH lifetime, VPH за 24ч, прирост за сутки, «разгоняется / затухает» |
| `title_changes` | кто переименовал видео или сменил обложку |
| `best_time_to_publish` | 168 слотов недели по медианному age-adjusted outlier |
| `title_patterns` | какие фразы в заголовках коррелируют с пробитиями |
| `calibrate_maturity_curve` | пересчитать кривую зрелости по своим данным |

---

## Как этим пользоваться

**День первый — набрать корпус.** Дешёвый путь: найдите 20–50 каналов в вашей
теме и залейте их через `collect_channel` (это ~1 unit за 50 видео, поиск не
тратится). Дорогой, но нужный для открытия новых тем — `collect_niche`.

```
collect_niche(query="гипотезы о мозге и памяти", label="brain", language="ru", period="30d", pages=2)
collect_channel(channel="@some-channel", niche="brain")
```

### Важно: что означает «за последние 24 часа»

У всех разделов есть параметр `period_by`:

- `"published"` (по умолчанию) — **что вышло** в окне. Обычное человеческое чтение.
- `"discovered"` — **что мы впервые увидели** в окне.

Это не педантизм. На скриншотах NexLev в списке «Viral Videos On Small Channels
— Last 24 hours» лежат ролики с подписью «1 year ago». Значит их окно — про
попадание в индекс, а не про дату публикации. Оба режима полезны:
`published` отвечает «что нового вышло», `discovered` — «что нового я нашёл».
Чтобы воспроизвести поведение NexLev, передавайте `period_by="discovered"`.

**Дальше — смотреть разделы.** Они бесплатны, гоняйте сколько угодно:

```
viral_videos_small_channels(period="24h", max_subscribers=10000, sort_by="viral")
viral_videos_small_channels(period="24h", period_by="discovered")   # как у NexLev
recently_added_outlier_channels(period="24h")
most_popular_categories(period="7d", rank_by="channels")
trending_keywords(period="24h", sort_by="trend")
niche_overview(niche="brain")
```

**Постоянно — держать воркер включённым.** Через сутки появятся `vph24h` и
`viewsGained24h`, через неделю — рост каналов и `momentum`, через месяц —
`calibrate_maturity_curve()` пересчитает кривую под ваши ниши.

Чтобы темы обновлялись сами, задайте в `.env`:

```
WORKER_QUERIES=ai automation,faceless history,нейросети для бизнеса
WORKER_QUERY_PERIOD=24h
```

Каждая тема — один поисковый вызов в сутки, так что до ~90 тем безопасно.

### Пустой результат объясняет сам себя

`viral_videos_small_channels` возвращает `funnel` — сколько видео осталось
после каждого фильтра — и `hint` с конкретным параметром, который всё отсёк:

```json
"funnel": [
  {"step": "videos in window",        "remaining": 64},
  {"step": "channel subs <= 10,000",  "remaining": 33},
  {"step": "video views >= 10,000",   "remaining": 25}
],
"hint": null
```

Остальные разделы возвращают `hint`, когда результат пуст. В CLI подсказка
дополнительно печатается отдельной строкой.

**Если раздел вернул пусто** — почти всегда дело не в том, что «ничего не
трендит», а в том, что в это окно ничего не собрано. `data_coverage(period=…)`
покажет разницу.

---

## Формулы

Полный разбор — в [`../docs/research-tools.md`](../docs/research-tools.md),
код — в `metrics.py`. Коротко:

```
outlierScore        = views / медиана просмотров предыдущих 10 long-form загрузок
outlierScoreAdjusted= views / (baseline * maturity(возраст в днях))
outlierScoreNexlev  = views / (channel.viewCount // channel.videoCount)   # для сверки с NexLev
viewsPerSubscriber  = views / подписчики
viralScore          = прогноз просмотров на 30 дней / подписчики
vphLifetime         = views / часов с публикации          # это и есть "VPH" в UI NexLev
vph24h              = (views_сейчас - views_24ч_назад) / 24               # нужна история
acceleration        = vph24h сегодня / vph24h вчера                       # >1.5 разгоняется
momentum            = просмотров в день за 30д / просмотров в день за всё время
revenue             = месячные просмотры / 1000 * RPM ниши * 0.70
```

Медиана вместо среднего — принципиально: у NexLev baseline это среднее за всю
жизнь канала, и один вирусный ролик его разрушает (наблюдаемое отношение
среднего к медиане доходит до 27x).

---

## Структура

С 5.09.2026 backend переписан по слоям DDD/Clean Architecture (domain →
infrastructure → application → interfaces), но **все точки входа остались
на старых путях**: `server.py`, `api.py`, `cli.py`, `worker.py` в
`backend/` — это тонкие «шимы» (composition root), которые просто
импортируют реальный код из нового места. Поэтому `docker compose up`,
`python cli.py ...`, `uvicorn api:app` и весь Makefile работают
без изменений. Старые плоские модули (`db.py`, `trends.py`, `query.py` и
т.д.) сохранены нетронутыми в `backend/_legacy_flat_modules/` — как
референс/страховка, в коде на них никто больше не ссылается.

```
analytic/
├── docker-compose.yml      воркер + MCP (stdio и HTTP-профиль)
├── Makefile                make up / logs / test / seed / stats / dev
├── .env.example            ключ и настройки воркера
├── scripts/mcp-docker.sh   лончер MCP в Docker для Claude Desktop
├── frontend/               дашборд: index.html, styles.css, ui.js, app.js
├── docs/
│   ├── context.md          история решений по проекту
│   └── research-tools.md   разбор рынка, формулы, что воспроизводимо
└── backend/
    ├── Dockerfile
    ├── server.py           шим: python server.py -> interfaces.mcp.server
    ├── cli.py              шим: python cli.py ...  -> interfaces.cli.cli
    ├── api.py              шим: uvicorn api:app    -> interfaces.http.api
    ├── worker.py           шим: python worker.py   -> application.worker_cycle
    ├── migrate_sqlite_to_postgres.py   разовый перенос данных из старого niches.db
    │
    ├── domain/             чистые правила, без внешних зависимостей
    │   ├── metrics.py          все формулы (outlier, VPH, revenue, ...)
    │   ├── periods.py          разбор 24h / 7d / 30d / all
    │   ├── keywords.py         n-граммы, momentum, lift
    │   ├── scoring.py          обратная совместимость (see metrics.py)
    │   └── categories_catalog.py  чистые категории YouTube + офлайн-фолбэк
    │
    ├── infrastructure/     адаптеры к внешнему миру
    │   ├── postgres/           connection.py, schema.py, repositories.py
    │   │                       (схема Postgres v2, sqlite3-совместимый шим)
    │   ├── youtube/client.py   обёртка над YouTube Data API v3 + модель квот
    │   ├── embeddings/fastembed_provider.py  локальные мультиязычные эмбеддинги
    │   └── categories/repository.py          категории, кэш в Postgres + YouTube API
    │
    ├── application/        оркестрация сценариев (use cases)
    │   ├── collecting.py       всё, что тратит квоту YouTube (было collector.py)
    │   ├── discovery.py        три раздела за период (было trends.py)
    │   ├── channel_tracking.py трекинг и анализ каналов (было tracking.py)
    │   ├── search.py           outlier-поиск и обзор ниши (было query.py)
    │   └── worker_cycle.py     цикл фонового сборщика (было worker.py)
    │
    ├── interfaces/         тонкие адаптеры наружу
    │   ├── mcp/server.py       MCP-сервер, 26 инструментов
    │   ├── http/api.py         HTTP API для дашборда (FastAPI)
    │   ├── cli/cli.py          то же из терминала + doctor (диагностика)
    │   └── worker/main.py      точка входа фонового сборщика
    │
    ├── _legacy_flat_modules/   старые плоские модули, не импортируются нигде
    └── tests/              smoke-тесты и синтетический сид
```
