# NFL Odds Dashboard — Copilot Instructions

## Project overview
Streamlit dashboard for NFL betting odds analysis.
- **Entrypoint:** `app.py`
- **Data logic:** `utils.py`
- **Auth:** `auth.py`
- **Run:** `streamlit run app.py`

## ⚠️ Security — CRITICAL
- `.streamlit/secrets.toml` is gitignored and must NEVER be committed
- Access secrets only via `st.secrets["KEY"]` or `os.environ.get("KEY")`
- Never hardcode API keys or credentials in any file
- All tests in `/tests` must run without real API keys — use `unittest.mock`

## Code standards
- Python 3.11+, PEP8, type hints required
- Add new dependencies to `requirements.txt`
- Use `@st.cache_data` for expensive data fetches in app.py
