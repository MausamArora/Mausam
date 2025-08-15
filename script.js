// =====================
// DOM Ready
// =====================
document.addEventListener("DOMContentLoaded", () => {
    // Load default ACC data and initialize
    const defaultStock = "ACC";
    document.getElementById("symbolInput").value = defaultStock;
    addToWatchlist(defaultStock);

    initDefaultData();
    startBot();
    showChart(defaultStock);

    // Button listeners
    const marketSentimentBtn = document.getElementById("marketSentimentBtn");
    if (marketSentimentBtn) marketSentimentBtn.addEventListener("click", runMarketSentiment);

    const runScreenerBtn = document.getElementById("runScreenerBtn");
    if (runScreenerBtn) runScreenerBtn.addEventListener("click", runScreener);

    const chartBtn = document.getElementById("chartBtn");
    if (chartBtn) {
        chartBtn.addEventListener("click", () => {
            const symbol = document.getElementById("symbolInput").value.trim().toUpperCase();
            const timeframe = document.getElementById("timeframeSelect")?.value || "5m";
            if (!symbol) return alert("Please enter a stock symbol first");
            loadChart(symbol, timeframe);
        });
    }
});

// =====================
// Load Default ACC Data
// =====================
async function initDefaultData() {
    try {
        const res = await fetch("/static/data/sample_data.json");
        const data = await res.json();
        if (data && data.symbol) {
            // use the existing updater (avoid undefined function)
            updateTable(data);
            document.getElementById("symbolInput").value = data.symbol;
            await loadChart(data.symbol);
        }
    } catch (err) {
        console.error("Error loading default data:", err);
    }
}

// =====================
// Start Bot Function
// =====================
async function startBot() {
    const symbol = document.getElementById("symbolInput").value.trim().toUpperCase();
    if (!symbol) return alert("Please enter a symbol.");

    try {
        const res = await fetch("/start-bot", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol })
        });

        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        const data = await res.json();

        if (!data || data.error) {
            console.warn("⚠️ API failed, using default data...", data?.error);
            return initDefaultData();
        }

        updateTable(data);

    } catch (err) {
        console.error("Bot start error:", err);
        alert("⚠️ Failed to start bot. Using default data...");
        initDefaultData();
    }
}

// =====================
// Table Update Function
// =====================
function updateTable(data) {
    if (!data?.symbol) {
        console.warn("⚠️ Invalid table data", data);
        return;
    }
    const table = document.getElementById("resultTable");
    const tbody = table.querySelector("tbody");
    table.style.display = "table";

    // Remove "No Data" placeholder row if it exists
    if (tbody.rows.length === 1 && tbody.rows[0].cells.length === 1) {
        tbody.innerHTML = "";
    }

    // Find existing row by symbol or create new
    const existingRow = [...tbody.rows].find(r => r.cells[0]?.innerText === data.symbol);
    const row = existingRow || tbody.insertRow();

    // IMPORTANT: match index.html header order exactly:
    // Symbol | LTP | Buy | Sell | Prediction | Chart | Action
    row.innerHTML = `
        <td>${data.symbol}</td>
        <td>${data.ltp ?? "N/A"}</td>
        <td><button onclick="openOrderModal('${data.symbol}','BUY')">Buy</button></td>
        <td><button onclick="openOrderModal('${data.symbol}','SELL')">Sell</button></td>
        <td>${data.prediction ?? "-"}</td>
        <td><button onclick="showChart('${data.symbol}')" title="View Chart">📈</button></td>
        <td><button onclick="removeStock('${data.symbol}')" title="Remove from table">🗑</button></td>
    `;
}

// =====================
// Remove Stock from Table
// =====================
function removeStock(symbol) {
    const tableBody = document.getElementById("resultTable").querySelector("tbody");
    [...tableBody.rows].forEach(row => {
        if (row.cells[0].innerText === symbol) {
            row.remove();
        }
    });
}

