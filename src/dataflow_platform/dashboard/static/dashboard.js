/* Dashboard overview interactions — data from window.TC_DASHBOARD */
(function () {
  const data = window.TC_DASHBOARD || {};
  const monthsShort = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

  const clientSelect = document.getElementById("clientSelect");
  if (clientSelect) {
    clientSelect.addEventListener("change", () => {
      const v = clientSelect.value;
      const url = new URL(window.location.href);
      if (v) url.searchParams.set("client", v);
      else url.searchParams.delete("client");
      window.location.href = url.pathname + (url.searchParams.toString() ? "?" + url.searchParams.toString() : "");
    });
  }

  const monthSelect = document.getElementById("jobsMonth");
  const yearSelect = document.getElementById("jobsYear");
  if (monthSelect && yearSelect) {
    const now = new Date();
    const seriesYear = (data.series && data.series.year) || now.getFullYear();
    const seriesMonth = (data.series && data.series.month != null) ? data.series.month - 1 : now.getMonth();
    monthsShort.forEach((m, i) => {
      const opt = document.createElement("option");
      opt.value = String(i + 1);
      opt.textContent = m;
      if (i === seriesMonth) opt.selected = true;
      monthSelect.appendChild(opt);
    });
    [seriesYear - 1, seriesYear, seriesYear + 1].filter((y, i, a) => a.indexOf(y) === i).forEach((y) => {
      const opt = document.createElement("option");
      opt.value = String(y);
      opt.textContent = String(y);
      if (y === seriesYear) opt.selected = true;
      yearSelect.appendChild(opt);
    });

    function reloadSeries() {
      const url = new URL(window.location.href);
      url.searchParams.set("year", yearSelect.value);
      url.searchParams.set("month", monthSelect.value);
      window.location.href = url.pathname + "?" + url.searchParams.toString();
    }
    monthSelect.addEventListener("change", reloadSeries);
    yearSelect.addEventListener("change", reloadSeries);
  }

  let chartCoords = [];
  let chartDaily = [];
  let chartMonth = 1;
  const chartW = 400;
  const chartH = 180;

  function setTip(idx) {
    if (!chartCoords.length) return;
    const i = Math.max(0, Math.min(chartCoords.length - 1, idx));
    const [tx, ty] = chartCoords[i];
    const tipDot = document.getElementById("tipDot");
    const chartTip = document.getElementById("chartTip");
    const tipLine = document.getElementById("tipLine");
    if (tipDot) {
      tipDot.setAttribute("cx", tx);
      tipDot.setAttribute("cy", ty);
    }
    if (tipLine) {
      tipLine.setAttribute("x1", tx);
      tipLine.setAttribute("x2", tx);
      tipLine.setAttribute("y1", 0);
      tipLine.setAttribute("y2", chartH);
    }
    if (chartTip) {
      const m = monthsShort[(chartMonth || 1) - 1];
      const n = chartDaily[i] != null ? Number(chartDaily[i]) : 0;
      const val = n.toLocaleString();
      const unit = n === 1 ? "item scraped" : "items scraped";
      chartTip.replaceChildren(
        document.createTextNode((i + 1) + " " + m),
        document.createElement("br"),
        document.createTextNode(val + " " + unit)
      );
      chartTip.style.left = ((tx / chartW) * 100) + "%";
    }
  }

  function defaultTipIndex(daily) {
    let last = -1;
    for (let i = 0; i < daily.length; i++) {
      if ((daily[i] || 0) > 0) last = i;
    }
    if (last >= 0) return last;
    return Math.max(0, Math.floor((daily.length - 1) / 2));
  }

  function drawChart(series) {
    if (!series || !series.normalized || !series.normalized.length) return;
    const pts = series.normalized;
    chartDaily = series.daily || [];
    chartMonth = series.month || 1;
    const pad = 8;
    const step = pts.length > 1 ? (chartW - pad * 2) / (pts.length - 1) : 0;
    chartCoords = pts.map((p, i) => [pad + i * step, pad + p * (chartH - pad * 2)]);
    const line = chartCoords.map((c, i) => (i ? "L" : "M") + c[0].toFixed(1) + " " + c[1].toFixed(1)).join(" ");
    const area = line + " L" + chartCoords[chartCoords.length - 1][0].toFixed(1) + " " + chartH +
      " L" + chartCoords[0][0].toFixed(1) + " " + chartH + " Z";
    const linePath = document.getElementById("linePath");
    const areaPath = document.getElementById("areaPath");
    if (!linePath || !areaPath) return;
    linePath.setAttribute("d", line);
    areaPath.setAttribute("d", area);
    setTip(defaultTipIndex(chartDaily));
  }
  drawChart(data.series);

  const chartWrap = document.querySelector(".chart-wrap");
  if (chartWrap && chartCoords.length) {
    chartWrap.addEventListener("mousemove", (e) => {
      const svg = chartWrap.querySelector("svg");
      if (!svg || !chartCoords.length) return;
      const rect = svg.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * chartW;
      let best = 0;
      let bestDist = Infinity;
      chartCoords.forEach((c, i) => {
        const d = Math.abs(c[0] - x);
        if (d < bestDist) {
          bestDist = d;
          best = i;
        }
      });
      setTip(best);
    });
    chartWrap.addEventListener("mouseleave", () => {
      setTip(defaultTipIndex(chartDaily));
    });
  }

  const statusMap = {
    completed: { label: "Completed", cls: "ok" },
    scheduled: { label: "Scheduled", cls: "sched" },
    attention: { label: "Failed", cls: "fail" }
  };
  let activeFilter = "completed";
  const jobs = (data.job_center && data.job_center.jobs) || [];
  const emptyCopy = {
    completed: "No completed jobs today",
    scheduled: "No scrapers scheduled",
    attention: "Nothing needs attention",
  };
  const infoColLabels = {
    completed: "Items Processed",
    scheduled: "Next run",
    attention: "Info",
  };

  function renderJobs() {
    const body = document.getElementById("jobTableBody");
    const emptyEl = document.getElementById("jobCenterEmpty");
    const infoCol = document.getElementById("jobInfoCol");
    const stage = body && body.closest(".job-center-body");
    if (infoCol) infoCol.textContent = infoColLabels[activeFilter] || "Info";
    if (!body) return;
    const list = jobs.filter((j) => j.status === activeFilter);
    if (!list.length) {
      body.innerHTML = "";
      if (emptyEl) {
        emptyEl.textContent = emptyCopy[activeFilter] || "No jobs in this tab";
        emptyEl.hidden = false;
      }
      if (stage) stage.classList.add("is-empty");
      return;
    }
    if (emptyEl) emptyEl.hidden = true;
    if (stage) stage.classList.remove("is-empty");
    body.innerHTML = list.map((j) => {
      const s = statusMap[j.status] || { label: j.status, cls: "" };
      let info = '<span class="muted">' + (j.info || "—") + "</span>";
      return (
        "<tr>" +
          '<td class="name"><a class="link" href="/dashboard/scrapers/' + encodeURIComponent(j.spider_name) + '">' + j.name + "</a></td>" +
          '<td><span class="pill ' + s.cls + '">' + s.label + "</span></td>" +
          "<td>" + info + "</td>" +
          '<td class="time">' + (j.time || "—") + "</td>" +
        "</tr>"
      );
    }).join("");
  }

  const tabs = document.getElementById("jobTabs");
  if (tabs) {
    tabs.addEventListener("click", (e) => {
      const tab = e.target.closest(".tab");
      if (!tab) return;
      tabs.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      activeFilter = tab.dataset.filter;
      renderJobs();
    });
    renderJobs();
  }

  function renderTop(sort) {
    const listEl = document.getElementById("topList");
    if (!listEl) return;
    let topJobs = (data.top_jobs || []).slice();
    if (sort === "success") {
      topJobs.sort((a, b) => b.pct - a.pct || b.count - a.count);
    } else {
      topJobs.sort((a, b) => b.count - a.count || b.pct - a.pct);
    }
    if (!topJobs.length) {
      listEl.innerHTML = '<div class="muted">No jobs yet.</div>';
      return;
    }
    const maxCount = Math.max(...topJobs.map((j) => j.count), 1);
    const barColors = ["#e8926f", "#2f9e6b", "#3b82f6", "#d97706", "#8b5cf6"];
    listEl.innerHTML = topJobs.map((j, i) => {
      const w = Math.round((j.count / maxCount) * 100);
      const color = barColors[i % barColors.length];
      return (
        '<div class="top-row">' +
          '<div class="top-main">' +
            '<div class="top-name">' + j.name + "</div>" +
            '<div class="top-bar"><i style="width:' + w + "%;background:" + color + '"></i></div>' +
          "</div>" +
          '<div class="top-meta">' +
            '<em class="top-count">' + j.count + "</em>" +
            '<div class="top-pct">' + Number(j.pct).toFixed(1) + "%</div>" +
          "</div>" +
        "</div>"
      );
    }).join("");
  }
  const topSort = document.getElementById("topSort");
  if (topSort) {
    topSort.addEventListener("change", () => renderTop(topSort.value));
    renderTop(topSort.value);
  } else {
    renderTop("count");
  }

  const activity = data.activity || [];
  const activityList = document.getElementById("activityList");
  if (activityList) {
    activityList.innerHTML = activity.length
      ? activity.map((a) => (
          '<div class="activity-item">' +
            '<span class="dot ' + (a.cls || "") + '"></span>' +
            "<p>" + a.text + "</p>" +
            "<time>" + a.time + "</time>" +
          "</div>"
        )).join("")
      : '<div class="muted">No recent activity.</div>';
  }

  const quality = data.quality || {};
  const qualityDonut = document.getElementById("qualityDonut");
  if (qualityDonut && quality.donut_css) {
    qualityDonut.style.background = quality.donut_css;
  }
})();

