import io
import base64
import matplotlib.pyplot as plt
import mplfinance as mpf
from backend.core.mstock_api import fetch_historical_data

def generate_signal_chart(symbol, timeframe="5m", api_key=None, access_token=None):
    # Fetch data
    df = fetch_historical_data(symbol, api_key, access_token, timeframe)
    if df.empty:
        raise ValueError("No data to plot")

    df.dropna(inplace=True)

    # Calculate Buy/Sell signals
    df['Buy'] = (df['EMA7'] > df['EMA21']) & (df['EMA7'].shift(1) <= df['EMA21'].shift(1))
    df['Sell'] = (df['EMA7'] < df['EMA21']) & (df['EMA7'].shift(1) >= df['EMA21'].shift(1))

    buys = df[df['Buy']]
    sells = df[df['Sell']]

    # Prepare buy/sell markers for mplfinance
    apds = [
        mpf.make_addplot(df['EMA7'], color='blue', width=1.0),
        mpf.make_addplot(df['EMA21'], color='orange', width=1.0),
        mpf.make_addplot(buys['close'], type='scatter', marker='^', markersize=100, color='green'),
        mpf.make_addplot(sells['close'], type='scatter', marker='v', markersize=100, color='red')
    ]

    # Create candlestick chart
    fig, ax = mpf.plot(
        df,
        type='candle',
        style='yahoo',
        title=f"{symbol} ({timeframe}) - EMA Crossover Signals",
        ylabel="Price",
        ylabel_lower="Volume",
        addplot=apds,
        volume=True,
        returnfig=True,
        figsize=(10, 6)
    )

    # Save to base64
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)

    return img_base64
