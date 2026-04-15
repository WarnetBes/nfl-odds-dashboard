# 🏈 Sports Odds Dashboard

[![CI](https://github.com/WarnetBes/nfl-odds-dashboard/actions/workflows/ci.yml/badge.svg)](https://github.com/WarnetBes/nfl-odds-dashboard/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-Cloud-FF4B4B.svg)](https://nfl-odds-dashboard-cwetbvdeqon6p5ujc7hz6u.streamlit.app/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Интерактивный дашборд для анализа спортивных коэффициентов — NFL, EPL и NBA.  
Value Bets с EV Edge, Arbitrage (суребеты), Kelly Stake, Live Scores, История ставок и статистика банкролла.

🌐 **Live:** https://nfl-odds-dashboard-cwetbvdeqon6p5ujc7hz6u.streamlit.app/  
⚡ **PWA (Cloudflare):** https://sports-odds-dashboard.warnetbesholin.workers.dev

---

## Возможности

| Вкладка | Описание |
|---|---|
| 🎯 **Сигналы** | Sharp EV + Kelly Stake для H2H, Spreads, Totals — кому ставить и сколько |
| ⚡ **Арбитраж** | Автопоиск суребетов по всем лигам, калькулятор распределения ставок |
| 📋 **Коэффициенты** | Живые odds от 40+ букмекеров (DraftKings, FanDuel, Pinnacle, Bet365 и др.) |
| 📊 **Сравнение** | Интерактивные графики odds по букмекерам |
| 💎 **Value Bets** | Детектор с EV Edge > порога, авто-уведомления на Gmail |
| 📺 **Live Scores** | Актуальные счёты матчей NFL, EPL, NBA через ESPN Public API |
| 📊 **История ставок** | Логирование value bets в Google Sheets по дате/матчу/EV |
| 💰 **Статистика банкролла** | P&L по дням, ROI по букмекеру, ожидаемый Kelly-рост |

---

## Быстрый старт

```bash
git clone https://github.com/WarnetBes/nfl-odds-dashboard.git
cd nfl-odds-dashboard
pip install -r requirements.txt
streamlit run app.py
```

При первом запуске введи API-ключ [The Odds API](https://the-odds-api.com) в боковой панели.  
Ключ сохраняется в `st.secrets` / environment variable и не сбрасывается между сессиями.

---

## CI / Тесты

GitHub Actions автоматически запускает тесты при каждом `push` и `pull_request` в `main`.

```bash
# Запустить тесты локально
python -m pytest tests/ -v --tb=short
```

- **Python:** 3.11 и 3.12 (матричный запуск)
- **Тест-файлы:** `tests/test_*.py` — 260+ тестов
- **Блокировка merge** при падении любого теста (`fail-fast: true`)

### Покрытие тестами

| Модуль | Что тестируется |
|---|---|
| `test_value_bets.py` | `build_betting_signals()`, EV Edge, No-Vig prob |
| `test_utils.py` | Kelly Stake, Sharp EV, `find_arb_in_group()` |
| `test_live_scores.py` | Mock ESPN API — пустой ответ, LIVE/Finished статусы |
| `test_api_key_and_fetch.py` | Чтение ODDS_API_KEY из secrets/env, mock fetch_odds (25 тестов) |

---

## AI-агенты для анализа value bets

Дашборд совместим с несколькими Python AI-агент фреймворками.  
Рекомендуемый выбор — **CrewAI** как наиболее лёгкий и быстрый для интеграции со Streamlit.

### Сравнение фреймворков

| Фреймворк | Лучше всего подходит | Установка | Латентность | ~LoC для агента |
|---|---|---|---|---|
| **CrewAI** ✅ | Role-based агенты, быстрый прототип | `pip install crewai` | ~1.8 с | ~35 |
| **LangChain / LangGraph** | Сложные stateful пайплайны, RAG | `pip install langchain` | ~1.2 с | ~80 |
| **AutoGen** | Multi-agent + выполнение кода | `pip install pyautogen` | ~2.1 с | ~40 |
| **LlamaIndex** | Data-centric / RAG пайплайны | `pip install llama-index` | ~1.5 с | ~50 |

### Пример минимальной интеграции (CrewAI)

```python
from crewai import Agent, Task, Crew

odds_analyst = Agent(
    role="Odds Analyst",
    goal="Analyse EV Edge and Kelly signals from betting data",
    backstory="Expert in sports betting mathematics and value detection"
)

strategist = Agent(
    role="Betting Strategist",
    goal="Recommend optimal stake sizing based on Kelly criterion",
    backstory="Specialises in bankroll management and risk-adjusted returns"
)

risk_manager = Agent(
    role="Risk Manager",
    goal="Monitor exposure and flag overbet situations",
    backstory="Tracks book limits and portfolio correlation"
)

# Задача: проанализировать список value bets
analyse_task = Task(
    description="Given value bets: {value_bets}, rank by EV Edge and recommend top 3",
    expected_output="Ranked list with stake sizes and rationale",
    agent=odds_analyst
)

crew = Crew(agents=[odds_analyst, strategist, risk_manager], tasks=[analyse_task])
result = crew.kickoff(inputs={"value_bets": value_bets_df.to_dict("records")})
```

### Рекомендации по выбору

- **CrewAI** — если нужен быстрый MVP: три агента (аналитик, стратег, риск-менеджер) за ~35 строк
- **LangGraph** — если нужна условная логика (например, подтверждение перед ставкой, цикл пересчёта)
- **LangChain** — если планируется RAG по историческим данным (подгрузка статистики команд)
- Все три: Apache 2.0, нет привязки к LLM-провайдеру

---

## Архитектура

```
nfl-odds-dashboard/
├── app.py                  # Streamlit приложение (8 вкладок, ~2400 строк)
├── utils.py                # Kelly Stake, Sharp EV, find_arb_in_group()
├── requirements.txt
├── tests/
│   ├── test_value_bets.py
│   ├── test_utils.py
│   ├── test_live_scores.py
│   └── test_api_key_and_fetch.py
├── pwa/
│   ├── manifest.json       # PWA-манифест
│   ├── sw.js               # Service Worker
│   └── offline.html
├── cloudflare-worker/
│   ├── worker.js           # Cloudflare Worker
│   └── wrangler.toml
└── .github/
    └── workflows/
        └── ci.yml          # GitHub Actions CI
```

---

## Формулы

### Value Bet (EV Edge)
```
Implied Prob  = |odds| / (|odds| + 100) × 100   (фаворит, odds < 0)
Implied Prob  = 100 / (odds + 100) × 100          (аутсайдер, odds > 0)
No-Vig Prob   = implied_prob / Σ(all_implied_probs) × 100
EV Edge       = no_vig_prob × decimal_odds − 1
Value Bet если EV Edge > порог (по умолчанию 5%)
```

### Kelly Stake (четверть-Келли, fraction = 0.25)
```
b  = decimal_odds − 1
p  = no_vig_prob / 100
q  = 1 − p
Kelly full  = (b × p − q) / b
Kelly stake = Kelly full × 0.25 × bankroll
```

### Sharp EV (Cross-Book)
```
Sharp fair odds = средние коэффициенты Pinnacle / Betfair / Circa (без маржи)
Sharp EV Edge   = (no_vig_prob_sharp − implied_prob_market) / implied_prob_market
```

### Арбитраж (Surebet)
```
Arb %    = Σ(1 / decimal_odds_i) < 1
Stake_i  = total_stake × (1 / decimal_odds_i) / Σ(1 / decimal_odds_j)
Profit   = total_stake × (1 − Arb %)
```

---

## API и переменные окружения

| Переменная | Описание |
|---|---|
| `ODDS_API_KEY` | [The Odds API](https://the-odds-api.com) — 500 запросов/мес бесплатно |
| `GMAIL_SENDER` | Gmail для отправки уведомлений о value bets |
| `GMAIL_PASSWORD` | App Password (не обычный пароль) |
| `GMAIL_TO` | Адрес получателя уведомлений |
| `GSHEET_URL` | URL Google Sheets для логирования истории ставок |

Ключи хранятся в **GitHub Secrets** и пробрасываются в Streamlit Cloud как environment variables.  
При локальном запуске можно указать в `.streamlit/secrets.toml` или в переменных окружения.

---

## PWA (установка на телефон)

Дашборд поддерживает установку на домашний экран iPhone и Android:

1. Открой https://sports-odds-dashboard.warnetbesholin.workers.dev в Safari / Chrome
2. Нажми «Поделиться» → «На экран Домой» (iOS) или «Установить приложение» (Android)
3. Приложение запустится в полноэкранном режиме без адресной строки
