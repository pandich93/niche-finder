# niche-finder

[![CI](https://img.shields.io/github/actions/workflow/status/pandich93/niche-finder/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/pandich93/niche-finder/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fpandich93%2Fniche-finder%2Fmain%2Fassets%2Fcoverage.json&query=%24.totals.percent_covered_display&suffix=%25&label=coverage&style=flat-square)](assets/coverage.json)
[![License: MIT](https://img.shields.io/github/license/pandich93/niche-finder?style=flat-square)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square&logo=python&logoColor=white)](backend/Dockerfile)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](backend/interfaces/http/api.py)
[![PostgreSQL 16](https://img.shields.io/badge/postgres-16-336791?style=flat-square&logo=postgresql&logoColor=white)](docker-compose.yml)
[![Docker Compose](https://img.shields.io/badge/docker-compose-2496ED?style=flat-square&logo=docker&logoColor=white)](docker-compose.yml)
[![MCP](https://img.shields.io/badge/MCP-24%20tools-8A2BE2?style=flat-square)](backend/interfaces/mcp/server.py)
[![Last commit](https://img.shields.io/github/last-commit/pandich93/niche-finder?style=flat-square)](https://github.com/pandich93/niche-finder/commits/main)

Свой аналог NexLev / vidIQ / ViewStats: поиск ниш, вирусных видео у маленьких
каналов, трендовых категорий и ключевых слов за произвольные периоды (24 часа,
48 часов, 7/30/90 дней), плюс полноценный трекинг и разбор YouTube-каналов.
Работает на бесплатном YouTube Data API v3 и локальном PostgreSQL — никакой
подписки, никакого платного LLM-ключа: классификацию вида «faceless / подходит
по смыслу» делает модель, которая вызывает эти инструменты, а не сервер.

![Дашборд niche-finder: обзор — каналы, видео, outlier-каналы, трендовые категории и ключевые слова](assets/dashboard.jpg)

У проекта две части, которые вместе и составляют «продукт»:

- **`backend/`** — Python: MCP-сервер (24 инструмента для Claude), HTTP API
  для дашборда и фоновый воркер, который пишет историю просмотров/подписчиков
  по расписанию (без этого не существует «скорость роста за 24 часа» — YouTube
  API отдаёт только «сейчас»).
- **`frontend/`** — тот же функционал, но глазами: дашборд на чистых ES-модулях
  (без npm и шага сборки), который дёргает HTTP API backend'а.

Обе части и хранилище Postgres запускаются вместе одной командой (см. ниже) —
дашборд и Claude Desktop в итоге смотрят в одну и ту же базу.

## Возможности

- Поиск вирусных видео и outlier-каналов по нише за произвольный период
  (24ч / 48ч / 7 / 30 / 90 дней)
- Трендовые категории и ключевые слова, лучшее время публикации, паттерны
  заголовков
- Трекинг конкретных каналов: скорость роста просмотров/подписчиков, история
  снапшотов
- Один и тот же расчёт в Claude Desktop (через MCP) и на веб-дашборде —
  общая кодовая база, не две реализации
- Только бесплатный YouTube Data API v3 и локальный PostgreSQL — без платных
  подписок и без LLM-ключа на стороне сервера

## Содержание

- [Экраны](#экраны)
- [Как это устроено](#как-это-устроено)
- [Быстрый старт](#быстрый-старт)
- [Структура репозитория](#структура-репозитория)
- [Дальше читать](#дальше-читать)

## Экраны

<table>
<tr>
<td width="50%"><img src="assets/viral.jpg" alt="Вирусные видео у маленьких каналов"><br><sub>Вирусные видео — маленькие каналы, выстрелившие сильнее ожидаемого</sub></td>
<td width="50%"><img src="assets/outliers.jpg" alt="Outlier-каналы"><br><sub>Outlier-каналы — множитель лучшего видео против медианы канала</sub></td>
</tr>
<tr>
<td width="50%"><img src="assets/categories.jpg" alt="Категории"><br><sub>Категории — доля и рост по нишам YouTube</sub></td>
<td width="50%"><img src="assets/keywords.jpg" alt="Ключевые слова"><br><sub>Ключевые слова — trendScore, lift, momentum</sub></td>
</tr>
<tr>
<td width="50%"><img src="assets/tracker.jpg" alt="Трекер каналов"><br><sub>Трекер каналов — сбор и отслеживание конкретных каналов</sub></td>
<td width="50%"><img src="assets/niches.jpg" alt="Ниши"><br><sub>Ниши — всё, что собрано под пользовательскими ярлыками</sub></td>
</tr>
<tr>
<td width="50%"><img src="assets/data.jpg" alt="Данные"><br><sub>Данные — состояние базы и ручной сбор/обновление статистики</sub></td>
<td width="50%"></td>
</tr>
</table>

## Как это устроено

```mermaid
flowchart LR
    CD["Claude Desktop"] -->|MCP| MCP["MCP-сервер\nbackend/server.py"]
    FE["Браузер / frontend"] -->|HTTP| API["HTTP API\nbackend/api.py"]
    YT["YouTube Data API v3"] <-->|"по расписанию"| W["Фоновый воркер\nbackend/worker.py"]
    MCP --> PG[("PostgreSQL")]
    API --> PG
    W --> PG
```

MCP-сервер, HTTP API и воркер — это три разных входа в один и тот же код:
все три вызывают одни и те же сценарии из `backend/application/`, поэтому
результат в Claude Desktop и на дашборде — буквально один и тот же расчёт,
а не две отдельные реализации. Подробный разбор слоёв backend'а (с 5 сентября
2026 — DDD: domain → infrastructure → application → interfaces) — в
[backend/README.md](backend/README.md#структура).

## Быстрый старт

Через Docker (рекомендуется — поднимает Postgres, воркер и дашборд разом):

```bash
cp .env.example .env          # впишите YOUTUBE_API_KEY (не обязателен для сборки)
docker compose build
make up                       # или: docker compose up -d web worker
make doctor                   # проверить ключ, сеть и базу
open http://localhost:8080    # дашборд
```

Без Docker (нужен свой доступный Postgres):

```bash
make local-install            # venv + зависимости backend, один раз
make dev                      # HTTP-дашборд на http://localhost:8080
make local-run                # или: MCP-сервер на хосте, для Claude Desktop
```

`make help` печатает все доступные команды с однострочным описанием каждой.

## Структура репозитория

| Путь | Что внутри |
|---|---|
| [`backend/`](backend/README.md) | MCP-сервер, HTTP API, воркер — вся логика и хранение данных |
| [`frontend/`](frontend/README.md) | дашборд: index.html, styles.css, ui.js, app.js |
| `docker-compose.yml` | postgres + worker + web + mcp/mcp-http сервисы |
| `Makefile` | команды запуска что через Docker, что напрямую на хосте |
| `.env.example` | ключ YouTube и настройки воркера |
| `scripts/mcp-docker.sh` | лончер MCP-сервера в Docker для Claude Desktop |

`docs/` (история решений и разбор рынка) — внутренние заметки, в этот
репозиторий не входят.

## Дальше читать

- [backend/README.md](backend/README.md) — квоты YouTube API, все 24
  инструмента с описанием, как читать `period_by`, запуск с Docker и без,
  структура DDD-слоёв.
- [frontend/README.md](frontend/README.md) — экраны дашборда, откуда берутся
  данные, как устроена палитра.