/* Detail page: scraped volume chart + range tabs */
(function () {
  const el = document.getElementById("detail-data");
  if (!el) return;
  let payload = {};
  try {
    payload = JSON.parse(el.textContent || "{}");
  } catch (_) {
    return;
  }
  const ranges = (payload.volume && payload.volume.ranges) || {};
  const linePath = document.getElementById("detailLinePath");
  const areaPath = document.getElementById("detailAreaPath");
  const periodEl = document.getElementById("volPeriodTotal");
  const deltaEl = document.getElementById("volDelta");
  const tabs = document.getElementById("volumeTabs");
  if (!linePath || !areaPath || !tabs) return;

  function buildPaths(normalized) {
    const w = 400;
    const h = 140;
    const padY = 12;
    const n = normalized.length;
    if (!n) {
      linePath.setAttribute("d", "");
      areaPath.setAttribute("d", "");
      return;
    }
    const pts = normalized.map((v, i) => {
      const x = n === 1 ? w / 2 : (i / (n - 1)) * w;
      const y = h - padY - v * (h - padY * 2);
      return [x, y];
    });
    const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(2) + " " + p[1].toFixed(2)).join(" ");
    const area = line + " L" + pts[pts.length - 1][0].toFixed(2) + " " + h + " L" + pts[0][0].toFixed(2) + " " + h + " Z";
    linePath.setAttribute("d", line);
    areaPath.setAttribute("d", area);
  }

  function renderRange(key) {
    const series = ranges[key] || ranges["7d"] || {};
    buildPaths(series.normalized || []);
    if (periodEl) periodEl.textContent = series.period_total_fmt || "0";
    if (deltaEl) {
      const d = series.delta_pct;
      if (d == null) {
        deltaEl.textContent = "";
        deltaEl.className = "delta";
      } else {
        deltaEl.textContent = (d > 0 ? "↑ " : "↓ ") + Math.abs(d) + "%";
        deltaEl.className = "delta " + (d > 0 ? "up" : "down");
      }
    }
  }

  tabs.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-range]");
    if (!btn) return;
    tabs.querySelectorAll(".vol-tab").forEach((t) => t.classList.toggle("active", t === btn));
    renderRange(btn.dataset.range);
  });

  renderRange("7d");
})();
