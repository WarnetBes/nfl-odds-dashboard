# 🏈 NFL Odds Dashboard

Интерактивный дашборд для просмотра живых коэффициентов на матчи NFL с расчётом value bets и сравнением букмекеров.

## Возможности
- 📊 Живые коэффициенты от 40+ букмекеров (DraftKings, FanDuel, BetMGM, Caesars и др.)
- 🎯 Value Bet детектор с расчётом EV Edge
- 📈 Интерактивные графики сравнения Odds
- 🔢 No-Vig вероятности (честные шансы без маржи)
- 🌍 Регионы: US, UK/EU, Australia
- 📋 Рынки: H2H (Moneyline), Spreads, Totals

## Запуск локально

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Деплой на Streamlit Community Cloud

1. Форкни/загрузи репозиторий на GitHub
2. Зайди на https://share.streamlit.io
3. Нажми "New app" → выбери репозиторий
4. Main file: `app.py`
5. Deploy!

## API Key

Получи бесплатный ключ на https://the-odds-api.com (500 запросов/мес бесплатно).

## Структура данных

The Odds API возвращает:
- Матч (home_team, away_team, commence_time)
- Букмекер (key, title)
- Рынок (h2h, spreads, totals)
- Коэффициенты (American format)

## Value Bet формула

```
1. Implied Prob = |odds| / (|odds| + 100) × 100  (для фаворитов)
2. Implied Prob = 100 / (odds + 100) × 100        (для аутсайдеров)
3. No-vig Prob = implied_prob / sum(all_implied_probs) × 100
4. EV Edge = no_vig_prob × decimal_odds - 1
5. Value Bet если EV Edge > порог
```