// =====================
// Watchlist Functions
// =====================
function addToWatchlist(symbol) {
    const watchlistTable = document.getElementById("watchlistTable");
    const watchlistBody = document.getElementById("watchlistBody");

    const row = document.createElement("tr");
    row.innerHTML = `
        <td>${symbol}</td>
        <td><button onclick="triggerBot('${symbol}')">Fetch</button></td>
        <td><button onclick="showChart('${symbol}')">📈</button></td>
        <td><button onclick="removeFromWatchlist(this)">🗑</button></td>
    `;
    watchlistBody.appendChild(row);
    watchlistTable.style.display = "table";
}

function removeFromWatchlist(btn) {
    btn.closest("tr").remove();
}

function triggerBot(symbol) {
    document.getElementById("symbolInput").value = symbol;
    startBot();
}

// =====================
// Chart Function with Automatic Fallback
// =====================
async function loadChart(symbol, timeframe = "5m") {
    if (!symbol) return console.warn("No symbol provided for chart loading");

    const chartDiv = document.getElementById("chart");
    chartDiv.innerHTML = "<p>Loading chart...</p>";

    try {
        // Fetch from Flask route
        const res = await fetch(`/chart/${encodeURIComponent(symbol)}?timeframe=${timeframe}`);
        if (!res.ok) throw new Error(`Chart fetch failed: ${res.statusText}`);
        const chartData = await res.json();

        // If no data, fallback (left as-is per your current flow)
        if (!chartData || !chartData.data || !chartData.data.length) {
            console.warn(`No chart data from MStock for ${symbol}, using Yahoo fallback`);
            return await fetchYahooChart(symbol, timeframe);
        }

        renderChart(chartData, symbol);

    } catch (err) {
        console.warn(`Error loading MStock chart for ${symbol}, falling back to Yahoo:`, err);
        await fetchYahooChart(symbol, timeframe);
    }
}

// =====================
// Chart Rendering Helper
// =====================
function renderChart(chartData, symbol) {
    const chartDiv = document.getElementById("chart");
    chartDiv.innerHTML = "";

    let canvas = document.getElementById("chartCanvas");
    if (!canvas) {
        canvas = document.createElement("canvas");
        canvas.id = "chartCanvas";
        chartDiv.appendChild(canvas);
    }

    const sourceLabel = chartData.source ? ` (${chartData.source.toUpperCase()})` : "";
    const ctx = canvas.getContext("2d");

    new Chart(ctx, {
        type: "line",
        data: {
            labels: chartData.data.map(d => d.Date || d.time),
            datasets: [{
                label: `${symbol} Price${sourceLabel}`,
                data: chartData.data.map(d => d.Close ?? d.close),
                borderColor: sourceLabel.includes("YAHOO") ? "green" : "blue",
                fill: false
            }]
        },
        options: {
            responsive: true,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: { title: { display: true, text: "Time" } },
                y: { title: { display: true, text: "Price" } }
            }
        }
    });
}

// =====================
// Order Modal Functions
// =====================
let selectedSymbol = "";
let selectedSide = "";

function openOrderModal(symbol, side) {
    selectedSymbol = symbol;
    selectedSide = side;
    document.getElementById("orderModalTitle").innerText = `${side} Order - ${symbol}`;
    document.getElementById("orderModal").style.display = "block";
}

function closeOrderModal() {
    document.getElementById("orderModal").style.display = "none";
}

async function submitOrder() {
    const data = {
        symbol: selectedSymbol,
        transaction_type: selectedSide,
        quantity: document.getElementById("orderQty").value,
        price: document.getElementById("orderPrice").value,
        sl_price: document.getElementById("orderSL").value,
        trigger_price: document.getElementById("orderTrigger").value,
        order_type: document.getElementById("orderType").value,
        product: document.getElementById("orderProduct").value
    };

    try {
        const res = await fetch("/place-order", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        });

        const result = await res.json();
        if (result.status === "success") {
            alert(`✅ Order Placed\nOrder ID: ${result.order_id}`);
        } else {
            alert(`❌ Order Failed\n${result.message}`);
        }
    } catch (err) {
        console.error("Order error:", err);
        alert("⚠️ Order placement failed.");
    }
    closeOrderModal();
}
