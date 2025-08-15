# config.py

import os
from backend.core.config import API_KEY, ACCESS_TOKEN
# === MStock API Configuration ===
MSTOCK_API_KEY = os.getenv("MSTOCK_API_KEY", "fmm5ClnXQiIVywK8odARaw==")
MSTOCK_BASE_URL = "https://api.mstock.trade/openapi/typea"

# === Default Screener Settings ===
DEFAULT_SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "BAJFINANCE"]
DEFAULT_THRESHOLD = 2.0  # % Change

# === ML Settings ===
MODEL_PATH = "backend/models/rf_model.pkl"

# === Sentiment Source ===
MONEYCONTROL_NEWS_URL = "https://www.moneycontrol.com/news/business/markets/"

# === Logging Config ===
LOG_FILE = "logs/tradingbot.log"

# === Flask App Settings ===
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
FLASK_DEBUG = True
