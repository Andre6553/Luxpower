/** LuxPower-style weather summary + Solar Generation Forecast chart. */
const FORECAST_COLORS = {
  today: "#1e81b0",
  tomorrow: "#76b5c5",
};

let forecastChart = null;

function forecastEl(id) {
  return document.getElementById(id);
}

function destroyForecastChart() {
  if (forecastChart) {
    forecastChart.destroy();
    forecastChart = null;
  }
}

function renderWeatherCard(payload) {
  const card = forecastEl("luxWeatherCard");
  if (!card) return;

  const weather = payload.weather || {};
  const hasWeather = Boolean(payload.location || weather.conditions);
  card.hidden = !hasWeather;

  const cond = forecastEl("forecastConditions");
  const temps = forecastEl("forecastTemps");
  const loc = forecastEl("forecastLocation");
  const todayDate = forecastEl("forecastTodayDate");
  const tomorrowDate = forecastEl("forecastTomorrowDate");
  const todayYield = forecastEl("forecastTodayYield");
  const tomorrowYield = forecastEl("forecastTomorrowYield");

  if (cond) cond.textContent = weather.conditions || "—";
  if (temps) {
    const min = weather.tempMin || "—";
    const max = weather.tempMax || "—";
    temps.textContent = min === max ? String(min) : `${min} ~ ${max}`;
  }
  if (loc) loc.textContent = payload.location || "—";
  if (todayDate) todayDate.textContent = payload.localDate || "Today";
  if (tomorrowDate) tomorrowDate.textContent = payload.localTomorrowDate || "Tomorrow";
  if (todayYield) {
    todayYield.textContent =
      payload.yieldTodayKwh != null ? `${payload.yieldTodayKwh} kWh` : "—";
  }
  if (tomorrowYield) {
    tomorrowYield.textContent =
      payload.yieldTomorrowKwh != null ? `${payload.yieldTomorrowKwh} kWh` : "—";
  }
}

function renderForecastChart(payload) {
  const canvas = forecastEl("solarForecastChart");
  const section = forecastEl("luxForecastSection");
  if (!canvas || !section) return;

  const hours = payload.hours || [];
  if (!hours.length) {
    section.hidden = true;
    destroyForecastChart();
    return;
  }

  section.hidden = false;
  if (typeof Chart === "undefined") {
    throw new Error("Chart.js did not load");
  }

  const labels = hours.map((row) => String(row.hour));
  destroyForecastChart();
  forecastChart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Today Solar Energy",
          data: hours.map((row) => row.todayKwh),
          borderColor: FORECAST_COLORS.today,
          backgroundColor: "transparent",
          pointBackgroundColor: FORECAST_COLORS.today,
          pointRadius: 3,
          pointHoverRadius: 4,
          tension: 0.35,
          borderWidth: 2,
        },
        {
          label: "Tomorrow Solar Energy",
          data: hours.map((row) => row.tomorrowKwh),
          borderColor: FORECAST_COLORS.tomorrow,
          backgroundColor: "transparent",
          pointBackgroundColor: FORECAST_COLORS.tomorrow,
          pointRadius: 3,
          pointHoverRadius: 4,
          tension: 0.35,
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          position: "top",
          align: "end",
          labels: { boxWidth: 12, usePointStyle: true, font: { size: 11 } },
        },
        tooltip: {
          callbacks: {
            title(items) {
              const hour = items[0]?.label ?? "0";
              return `Time: ${String(hour).padStart(2, "0")}:00`;
            },
            label(ctx) {
              return `${ctx.dataset.label}: ${ctx.parsed.y} kWh`;
            },
          },
        },
      },
      scales: {
        x: {
          title: { display: false },
          grid: { color: "#eef0f2" },
          ticks: { color: "#888", font: { size: 10 } },
        },
        y: {
          title: {
            display: true,
            text: "Energy (kWh)",
            color: "#aaa",
            font: { size: 10 },
          },
          beginAtZero: true,
          grid: { color: "#eef0f2" },
          ticks: { color: "#888", font: { size: 10 } },
        },
      },
    },
  });
}

function setForecastError(msg) {
  const node = forecastEl("forecastError");
  if (!node) return;
  node.textContent = msg || "";
  node.hidden = !msg;
}

async function refreshForecast() {
  try {
    const res = await fetch(`/api/luxpower/forecast?_=${Date.now()}`, { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    renderWeatherCard(data);
    renderForecastChart(data);
    setForecastError("");
  } catch (err) {
    setForecastError(String(err.message || err));
    console.error(err);
  }
}

window.refreshForecast = refreshForecast;

document.addEventListener("DOMContentLoaded", () => {
  refreshForecast().catch(console.error);
  setInterval(() => refreshForecast().catch(console.error), 15 * 60 * 1000);
});
