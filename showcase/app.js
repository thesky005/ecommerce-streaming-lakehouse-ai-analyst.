(() => {
  "use strict";
  const O = DATA.orders, I = DATA.items, DX = DATA.dicts;
  const N = O.d.length, M = I.o.length;
  const BASE = Date.parse(DATA.base + "T00:00:00Z"), DAY = 864e5;

  // ------------------------------------------------------------------ palette
  const S = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];
  const SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
  const INK = "#0b0b0b", INK2 = "#52514e", MUTED = "#898781", GRID = "#ebeae4", AXIS = "#c3c2b7", PRIOR = "#b9b8b0";
  const COLOR = {
    ch: { web: S[0], mobile_app: S[1], marketplace: S[2] },
    src: { organic_search: S[0], paid_search: S[1], direct: S[2], social: S[3], email: S[4], affiliate: S[5] },
    car: { SwiftShip: S[0], ParcelPro: S[1], EconoPost: S[2] },
    cat: { Electronics: S[0], Apparel: S[1], "Home & Kitchen": S[2], Beauty: S[3], "Sports & Outdoors": S[4], Books: S[5] },
    reg: { West: S[0], Midwest: S[1], South: S[2], Northeast: S[3] },
  };
  const LABEL = {
    web: "Web", mobile_app: "Mobile app", marketplace: "Marketplace", organic_search: "Organic search",
    paid_search: "Paid search", direct: "Direct", social: "Social", email: "Email", affiliate: "Affiliate",
    buy_now_pay_later: "Buy now, pay later", apple_pay: "Apple Pay", paypal: "PayPal", card: "Card",
    bank_transfer: "Bank transfer", wrong_size: "Wrong size", changed_mind: "Changed mind",
    not_as_described: "Not as described", arrived_damaged: "Arrived damaged", defective: "Defective",
    delivery_overdue: "Delivery overdue", low_rating: "Low rating", refund_pending: "Refund pending",
  };
  const CAMPAIGN = {
    "CMP-SEARCH-ALWAYS-ON": "Search · always-on", "CMP-SOCIAL-PROSPECTING": "Social · prospecting",
    "CMP-SOCIAL-INFLUENCER": "Social · influencer burst", "CMP-EMAIL-WEEKEND-SALE": "Email · weekend sale",
    "CMP-EMAIL-NEWSLETTER": "Email · newsletter", "CMP-AFFILIATE-PARTNERS": "Affiliate partners",
  };
  const campaign = (id) => CAMPAIGN[id] || id;
  const nice = (v) => LABEL[v] || String(v).replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const esc = (v) => String(v ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // Business plan targets used for status pills and recommendations.
  const T = {
    growth: { value: 0.05, dir: "min", text: "+5% vs prior" },
    aov: { value: 150, dir: "min", text: "≥ $150" },
    margin: { value: 0.5, dir: "min", text: "≥ 50%" },
    onTime: { value: 0.9, dir: "min", text: "≥ 90%" },
    shipHours: { value: 24, dir: "max", text: "≤ 24 h" },
    p90Ship: { value: 48, dir: "max", text: "≤ 48 h" },
    returnRate: { value: 0.06, dir: "max", text: "≤ 6%" },
    rating: { value: 4.0, dir: "min", text: "≥ 4.0 ★" },
    payFail: { value: 0.03, dir: "max", text: "≤ 3%" },
    discount: { value: 0.05, dir: "max", text: "≤ 5%" },
    repeat: { value: 0.6, dir: "min", text: "≥ 60%" },
    lowRating: { value: 0.12, dir: "max", text: "≤ 12%" },
    refundRate: { value: 0.05, dir: "max", text: "≤ 5% of sales" },
  };
  const statusOf = (value, t) => {
    if (value == null || !isFinite(value)) return null;
    const ok = t.dir === "min" ? value >= t.value : value <= t.value;
    if (ok) return "on";
    return Math.abs(value - t.value) / Math.abs(t.value) <= 0.1 ? "watch" : "off";
  };
  const PILL = { on: "On track", watch: "Watch", off: "Off track" };
  const pill = (s) => (s ? `<span class="pill ${s}">${PILL[s]}</span>` : `<span class="pill info">No target</span>`);

  // ------------------------------------------------------------------ formats
  const money = (v) => {
    if (v == null || !isFinite(v)) return "–";
    const a = Math.abs(v), sign = v < 0 ? "-" : "";
    if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(a >= 1e8 ? 0 : 2)}M`;
    if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(a >= 1e5 ? 0 : 1)}K`;
    return `${sign}$${a.toFixed(a >= 100 ? 0 : 2)}`;
  };
  const pct = (v, d = 1) => (v == null || !isFinite(v) ? "–" : `${(v * 100).toFixed(d)}%`);
  const num = (v) => (v == null || !isFinite(v) ? "–" : Math.round(v).toLocaleString("en-US"));
  const hrs = (v) => (v == null || !isFinite(v) ? "–" : `${v.toFixed(1)} h`);
  const dayDate = (d) => new Date(BASE + d * DAY);
  const iso = (d) => dayDate(d).toISOString().slice(0, 10);
  const short = (d) => dayDate(d).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  const sum = (a) => a.reduce((x, y) => x + y, 0);
  const quantile = (arr, q) => {
    if (!arr.length) return null;
    const s = [...arr].sort((a, b) => a - b), i = (s.length - 1) * q, lo = Math.floor(i);
    return s[lo] + (s[Math.min(lo + 1, s.length - 1)] - s[lo]) * (i - lo);
  };
  const ratio = (a, b) => (b ? a / b : null);
  const inR = (v, s, e) => v !== null && v >= s && v <= e;

  // Returned line's category per order (for return analysis).
  const retCat = new Int16Array(N).fill(-1);
  for (let k = 0; k < M; k++) if (I.ret[k]) retCat[I.o[k]] = I.cat[k];
  const lostReason = DX.cr.includes("payment_failed") ? DX.cr.indexOf("payment_failed") : -99;

  // ------------------------------------------------------------------ metrics
  function compute(s, e) {
    const m = { orders: 0, active: 0, cancelled: 0, newCust: 0, repeat: 0, sales: 0, disc: 0, grossSales: 0, paidMerch: 0,
      ship: 0, cogs: 0, refunds: 0, pfailOrders: 0, lost: 0, lostValue: 0, shipHs: [], deliveries: 0, late: 0,
      daysDel: 0, returns: 0, ratingSum: 0, ratingN: 0, low: 0 };
    for (let i = 0; i < N; i++) {
      const d = O.d[i];
      if (d >= s && d <= e) {
        m.orders++;
        if (O.canc[i]) m.cancelled++;
        else { m.active++; m.sales += O.merch[i]; m.disc += O.disc[i]; O.new[i] ? m.newCust++ : m.repeat++; }
        if (O.paid[i]) {
          m.paidMerch += O.merch[i]; m.grossSales += O.merch[i] + O.disc[i]; m.ship += O.ship[i];
          if (!O.canc[i]) m.cogs += O.cost[i];
        }
        if (O.pfail[i] > 0) m.pfailOrders++;
        if (O.cr[i] === lostReason) { m.lost++; m.lostValue += O.merch[i]; }
        if (O.shipH[i] !== null) m.shipHs.push(O.shipH[i]);
      }
      if (inR(O.delD[i], s, e)) {
        m.deliveries++; if (O.late[i]) m.late++; m.daysDel += O.daysDel[i] || 0;
        if (O.rating[i] !== null) { m.ratingSum += O.rating[i]; m.ratingN++; if (O.rating[i] <= 2) m.low++; }
      }
      if (inR(O.retD[i], s, e)) m.returns++;
      if (inR(O.refD[i], s, e)) m.refunds += O.refund[i];
    }
    m.aov = ratio(m.sales, m.active);
    m.discountRate = ratio(m.disc, m.sales + m.disc);
    m.netRevenue = m.paidMerch + m.ship - m.refunds;
    m.grossProfit = m.netRevenue - m.cogs;
    m.margin = ratio(m.grossProfit, m.netRevenue);
    m.onTime = m.deliveries ? 1 - m.late / m.deliveries : null;
    m.shipH = m.shipHs.length ? sum(m.shipHs) / m.shipHs.length : null;
    m.p90 = quantile(m.shipHs, 0.9);
    m.avgDays = ratio(m.daysDel, m.deliveries);
    m.returnRate = ratio(m.returns, m.deliveries);
    m.rating = ratio(m.ratingSum, m.ratingN);
    m.lowShare = ratio(m.low, m.ratingN);
    m.payFail = ratio(m.pfailOrders, m.orders);
    m.repeatShare = ratio(m.repeat, m.active);
    m.refundRate = ratio(m.refunds, m.paidMerch);
    m.cancelRate = ratio(m.cancelled, m.orders);
    return m;
  }

  let state = { days: 7, view: "overview" };
  let cache = null;
  function context() {
    if (cache && cache.days === state.days) return cache;
    const e = DATA.asOf, s = e - state.days + 1, ps = s - state.days, pe = s - 1;
    const hasPrior = ps >= 0;
    const daily = [], dailyPrior = [];
    for (let d = s; d <= e; d++) daily.push(compute(d, d));
    for (let d = ps; d <= pe; d++) dailyPrior.push(compute(d, d));
    cache = { days: state.days, s, e, ps, pe, hasPrior, cur: compute(s, e), prev: hasPrior ? compute(ps, pe) : null,
      daily, dailyPrior };
    return cache;
  }

  // Group orders placed in [s, e] by a dictionary-encoded column.
  function byOrder(col, s, e, fn) {
    const out = new Map();
    for (let i = 0; i < N; i++) {
      if (O.d[i] < s || O.d[i] > e) continue;
      const k = O[col][i];
      if (k < 0) continue;
      if (!out.has(k)) out.set(k, fn.init());
      fn.add(out.get(k), i);
    }
    return out;
  }

  // ------------------------------------------------------------------ widgets
  function delta(cur, prev, good, mode = "rel") {
    if (prev == null || cur == null || !isFinite(prev) || !isFinite(cur) || (mode === "rel" && !prev))
      return `<span class="delta flat">no prior data</span>`;
    const change = mode === "rel" ? (cur - prev) / Math.abs(prev) : cur - prev;
    const flatBelow = { rel: 0.0005, pts: 0.0005, h: 0.05, abs: 0.005 }[mode] ?? 0.0005;
    const dir = Math.abs(change) < flatBelow ? "flat" : (change > 0) === (good === "up") ? "up" : "down";
    const arrow = change > 0 ? "▲" : change < 0 ? "▼" : "■";
    const text = mode === "rel" ? `${(change * 100).toFixed(1)}%` : mode === "pts" ? `${(change * 100).toFixed(1)} pts`
      : mode === "h" ? `${change.toFixed(1)} h` : change.toFixed(2);
    return `<span class="delta ${dir}">${arrow} ${text.replace("-", "")}</span>`;
  }

  function spark(values, color = S[0]) {
    const pts = values.map((v, i) => [i, v]).filter((p) => p[1] != null && isFinite(p[1]));
    if (pts.length < 2) return `<svg class="spark"></svg>`;
    const ys = pts.map((p) => p[1]), lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
    const w = 200, h = 30, n = values.length - 1 || 1;
    const path = pts.map((p, j) => `${j ? "L" : "M"}${(p[0] / n * w).toFixed(1)},${(h - 3 - (p[1] - lo) / span * (h - 6)).toFixed(1)}`).join("");
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
      <path d="${path}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`;
  }

  function kpi({ label, value, fmt, prev, good = "up", mode = "rel", target, series, note }) {
    const st = target ? statusOf(value, target) : null;
    return `<div class="kpi">
      <div class="kpi-top"><span class="kpi-label">${label}</span>${target ? pill(st) : ""}</div>
      <div class="kpi-value">${fmt(value)}</div>
      <div class="kpi-meta">${prev !== undefined ? delta(value, prev, good, mode) : `<span>${note || ""}</span>`}
        <span>${target ? "Target " + target.text : note && prev !== undefined ? note : ""}</span></div>
      ${series ? spark(series, st === "off" ? "#d03b3b" : S[0]) : ""}
    </div>`;
  }

  function panel(title, sub, body, extra = "") {
    return `<div class="panel"><div class="panel-head"><div><h2>${title}</h2>${sub ? `<p>${sub}</p>` : ""}</div>${extra}</div>${body}</div>`;
  }

  function table(headers, rows) {
    const head = headers.map((h) => `<th class="${h.n ? "n" : ""}">${h.label}</th>`).join("");
    const body = rows.length ? rows.map((r) => `<tr>${r.map((c, i) => `<td class="${headers[i].n ? "n" : ""}">${c}</td>`).join("")}</tr>`).join("")
      : `<tr><td colspan="${headers.length}" class="muted">No data in this period</td></tr>`;
    return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }
  const cellBar = (value, max, text) =>
    `<div class="cellbar">${text}<i style="width:${Math.max(2, (value / (max || 1)) * 70).toFixed(0)}px"></i></div>`;
  const change = (cur, prev) => (prev ? delta(cur, prev, "up") : `<span class="delta flat">${cur ? "new" : "–"}</span>`);

  // ------------------------------------------------------------------ charts
  const charts = [];
  function plot(id, data, layout = {}) {
    const el = document.getElementById(id);
    if (!el) return;
    const base = {
      height: layout.height || 290, margin: { l: 8, r: 12, t: 6, b: 8 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: 'system-ui, -apple-system, "Segoe UI", sans-serif', color: INK2, size: 12 },
      showlegend: true, legend: { orientation: "h", yanchor: "top", y: -0.14, x: 0, font: { size: 12 } },
      hoverlabel: { bgcolor: "#fff", bordercolor: GRID, font: { color: INK } }, bargap: 0.3,
      xaxis: { showgrid: false, linecolor: AXIS, tickfont: { color: MUTED }, automargin: true, fixedrange: true },
      yaxis: { gridcolor: GRID, zeroline: false, linecolor: AXIS, tickfont: { color: MUTED }, automargin: true, fixedrange: true },
    };
    const merged = { ...base, ...layout, xaxis: { ...base.xaxis, ...(layout.xaxis || {}) }, yaxis: { ...base.yaxis, ...(layout.yaxis || {}) } };
    Plotly.react(el, data, merged, { displayModeBar: false, responsive: true });
    charts.push(el);
  }
  const hbarLayout = (max) => ({ showlegend: false, xaxis: { visible: false, range: [0, max * 1.25 || 1] }, yaxis: { autorange: "reversed", gridcolor: "rgba(0,0,0,0)" } });

  // ------------------------------------------------------------------ insights
  const RETURN_ACTION = {
    wrong_size: "Add size guidance and fit recommendations to these product pages",
    defective: "Open a quality review with the suppliers of the most-returned SKUs",
    arrived_damaged: "Review packaging and carrier handling for these items",
    not_as_described: "Correct product descriptions and photos on the most-returned SKUs",
    changed_mind: "Test a shorter free-return window or a restocking fee",
  };

  function insights(ctx) {
    const { s, e, cur, prev } = ctx, out = [];
    const sev = (st) => (st === "off" ? "high" : "medium");

    // Carriers
    const car = new Map();
    for (let i = 0; i < N; i++) if (inR(O.delD[i], s, e) && O.car[i] >= 0) {
      const c = car.get(O.car[i]) || { n: 0, late: 0 }; c.n++; if (O.late[i]) c.late++; car.set(O.car[i], c);
    }
    const carriers = [...car].filter(([, c]) => c.n >= 15).map(([k, c]) => ({ name: DX.car[k], ...c, rate: 1 - c.late / c.n }))
      .sort((a, b) => a.rate - b.rate);
    if (carriers.length > 1 && statusOf(carriers[0].rate, T.onTime) !== "on") {
      const worst = carriers[0], best = carriers[carriers.length - 1];
      let lr = [0, 0], or = [0, 0];
      for (let i = 0; i < N; i++) if (inR(O.delD[i], s, e) && O.rating[i] !== null) {
        const t = O.late[i] ? lr : or; t[0] += O.rating[i]; t[1]++;
      }
      const ratingNote = lr[1] && or[1] ? ` Late orders are rated ${(lr[0] / lr[1]).toFixed(1)}★ vs ${(or[0] / or[1]).toFixed(1)}★ when on time.` : "";
      out.push({ sev: sev(statusOf(worst.rate, T.onTime)), dept: "Operations",
        title: `${worst.name} is missing the delivery SLA`,
        evidence: `${pct(worst.rate)} on time (target ${T.onTime.text}), ${num(worst.late)} late deliveries this period. ${best.name} delivered ${pct(best.rate)} on time.${ratingNote}`,
        action: `Shift time-sensitive volume from ${worst.name} to ${best.name}, or renegotiate ${worst.name}'s SLA.` });
    }

    // Warehouses
    const wh = byOrder("wh", s, e, { init: () => [], add: (a, i) => O.shipH[i] !== null && a.push(O.shipH[i]) });
    const sites = [...wh].filter(([, a]) => a.length >= 15).map(([k, a]) => ({ name: DX.wh[k], h: sum(a) / a.length }))
      .sort((a, b) => b.h - a.h);
    if (sites.length > 1 && sites[0].h > T.shipHours.value) {
      const worst = sites[0], best = sites[sites.length - 1];
      out.push({ sev: worst.h > T.shipHours.value * 1.25 ? "high" : "medium", dept: "Operations",
        title: `${worst.name} is the slowest warehouse to ship`,
        evidence: `${hrs(worst.h)} from order to shipment on average (target ${T.shipHours.text}); ${best.name} averages ${hrs(best.h)}.`,
        action: `Add a pick-and-pack shift at ${worst.name} or route overflow orders to ${best.name}.` });
    }

    // Payments
    const pay = byOrder("pay", s, e, { init: () => ({ n: 0, f: 0, lost: 0, value: 0 }),
      add: (a, i) => { a.n++; if (O.pfail[i]) a.f++; if (O.cr[i] === lostReason) { a.lost++; a.value += O.merch[i]; } } });
    const methods = [...pay].filter(([, a]) => a.n >= 20).map(([k, a]) => ({ name: nice(DX.pay[k]), ...a, rate: a.f / a.n }))
      .sort((a, b) => b.rate - a.rate);
    if (methods.length && statusOf(methods[0].rate, T.payFail) !== "on") {
      const m = methods[0];
      out.push({ sev: sev(statusOf(m.rate, T.payFail)), dept: "Finance",
        title: `${m.name} payments are failing too often`,
        evidence: `${pct(m.rate)} of ${m.name} orders hit a payment failure (target ${T.payFail.text})` +
          (m.lost ? `; ${num(m.lost)} orders worth ${money(m.value)} were cancelled as a result.` : "; so far every failed order was recovered on retry."),
        action: `Review the ${m.name} provider's decline reasons and retry automatically before cancelling the order.` });
    }

    // Returns by category
    const delivered = new Map(), returned = new Map(), reasons = new Map();
    for (let k = 0; k < M; k++) { const i = I.o[k]; if (inR(O.delD[i], s, e)) delivered.set(I.cat[k], (delivered.get(I.cat[k]) || 0) + 1); }
    for (let i = 0; i < N; i++) if (inR(O.retD[i], s, e) && retCat[i] >= 0) {
      returned.set(retCat[i], (returned.get(retCat[i]) || 0) + 1);
      const key = retCat[i] + "|" + O.rr[i]; reasons.set(key, (reasons.get(key) || 0) + 1);
    }
    const cats = [...returned].filter(([k]) => (delivered.get(k) || 0) >= 30)
      .map(([k, r]) => ({ k, name: DX.cat[k], r, rate: r / delivered.get(k) })).sort((a, b) => b.rate - a.rate);
    if (cats.length && cats[0].rate > T.returnRate.value) {
      const c = cats[0];
      const top = [...reasons].filter(([key]) => key.startsWith(c.k + "|")).sort((a, b) => b[1] - a[1])[0];
      const reason = top ? DX.rr[+top[0].split("|")[1]] : null;
      out.push({ sev: c.rate > T.returnRate.value * 1.5 ? "high" : "medium", dept: "Customer service",
        title: `${c.name} has the highest return rate`,
        evidence: `${pct(c.rate)} of delivered ${c.name} lines were returned (target ${T.returnRate.text})${reason ? `; the top reason is “${nice(reason).toLowerCase()}” (${top[1]} of ${c.r})` : ""}.`,
        action: reason ? `${RETURN_ACTION[reason] || "Review the most-returned SKUs"}.` : "Review the most-returned SKUs." });
    }

    // Revenue trend and driver
    if (prev && prev.sales) {
      const g = (cur.sales - prev.sales) / prev.sales;
      const chNow = byOrder("ch", s, e, { init: () => [0], add: (a, i) => { if (!O.canc[i]) a[0] += O.merch[i]; } });
      const chPrev = byOrder("ch", ctx.ps, ctx.pe, { init: () => [0], add: (a, i) => { if (!O.canc[i]) a[0] += O.merch[i]; } });
      const moves = DX.ch.map((name, k) => ({ name: nice(name), diff: (chNow.get(k)?.[0] || 0) - (chPrev.get(k)?.[0] || 0) }))
        .sort((a, b) => (g >= 0 ? b.diff - a.diff : a.diff - b.diff));
      const driver = moves[0];
      if (g < 0) out.push({ sev: g < -0.05 ? "high" : "medium", dept: "Sales", title: `Net sales fell ${pct(-g)} vs the prior period`,
        evidence: `${money(cur.sales)} vs ${money(prev.sales)}. ${driver.name} accounts for ${money(driver.diff)} of the change.`,
        action: `Check the ${driver.name} funnel: traffic, conversion, stock-outs and pricing changes.` });
      else if (g >= T.growth.value) out.push({ sev: "positive", dept: "Sales", title: `Net sales grew ${pct(g)} vs the prior period`,
        evidence: `${money(cur.sales)} vs ${money(prev.sales)}, ahead of the ${T.growth.text} plan. ${driver.name} added ${money(driver.diff)}.`,
        action: `Keep investment behind ${driver.name}; review stock cover for its top sellers.` });
      else out.push({ sev: "medium", dept: "Sales", title: `Net sales growth of ${pct(g)} is below plan`,
        evidence: `${money(cur.sales)} vs ${money(prev.sales)}; the plan is ${T.growth.text}. Biggest mover: ${driver.name} (${money(driver.diff)}).`,
        action: `Use a targeted campaign on ${driver.name} to close the gap to plan.` });
    }

    // Discount efficiency
    const cmp = byOrder("cmp", s, e, { init: () => ({ r: 0, d: 0, n: 0 }), add: (a, i) => { if (!O.canc[i]) { a.r += O.merch[i]; a.d += O.disc[i]; a.n++; } } });
    // Only promotions (discount of at least 1% of revenue) are ranked on return per discount dollar.
    const camps = [...cmp].filter(([, a]) => a.d >= a.r * 0.01 && a.n >= 10).map(([k, a]) => ({ name: campaign(DX.cmp[k]), ...a, roi: a.r / a.d }))
      .sort((a, b) => a.roi - b.roi);
    if (camps.length > 1) {
      const worst = camps[0], best = camps[camps.length - 1];
      out.push({ sev: "medium", dept: "Marketing", title: `${worst.name} has the weakest return on discount`,
        evidence: `${money(worst.d)} of discounts for ${money(worst.r)} revenue (${worst.roi.toFixed(1)}× return); ${best.name} returns ${best.roi.toFixed(1)}×.`,
        action: `Test a smaller discount on ${worst.name} or move promotional budget to ${best.name}.` });
    }

    // Ratings
    if (cur.rating !== null && statusOf(cur.rating, T.rating) !== "on") {
      const high = DATA.queue.filter((q) => q.priority === "high").length;
      out.push({ sev: sev(statusOf(cur.rating, T.rating)), dept: "Customer service",
        title: `Average rating ${cur.rating.toFixed(2)}★ is below target`,
        evidence: `${pct(cur.lowShare)} of reviews are 1–2★ (target ${T.lowRating.text}). Late delivery is the strongest driver of low ratings.`,
        action: `Work the ${high} high-priority cases in the attention queue and notify customers proactively when a delivery is late.` });
    }

    // New customers
    if (prev && prev.newCust) {
      const g = (cur.newCust - prev.newCust) / prev.newCust;
      if (g <= -0.1) out.push({ sev: "medium", dept: "Marketing", title: `New-customer acquisition is down ${pct(-g)}`,
        evidence: `${num(cur.newCust)} first-time customers vs ${num(prev.newCust)} in the prior period.`,
        action: "Review paid-search and social budgets and creative fatigue on prospecting campaigns." });
      else if (g >= 0.1) out.push({ sev: "positive", dept: "Marketing", title: `New-customer acquisition is up ${pct(g)}`,
        evidence: `${num(cur.newCust)} first-time customers vs ${num(prev.newCust)} in the prior period.`,
        action: "Follow up with an onboarding series to convert them into repeat buyers." });
    }
    const order = { high: 0, medium: 1, positive: 2 };
    return out.sort((a, b) => order[a.sev] - order[b.sev]);
  }

  function decisions(list, limit) {
    if (!list.length) return `<div class="empty">Nothing needs attention in this period. All tracked metrics are on target.</div>`;
    const label = { high: "High priority", medium: "Review", positive: "Opportunity" };
    return `<div class="decisions">${list.slice(0, limit).map((x) => `<div class="decision ${x.sev}"><div class="bar"></div>
      <div><h3>${esc(x.title)}</h3><div class="evidence">${esc(x.evidence)}</div><div class="action"><b>Recommended:</b> ${esc(x.action)}</div></div>
      <div style="display:flex;flex-direction:column;gap:6px;align-items:flex-end"><span class="pill ${x.sev === "high" ? "off" : x.sev === "medium" ? "watch" : "on"}">${label[x.sev]}</span><span class="owner">${x.dept}</span></div>
    </div>`).join("")}</div>`;
  }
  const deptActions = (ctx, dept) => decisionsPanel(ctx, dept);
  const series = (ctx, key) => ctx.daily.map((m) => m[key]);

  // ------------------------------------------------------------------ views
  const VIEWS = {
    overview: { title: "Executive overview", render(ctx) {
      const { cur: c, prev: p } = ctx;
      const growth = p && p.netRevenue ? (c.netRevenue - p.netRevenue) / p.netRevenue : null;
      const kpis = [
        kpi({ label: "Net revenue", value: c.netRevenue, fmt: money, prev: p?.netRevenue, series: series(ctx, "netRevenue") }),
        kpi({ label: "Orders", value: c.orders, fmt: num, prev: p?.orders, series: series(ctx, "orders") }),
        kpi({ label: "Average order value", value: c.aov, fmt: money, prev: p?.aov, target: T.aov, series: series(ctx, "aov") }),
        kpi({ label: "Gross margin", value: c.margin, fmt: pct, prev: p?.margin, mode: "pts", target: T.margin, series: series(ctx, "margin") }),
        kpi({ label: "On-time delivery", value: c.onTime, fmt: pct, prev: p?.onTime, mode: "pts", target: T.onTime, series: series(ctx, "onTime") }),
        kpi({ label: "Return rate", value: c.returnRate, fmt: pct, prev: p?.returnRate, good: "down", mode: "pts", target: T.returnRate, series: series(ctx, "returnRate") }),
        kpi({ label: "Average rating", value: c.rating, fmt: (v) => (v == null ? "–" : v.toFixed(2) + " ★"), prev: p?.rating, mode: "abs", target: T.rating, series: series(ctx, "rating") }),
        kpi({ label: "Payment failure rate", value: c.payFail, fmt: pct, prev: p?.payFail, good: "down", mode: "pts", target: T.payFail, series: series(ctx, "payFail") }),
      ].join("");
      const rows = [
        ["Sales", "Net sales growth", pct(growth), T.growth.text, pill(growth == null ? null : statusOf(growth, T.growth))],
        ["Marketing", "Repeat-order share", pct(c.repeatShare), T.repeat.text, pill(statusOf(c.repeatShare, T.repeat))],
        ["Operations", "On-time delivery", pct(c.onTime), T.onTime.text, pill(statusOf(c.onTime, T.onTime))],
        ["Operations", "Average hours to ship", hrs(c.shipH), T.shipHours.text, pill(statusOf(c.shipH, T.shipHours))],
        ["Finance", "Gross margin", pct(c.margin), T.margin.text, pill(statusOf(c.margin, T.margin))],
        ["Finance", "Payment failure rate", pct(c.payFail), T.payFail.text, pill(statusOf(c.payFail, T.payFail))],
        ["Customer service", "Return rate", pct(c.returnRate), T.returnRate.text, pill(statusOf(c.returnRate, T.returnRate))],
        ["Customer service", "Average rating", c.rating == null ? "–" : c.rating.toFixed(2) + " ★", T.rating.text, pill(statusOf(c.rating, T.rating))],
      ];
      return `<div class="kpis k4">${kpis}</div>
        ${decisionsPanel(ctx, null)}
        <div class="grid cols-3-2">
          ${panel("Net revenue", `Daily net revenue this period${ctx.hasPrior ? " against the prior period" : ""}.`, `<div class="chart" id="c-rev"></div>`)}
          ${panel("Department scorecard", "Each department's headline metric against plan.",
            table([{ label: "Metric" }, { label: "Value", n: 1 }, { label: "Target", n: 1 }, { label: "Status" }],
              rows.map(([dept, metric, ...rest]) => [`${metric}<div class="muted" style="font-size:12px">${dept}</div>`, ...rest])))}
        </div>`;
    }, charts(ctx) {
      const x = ctx.daily.map((_, i) => iso(ctx.s + i));
      const traces = [{ type: "scatter", mode: "lines", name: "This period", x, y: series(ctx, "netRevenue"), line: { color: S[0], width: 2.4 },
        fill: "tozeroy", fillcolor: "rgba(42,120,214,0.07)", hovertemplate: "%{x|%a %d %b}: $%{y:,.0f}<extra>This period</extra>" }];
      if (ctx.hasPrior) traces.push({ type: "scatter", mode: "lines", name: "Prior period", x, y: ctx.dailyPrior.map((m) => m.netRevenue),
        line: { color: PRIOR, width: 2, dash: "dot" }, customdata: ctx.dailyPrior.map((_, i) => short(ctx.ps + i)),
        hovertemplate: "%{customdata}: $%{y:,.0f}<extra>Prior period</extra>" });
      plot("c-rev", traces, { yaxis: { tickprefix: "$", rangemode: "tozero" }, hovermode: "x unified", height: 440 });
    } },

    sales: { title: "Sales", render(ctx) {
      const { cur: c, prev: p, s, e, ps, pe } = ctx;
      const units = (a, b) => { let u = 0; for (let k = 0; k < M; k++) { const i = I.o[k]; if (O.d[i] >= a && O.d[i] <= b && !O.canc[i]) u += I.qty[k]; } return u; };
      const catAgg = (a, b) => { const m = new Map(); for (let k = 0; k < M; k++) { const i = I.o[k]; if (O.d[i] < a || O.d[i] > b || O.canc[i]) continue;
        const r = m.get(I.cat[k]) || { net: 0, gp: 0 }; r.net += I.net[k]; r.gp += I.gp[k]; m.set(I.cat[k], r); } return m; };
      const nowC = catAgg(s, e), prevC = ctx.hasPrior ? catAgg(ps, pe) : new Map();
      const totalNet = sum([...nowC.values()].map((r) => r.net));
      const catRows = [...nowC].sort((a, b) => b[1].net - a[1].net).map(([k, r]) => [
        `<span style="color:${COLOR.cat[DX.cat[k]]}">●</span> ${DX.cat[k]}`, cellBar(r.net, totalNet / 2, money(r.net)), pct(r.net / totalNet),
        ctx.hasPrior ? change(r.net, prevC.get(k)?.net) : "–", pct(r.gp / r.net)]);
      const skuAgg = (a, b) => { const m = new Map(); for (let k = 0; k < M; k++) { const i = I.o[k]; if (O.d[i] < a || O.d[i] > b || O.canc[i]) continue;
        const r = m.get(I.sku[k]) || { net: 0, gp: 0, qty: 0, cat: I.cat[k] }; r.net += I.net[k]; r.gp += I.gp[k]; r.qty += I.qty[k]; m.set(I.sku[k], r); } return m; };
      const nowS = skuAgg(s, e), prevS = ctx.hasPrior ? skuAgg(ps, pe) : new Map();
      const top = [...nowS].sort((a, b) => b[1].net - a[1].net).slice(0, 10);
      const topMax = top.length ? top[0][1].net : 1;
      const prodRows = top.map(([k, r]) => [`${esc(DX.skuName[k])}<div class="muted" style="font-size:12px">${DX.cat[r.cat]}</div>`, num(r.qty), cellBar(r.net, topMax, money(r.net)), pct(r.gp / r.net),
        ctx.hasPrior ? change(r.net, prevS.get(k)?.net) : "–"]);
      const u = units(s, e);
      return `<div class="kpis">
          ${kpi({ label: "Net sales", value: c.sales, fmt: money, prev: p?.sales, series: series(ctx, "sales") })}
          ${kpi({ label: "Orders", value: c.active, fmt: num, prev: p?.active, series: series(ctx, "active") })}
          ${kpi({ label: "Units sold", value: u, fmt: num, prev: ctx.hasPrior ? units(ps, pe) : undefined, note: "" })}
          ${kpi({ label: "Average order value", value: c.aov, fmt: money, prev: p?.aov, target: T.aov, series: series(ctx, "aov") })}
          ${kpi({ label: "Discount rate", value: c.discountRate, fmt: pct, prev: p?.discountRate, good: "down", mode: "pts", target: T.discount, series: series(ctx, "discountRate") })}
        </div>
        ${deptActions(ctx, "Sales")}
        <div class="grid cols-3-2">
          ${panel("Net sales by channel", "Daily, cancelled orders excluded.", `<div class="chart" id="c-sales-ch"></div>`)}
          ${panel("Sales by region", "Share of net sales by shipping region.", `<div class="chart" id="c-sales-reg"></div>`)}
        </div>
        <div class="grid cols-2-3">
          ${panel("Category performance", "Net sales, mix and margin by category.",
            table([{ label: "Category" }, { label: "Net sales", n: 1 }, { label: "Mix", n: 1 }, { label: "vs prior", n: 1 }, { label: "Margin", n: 1 }], catRows))}
          ${panel("Top products", "The ten best-selling products this period.",
            table([{ label: "Product" }, { label: "Units", n: 1 }, { label: "Net sales", n: 1 }, { label: "Margin", n: 1 }, { label: "vs prior", n: 1 }], prodRows))}
        </div>`;
    }, charts(ctx) {
      const traces = DX.ch.map((name, k) => {
        const y = []; for (let d = ctx.s; d <= ctx.e; d++) y.push(0);
        for (let i = 0; i < N; i++) if (O.ch[i] === k && !O.canc[i] && O.d[i] >= ctx.s && O.d[i] <= ctx.e) y[O.d[i] - ctx.s] += O.merch[i];
        return { type: "bar", name: nice(name), x: y.map((_, i) => iso(ctx.s + i)), y, marker: { color: COLOR.ch[name] },
          hovertemplate: `${nice(name)}: $%{y:,.0f}<extra></extra>` };
      });
      plot("c-sales-ch", traces, { barmode: "stack", hovermode: "x unified", yaxis: { tickprefix: "$" }, bargap: 0.18 });
      const reg = byOrder("reg", ctx.s, ctx.e, { init: () => [0], add: (a, i) => { if (!O.canc[i]) a[0] += O.merch[i]; } });
      const rows = [...reg].map(([k, a]) => ({ name: DX.reg[k], v: a[0] })).sort((a, b) => b.v - a.v);
      const total = sum(rows.map((r) => r.v));
      plot("c-sales-reg", [{ type: "bar", orientation: "h", y: rows.map((r) => r.name), x: rows.map((r) => r.v),
        marker: { color: rows.map((r) => COLOR.reg[r.name]) }, text: rows.map((r) => `${money(r.v)} · ${pct(r.v / total, 0)}`),
        textposition: "outside", cliponaxis: false, hovertemplate: "%{y}: $%{x:,.0f}<extra></extra>" }], hbarLayout(Math.max(...rows.map((r) => r.v), 1)));
    } },

    marketing: { title: "Marketing", render(ctx) {
      const { cur: c, prev: p, s, e, ps, pe } = ctx;
      const srcAgg = (a, b) => byOrder("src", a, b, { init: () => ({ n: 0, r: 0, nc: 0, d: 0 }),
        add: (x, i) => { if (O.canc[i]) return; x.n++; x.r += O.merch[i]; x.nc += O.new[i]; x.d += O.disc[i]; } });
      const now = srcAgg(s, e), before = ctx.hasPrior ? srcAgg(ps, pe) : new Map();
      const maxR = Math.max(...[...now.values()].map((x) => x.r), 1);
      const srcRows = [...now].sort((a, b) => b[1].r - a[1].r).map(([k, x]) => [
        `<span style="color:${COLOR.src[DX.src[k]]}">●</span> ${nice(DX.src[k])}`, num(x.n), cellBar(x.r, maxR, money(x.r)), num(x.nc),
        money(x.r / x.n), ctx.hasPrior ? change(x.nc, before.get(k)?.nc) : "–"]);
      const cmp = byOrder("cmp", s, e, { init: () => ({ n: 0, r: 0, d: 0, nc: 0 }), add: (x, i) => { if (O.canc[i]) return; x.n++; x.r += O.merch[i]; x.d += O.disc[i]; x.nc += O.new[i]; } });
      const camps = [...cmp].map(([k, x]) => ({ name: campaign(DX.cmp[k]), ...x, roi: x.d ? x.r / x.d : null,
        promo: x.d >= x.r * 0.01 })).sort((a, b) => b.r - a.r);
      const rois = camps.filter((x) => x.promo && x.n >= 10).map((x) => x.roi);
      const campRows = camps.map((x) => [x.name, num(x.n), money(x.r), money(x.d), num(x.nc),
        x.roi === null ? `<span class="muted">no discount</span>` : `${x.roi.toFixed(1)}×`,
        !x.promo ? `<span class="muted">always-on</span>` : rois.length < 2 ? "" : x.roi === Math.min(...rois) ? `<span class="pill off">Weakest</span>` : x.roi === Math.max(...rois) ? `<span class="pill on">Best</span>` : ""]);
      const PLAY = { Champions: "Early access and referral rewards", Loyal: "Tier-upgrade offers and bundles",
        "New & Promising": "Onboarding series with a second-order incentive", "Needs Attention": "Personalised recommendations",
        "At Risk": "Win-back offer within 7 days", Hibernating: "Low-cost reactivation, or suppress from paid media" };
      const segOrder = ["Champions", "Loyal", "New & Promising", "Needs Attention", "At Risk", "Hibernating"];
      const segs = segOrder.map((n) => DATA.segments.find((x) => x.segment === n)).filter(Boolean);
      const segRows = segs.map((x) => [`<b>${x.segment}</b>`, num(x.customers), money(x.revenue), `${x.recency.toFixed(0)} days`, x.frequency.toFixed(1), PLAY[x.segment]]);
      const campaignRevenue = sum(camps.map((x) => x.r));
      return `<div class="kpis">
          ${kpi({ label: "New customers", value: c.newCust, fmt: num, prev: p?.newCust, series: series(ctx, "newCust") })}
          ${kpi({ label: "Repeat-order share", value: c.repeatShare, fmt: pct, prev: p?.repeatShare, mode: "pts", target: T.repeat, series: series(ctx, "repeatShare") })}
          ${kpi({ label: "Campaign-driven revenue", value: ratio(campaignRevenue, c.sales), fmt: pct, note: `${money(campaignRevenue)} of net sales` })}
          ${kpi({ label: "Discount cost", value: c.disc, fmt: money, prev: p?.disc, good: "down", series: series(ctx, "disc") })}
          ${kpi({ label: "Revenue per $1 of discount", value: ratio(c.sales, c.disc), fmt: (v) => (v == null ? "–" : `$${v.toFixed(0)}`), prev: p ? ratio(p.sales, p.disc) : undefined })}
        </div>
        ${deptActions(ctx, "Marketing")}
        ${panel("Acquisition by traffic source", "Orders, revenue and first-time customers by where shoppers came from.",
          table([{ label: "Source" }, { label: "Orders", n: 1 }, { label: "Revenue", n: 1 }, { label: "New customers", n: 1 }, { label: "Avg order", n: 1 }, { label: "New vs prior", n: 1 }], srcRows))}
        <div class="grid cols-3-2">
          ${panel("Campaign efficiency", "Revenue returned for every dollar of discount. Promotions are ranked; always-on campaigns are shown for reference.",
            table([{ label: "Campaign" }, { label: "Orders", n: 1 }, { label: "Revenue", n: 1 }, { label: "Discount", n: 1 }, { label: "New", n: 1 }, { label: "Return", n: 1 }, { label: "" }], campRows))}
          ${panel("Weekly cohort retention", "Share of each week's new customers who ordered again (all data).", `<div class="chart" id="c-cohort"></div>`)}
        </div>
        ${panel("Customer segments (RFM)", "Recency, frequency and monetary scoring across the customer base, with the recommended play for each segment.",
          table([{ label: "Segment" }, { label: "Customers", n: 1 }, { label: "Revenue", n: 1 }, { label: "Avg recency", n: 1 }, { label: "Avg orders", n: 1 }, { label: "Recommended play" }], segRows))}`;
    }, charts() {
      const rows = DATA.cohorts.rows;
      plot("c-cohort", [{ type: "heatmap", z: rows.map((r) => r.values), x: DATA.cohorts.weeks.map((w) => `Week ${w}`), y: rows.map((r) => r.week),
        zmin: 0, zmax: 100, xgap: 2, ygap: 2, showscale: false, colorscale: SEQ.map((c, i) => [i / (SEQ.length - 1), c]),
        text: rows.map((r) => r.values.map((v) => (v == null ? "" : `${v.toFixed(0)}%`))), texttemplate: "%{text}",
        customdata: rows.map((r) => r.values.map(() => r.size)),
        hovertemplate: "Cohort %{y} · %{x}<br>%{z:.1f}% of %{customdata} customers<extra></extra>" }],
      { showlegend: false, yaxis: { autorange: "reversed", gridcolor: "rgba(0,0,0,0)" }, height: 300 });
    } },

    operations: { title: "Operations", render(ctx) {
      const { cur: c, prev: p, s, e } = ctx;
      const open = sum(DATA.backlog.map((b) => b.open_orders)), overdue = sum(DATA.backlog.map((b) => b.overdue_orders));
      const car = new Map();
      for (let i = 0; i < N; i++) if (inR(O.delD[i], s, e) && O.car[i] >= 0) {
        const x = car.get(O.car[i]) || { n: 0, late: 0, days: 0, rs: 0, rn: 0 };
        x.n++; x.late += O.late[i] || 0; x.days += O.daysDel[i] || 0; if (O.rating[i] !== null) { x.rs += O.rating[i]; x.rn++; } car.set(O.car[i], x);
      }
      const carRows = [...car].sort((a, b) => b[1].n - a[1].n).map(([k, x]) => { const r = 1 - x.late / x.n; return [
        `<span style="color:${COLOR.car[DX.car[k]]}">●</span> ${DX.car[k]}`, num(x.n), pct(r), `${(x.days / x.n).toFixed(1)} d`, num(x.late),
        x.rn ? (x.rs / x.rn).toFixed(2) + " ★" : "–", pill(statusOf(r, T.onTime))]; });
      const wh = byOrder("wh", s, e, { init: () => ({ n: 0, h: [] }), add: (x, i) => { x.n++; if (O.shipH[i] !== null) x.h.push(O.shipH[i]); } });
      const whDel = new Map();
      for (let i = 0; i < N; i++) if (inR(O.delD[i], s, e)) { const x = whDel.get(O.wh[i]) || [0, 0]; x[0]++; x[1] += O.late[i] || 0; whDel.set(O.wh[i], x); }
      const whRows = [...wh].sort((a, b) => b[1].n - a[1].n).map(([k, x]) => { const avg = x.h.length ? sum(x.h) / x.h.length : null; const d = whDel.get(k) || [0, 0];
        return [DX.wh[k], num(x.n), hrs(avg), hrs(quantile(x.h, 0.9)), d[0] ? pct(1 - d[1] / d[0]) : "–", pill(statusOf(avg, T.shipHours))]; });
      const backlog = new Map();
      DATA.backlog.forEach((b) => { const x = backlog.get(b.warehouse_id) || { open: 0, overdue: 0, oldest: 0, value: 0 };
        x.open += b.open_orders; x.overdue += b.overdue_orders; x.oldest = Math.max(x.oldest, b.oldest_order_hours); x.value += b.open_value; backlog.set(b.warehouse_id, x); });
      const blRows = [...backlog].sort((a, b) => b[1].overdue - a[1].overdue).map(([w, x]) => [w, num(x.open), num(x.overdue),
        `${(x.oldest / 24).toFixed(0)} days`, money(x.value)]);
      return `<div class="kpis">
          ${kpi({ label: "Avg hours to ship", value: c.shipH, fmt: hrs, prev: p?.shipH, good: "down", mode: "h", target: T.shipHours, series: series(ctx, "shipH") })}
          ${kpi({ label: "90th percentile to ship", value: c.p90, fmt: hrs, prev: p?.p90, good: "down", mode: "h", target: T.p90Ship })}
          ${kpi({ label: "On-time delivery", value: c.onTime, fmt: pct, prev: p?.onTime, mode: "pts", target: T.onTime, series: series(ctx, "onTime") })}
          ${kpi({ label: "Avg days to deliver", value: c.avgDays, fmt: (v) => (v == null ? "–" : v.toFixed(1) + " d"), prev: p?.avgDays, good: "down", mode: "abs", series: series(ctx, "avgDays") })}
          ${kpi({ label: "Open orders now", value: open, fmt: num, note: `${num(overdue)} past promised date` })}
        </div>
        ${deptActions(ctx, "Operations")}
        <div class="grid cols-3-2">
          ${panel("On-time delivery trend", "Share of orders delivered by the promised date, by delivery day.", `<div class="chart" id="c-ontime"></div>`)}
          ${panel("Open backlog", "Live snapshot of orders not yet delivered, worst first.",
            table([{ label: "Warehouse" }, { label: "Open", n: 1 }, { label: "Overdue", n: 1 }, { label: "Oldest", n: 1 }, { label: "Value", n: 1 }], blRows))}
        </div>
        <div class="grid cols-2">
          ${panel("Carrier scorecard", "Deliveries completed this period.",
            table([{ label: "Carrier" }, { label: "Deliveries", n: 1 }, { label: "On time", n: 1 }, { label: "Transit", n: 1 }, { label: "Late", n: 1 }, { label: "Rating", n: 1 }, { label: "SLA" }], carRows))}
          ${panel("Warehouse scorecard", "Orders placed this period, by fulfilling site.",
            table([{ label: "Warehouse" }, { label: "Orders", n: 1 }, { label: "Avg to ship", n: 1 }, { label: "P90", n: 1 }, { label: "On time", n: 1 }, { label: "Status" }], whRows))}
        </div>`;
    }, charts(ctx) {
      const x = ctx.daily.map((_, i) => iso(ctx.s + i));
      plot("c-ontime", [
        { type: "scatter", mode: "lines+markers", name: "On-time delivery", x, y: series(ctx, "onTime").map((v) => (v == null ? null : v * 100)),
          line: { color: S[0], width: 2.2 }, marker: { size: 6 }, hovertemplate: "%{x|%a %d %b}: %{y:.1f}%<extra></extra>" },
        { type: "scatter", mode: "lines", name: `Target ${T.onTime.text}`, x, y: x.map(() => T.onTime.value * 100), line: { color: "#d03b3b", width: 1.4, dash: "dash" }, hoverinfo: "skip" },
      ], { yaxis: { ticksuffix: "%", range: [40, 100] }, hovermode: "x unified" });
    } },

    finance: { title: "Finance", render(ctx) {
      const { cur: c, prev: p, s, e } = ctx;
      const pay = byOrder("pay", s, e, { init: () => ({ n: 0, f: 0, lost: 0, value: 0, col: 0 }),
        add: (x, i) => { x.n++; if (O.pfail[i]) x.f++; if (O.cr[i] === lostReason) { x.lost++; x.value += O.merch[i]; } if (O.paid[i]) x.col += O.merch[i] + O.ship[i]; } });
      const payRows = [...pay].sort((a, b) => b[1].col - a[1].col).map(([k, x]) => { const r = x.f / x.n;
        return [nice(DX.pay[k]), num(x.n), money(x.col), pct(r), num(x.lost), money(x.value), pill(statusOf(r, T.payFail))]; });
      const paidOrders = c.orders - c.lost;
      const ue = [["Average order value", money(c.aov)], ["COGS per order", money(ratio(c.cogs, paidOrders))],
        ["Gross profit per order", money(ratio(c.grossProfit, paidOrders))], ["Shipping revenue per order", money(ratio(c.ship, paidOrders))],
        ["Refunds as % of sales", `${pct(c.refundRate)} ${pill(statusOf(c.refundRate, T.refundRate))}`], ["Cancellation rate", pct(c.cancelRate)]];
      return `<div class="kpis">
          ${kpi({ label: "Gross sales", value: c.grossSales, fmt: money, prev: p?.grossSales, series: series(ctx, "grossSales") })}
          ${kpi({ label: "Refunds", value: c.refunds, fmt: money, prev: p?.refunds, good: "down", series: series(ctx, "refunds") })}
          ${kpi({ label: "Net revenue", value: c.netRevenue, fmt: money, prev: p?.netRevenue, series: series(ctx, "netRevenue") })}
          ${kpi({ label: "Gross profit", value: c.grossProfit, fmt: money, prev: p?.grossProfit, series: series(ctx, "grossProfit") })}
          ${kpi({ label: "Gross margin", value: c.margin, fmt: pct, prev: p?.margin, mode: "pts", target: T.margin, series: series(ctx, "margin") })}
          ${kpi({ label: "Revenue lost to failed payments", value: c.lostValue, fmt: money, prev: p?.lostValue, good: "down" })}
        </div>
        ${deptActions(ctx, "Finance")}
        <div class="grid cols-2-3">
          ${panel("Revenue bridge", "From gross sales to gross profit for the period.", `<div class="chart" id="c-bridge"></div>`)}
          ${panel("Daily revenue and profit", "Net revenue and gross profit by order date; refunds by the date issued.", `<div class="chart" id="c-fin"></div>`)}
        </div>
        <div class="grid cols-3-2">
          ${panel("Payment methods", "Collections and failures by payment method.",
            table([{ label: "Method" }, { label: "Orders", n: 1 }, { label: "Collected", n: 1 }, { label: "Failure rate", n: 1 }, { label: "Lost orders", n: 1 }, { label: "Lost value", n: 1 }, { label: "Status" }], payRows))}
          ${panel("Unit economics", "Per-order view of the period.", table([{ label: "Measure" }, { label: "Value", n: 1 }], ue))}
        </div>`;
    }, charts(ctx) {
      const c = ctx.cur;
      const steps = [["Gross sales", c.grossSales, "absolute"], ["Discounts", -c.disc, "relative"], ["Shipping", c.ship, "relative"],
        ["Refunds", -c.refunds, "relative"], ["Net revenue", c.netRevenue, "total"], ["COGS", -c.cogs, "relative"], ["Gross profit", c.grossProfit, "total"]];
      plot("c-bridge", [{ type: "waterfall", x: steps.map((x) => x[0]), y: steps.map((x) => x[1]), measure: steps.map((x) => x[2]),
        text: steps.map((x) => money(Math.abs(x[1]))), textposition: "outside", cliponaxis: false,
        increasing: { marker: { color: S[2] } }, decreasing: { marker: { color: S[7] } }, totals: { marker: { color: S[0] } },
        connector: { line: { color: AXIS } }, hovertemplate: "%{x}: $%{y:,.0f}<extra></extra>" }],
      { showlegend: false, yaxis: { tickprefix: "$", range: [0, c.grossSales * 1.15 || 1] }, height: 320 });
      const x = ctx.daily.map((_, i) => iso(ctx.s + i));
      plot("c-fin", [["netRevenue", "Net revenue", S[0]], ["grossProfit", "Gross profit", S[2]], ["refunds", "Refunds", S[7]]].map(([k, n, col]) => ({
        type: "scatter", mode: "lines", name: n, x, y: series(ctx, k), line: { color: col, width: 2 }, hovertemplate: `${n}: $%{y:,.0f}<extra></extra>` })),
      { yaxis: { tickprefix: "$", rangemode: "tozero" }, hovermode: "x unified", height: 320 });
    } },

    service: { title: "Customer service", render(ctx) {
      const { cur: c, prev: p } = ctx;
      const high = DATA.queue.filter((q) => q.priority === "high").length;
      const qRows = DATA.queue.map((q) => [q.order_id, q.order_date, nice(q.issue_type),
        `<span class="pill ${q.priority === "high" ? "off" : "watch"}">${q.priority}</span>`, `${q.days_open} days`, nice(q.order_status),
        q.carrier || "–", q.rating ? q.rating + " ★" : "–", money(q.order_total)]);
      return `<div class="kpis">
          ${kpi({ label: "Return rate", value: c.returnRate, fmt: pct, prev: p?.returnRate, good: "down", mode: "pts", target: T.returnRate, series: series(ctx, "returnRate") })}
          ${kpi({ label: "Returns requested", value: c.returns, fmt: num, prev: p?.returns, good: "down", series: series(ctx, "returns") })}
          ${kpi({ label: "Cancellations", value: c.cancelled, fmt: num, prev: p?.cancelled, good: "down", series: series(ctx, "cancelled") })}
          ${kpi({ label: "Average rating", value: c.rating, fmt: (v) => (v == null ? "–" : v.toFixed(2) + " ★"), prev: p?.rating, mode: "abs", target: T.rating, series: series(ctx, "rating") })}
          ${kpi({ label: "1–2★ review share", value: c.lowShare, fmt: pct, prev: p?.lowShare, good: "down", mode: "pts", target: T.lowRating })}
          ${kpi({ label: "High-priority cases", value: high, fmt: num, note: "open now" })}
        </div>
        ${deptActions(ctx, "Customer service")}
        <div class="grid cols-3-2">
          ${panel("Why customers return", "Return requests this period by reason and category.", `<div class="chart" id="c-reasons"></div>`)}
          ${panel("Late deliveries drive low ratings", "Rating distribution for orders delivered on time vs late.", `<div class="chart" id="c-ratings"></div>`)}
        </div>
        ${panel("Attention queue", "Open cases needing follow-up, highest priority and oldest first.",
          table([{ label: "Order" }, { label: "Ordered" }, { label: "Issue" }, { label: "Priority" }, { label: "Open", n: 1 }, { label: "Status" }, { label: "Carrier" }, { label: "Rating", n: 1 }, { label: "Value", n: 1 }], qRows))}`;
    }, charts(ctx) {
      const counts = new Map();
      for (let i = 0; i < N; i++) if (inR(O.retD[i], ctx.s, ctx.e) && O.rr[i] >= 0 && retCat[i] >= 0) {
        const key = O.rr[i] + "|" + retCat[i]; counts.set(key, (counts.get(key) || 0) + 1);
      }
      const totals = DX.rr.map((r, k) => ({ k, t: sum([...counts].filter(([key]) => key.startsWith(k + "|")).map((x) => x[1])) }))
        .filter((x) => x.t > 0).sort((a, b) => b.t - a.t);
      const traces = DX.cat.map((cat, ci) => ({ type: "bar", orientation: "h", name: cat, marker: { color: COLOR.cat[cat] },
        y: totals.map((x) => nice(DX.rr[x.k])), x: totals.map((x) => counts.get(x.k + "|" + ci) || 0),
        hovertemplate: `${cat}: %{x} returns<extra></extra>` }));
      plot("c-reasons", traces, { barmode: "stack", yaxis: { autorange: "reversed", gridcolor: "rgba(0,0,0,0)" }, height: 320, bargap: 0.35 });
      const dist = { 0: [0, 0, 0, 0, 0], 1: [0, 0, 0, 0, 0] };
      for (let i = 0; i < N; i++) if (inR(O.delD[i], ctx.s, ctx.e) && O.rating[i] !== null) dist[O.late[i] ? 1 : 0][5 - O.rating[i]]++;
      const stars = ["5 ★", "4 ★", "3 ★", "2 ★", "1 ★"];
      plot("c-ratings", [[0, "On time", S[0]], [1, "Late", S[1]]].map(([k, n, col]) => {
        const t = sum(dist[k]) || 1;
        return { type: "bar", name: `${n} (avg ${(sum(dist[k].map((v, j) => v * (5 - j))) / t).toFixed(2)} ★)`, x: stars,
          y: dist[k].map((v) => (v / t) * 100), marker: { color: col }, hovertemplate: `${n} · %{x}: %{y:.1f}%<extra></extra>` };
      }), { barmode: "group", yaxis: { ticksuffix: "%" }, height: 320, bargap: 0.25 });
    } },

    platform: { title: "Architecture & orchestration", render: null, charts: null },
  };


  // ------------------------------------------------------------------ AI (when served by ai/server.py)
  const SERVED = location.protocol === "http:" || location.protocol === "https:";
  const AI = { checked: !SERVED, online: false, model: "", reason: SERVED ? "" : "file",
    briefs: {}, loading: {}, errors: {}, chat: [], busy: false };
  const shortModel = (m) => String(m || "").split("/").pop().replace(/:free$/, "");

  async function api(path, options) {
    const res = await fetch(path, options);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
    return body;
  }

  function loadBrief(days, refresh = false) {
    if (AI.loading[days]) return;
    AI.loading[days] = true;
    delete AI.errors[days];
    api(`/api/decisions?days=${days}${refresh ? "&refresh=true" : ""}`)
      .then((brief) => { AI.briefs[days] = brief; })
      .catch((error) => { AI.errors[days] = error.message; })
      .finally(() => { AI.loading[days] = false; if (state.days === days && state.view !== "platform") render(true); });
  }

  function briefFor(ctx) {
    if (!AI.checked) return { mode: "loading", list: [], text: "Connecting to the AI analyst…" };
    if (!AI.online) return { mode: "rules", list: insights(ctx) };
    const brief = AI.briefs[state.days];
    if (brief) return { mode: "ai", list: brief.decisions, brief };
    if (AI.errors[state.days]) return { mode: "error", list: insights(ctx), error: AI.errors[state.days] };
    loadBrief(state.days);
    return { mode: "loading", list: [], text: `The AI analyst is reviewing ${state.days} days of data` };
  }

  function trace(steps, footer) {
    if (!steps || !steps.length) return footer ? `<div class="ai-meta">${footer}</div>` : "";
    return `<details class="ai-trace"><summary>How the AI got this · ${steps.length} ${steps.length === 1 ? "query" : "queries"}${footer ? " · " + footer : ""}</summary>
      ${steps.map((st) => `<div class="ai-step ${st.ok ? "" : "failed"}"><div><b>${esc(st.purpose || st.tool)}</b>
        <span class="muted">${st.ok ? (st.tool === "run_sql" ? `${st.rows} rows` : "") : "failed: " + esc(st.error)}</span></div>
        ${st.query ? `<pre>${esc(st.query)}</pre>` : ""}</div>`).join("")}</details>`;
  }

  function decisionsPanel(ctx, dept) {
    const src = briefFor(ctx);
    const title = dept ? "Recommended actions" : "Decisions needed";
    if (src.mode === "loading") {
      return panel(title, "", `<div class="ai-loading"><div class="spinner"></div><div><b>${src.text}</b><br>
        <span class="muted">It writes and runs its own SQL queries against the Gold tables and compares with the prior period. This usually takes 20–90 seconds.</span></div></div>`,
        `<span class="pill ai">✦ AI analyst working</span>`);
    }
    const list = dept ? src.list.filter((x) => x.dept === dept) : src.list;
    const body = list.length ? `<div class="${dept ? "" : "decision-grid"}">${decisions(list, dept ? 4 : 6)}</div>`
      : `<div class="empty">${src.mode === "ai" ? "The AI analyst raised no decisions for this department this period." : "Nothing needs attention in this period."}</div>`;
    if (src.mode === "ai") {
      const b = src.brief;
      const footer = `${b.llm_calls} model calls · generated ${esc(b.generated_at)}${b.cached ? " (cached)" : ""}`;
      return panel(title, b.summary ? esc(b.summary) : "AI analysis of this period.", body + trace(b.queries, footer),
        `<div class="ai-badges"><span class="pill ai">✦ AI · ${esc(shortModel(b.model))}</span>
         <button class="link-btn" data-ai-refresh>Regenerate</button></div>`);
    }
    const note = src.mode === "error"
      ? `<div class="ai-note warn">AI analysis failed: ${esc(src.error)} Showing the rule-based checks instead. <button class="link-btn" data-ai-retry>Try again</button></div>`
      : `<div class="ai-note">${AI.reason === "file" ? "Open this dashboard through the AI server (<code>python -m ai.server</code>, then http://localhost:8000) for AI-generated decisions."
          : AI.reason === "server" ? "The AI server is not reachable. Showing rule-based checks."
          : "AI is not configured on the server (add <code>OPENROUTER_API_KEY</code> to <code>.env</code>). Showing rule-based checks."}</div>`;
    return panel(title, "Rule-based checks against plan targets.", note + body, `<span class="pill info">Rule-based</span>`);
  }

  // Lightweight markdown for agent answers (input is escaped first).
  function md(source) {
    const inline = (t) => t.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<i>$2</i>");
    const lines = esc(source).split("\n");
    let html = "", i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (/^\s*```/.test(line)) {
        const code = []; i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
        i++; html += `<pre>${code.join("\n")}</pre>`; continue;
      }
      if (/^\s*\|/.test(line)) {
        const rows = [];
        while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
        const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
        const body = rows.filter((r) => !(/^[\s|:-]+$/.test(r) && r.includes("-")));
        if (body.length) html += `<div class="table-wrap"><table class="md"><thead><tr>${cells(body[0]).map((c) => `<th>${c}</th>`).join("")}</tr></thead>
          <tbody>${body.slice(1).map((r) => `<tr>${cells(r).map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
        continue;
      }
      const bullet = /^\s*[-*•]\s+/, numbered = /^\s*\d+[.)]\s+/;
      if (bullet.test(line) || numbered.test(line)) {
        const tag = bullet.test(line) ? "ul" : "ol", re = tag === "ul" ? bullet : numbered, items = [];
        while (i < lines.length && re.test(lines[i])) items.push(inline(lines[i++].replace(re, "")));
        html += `<${tag}>${items.map((x) => `<li>${x}</li>`).join("")}</${tag}>`; continue;
      }
      if (/^\s*#{1,4}\s+/.test(line)) { html += `<h4>${inline(line.replace(/^\s*#+\s+/, ""))}</h4>`; i++; continue; }
      if (!line.trim()) { i++; continue; }
      const para = [];
      while (i < lines.length && lines[i].trim() && !/^\s*(\||```|#{1,4}\s|[-*•]\s|\d+[.)]\s)/.test(lines[i])) para.push(inline(lines[i++]));
      html += `<p>${para.join("<br>")}</p>`;
    }
    return html;
  }

  const STARTERS = [
    "Why did net sales change last week, and which channel drove it?",
    "Which carrier should we give more volume to, and why?",
    "What are our five most profitable products this month?",
    "How much revenue sits with customers in the At Risk segment?",
    "Which warehouse is slowest to ship and is it getting better?",
  ];

  function renderChat() {
    const body = document.getElementById("ask-body");
    if (!body) return;
    document.getElementById("ask-model").textContent = AI.online ? `Data agent · ${shortModel(AI.model)}` : "Data agent";
    const form = document.getElementById("ask-form");
    form.classList.toggle("disabled", !AI.online);
    if (!AI.online) {
      body.innerHTML = `<div class="ask-empty"><h3>AI is offline</h3><p>${AI.reason === "file"
        ? "This file was opened directly from disk. Start the AI server with <code>python -m ai.server</code> and open <b>http://localhost:8000</b>."
        : AI.reason === "server" ? "The AI server is not reachable. Start it with <code>python -m ai.server</code>."
        : AI.checked ? "Add <code>OPENROUTER_API_KEY</code> to <code>.env</code> and restart the server." : "Connecting…"}</p></div>`;
      return;
    }
    let html = "";
    if (!AI.chat.length) {
      html = `<div class="ask-empty"><h3>Ask anything about the business</h3>
        <p>The agent writes and runs SQL against the warehouse and answers with the numbers it finds. Every answer shows the queries it ran.</p>
        <div class="starters">${STARTERS.map((q) => `<button class="starter" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div></div>`;
    }
    html += AI.chat.map((m) => m.role === "user" ? `<div class="msg user">${esc(m.content)}</div>`
      : m.role === "error" ? `<div class="msg error">${esc(m.content)}</div>`
      : `<div class="msg bot">${md(m.content)}${trace(m.steps, `${m.calls} model calls`)}</div>`).join("");
    if (AI.busy) html += `<div class="msg bot thinking"><div class="spinner small"></div>Querying the warehouse…</div>`;
    body.innerHTML = html;
    body.scrollTop = body.scrollHeight;
  }

  async function askAI(question) {
    question = question.trim();
    if (!question || AI.busy || !AI.online) return;
    const history = AI.chat.filter((m) => m.role !== "error").map((m) => ({ role: m.role, content: m.content }));
    AI.chat.push({ role: "user", content: question });
    AI.busy = true;
    renderChat();
    try {
      const r = await api("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, history }) });
      AI.chat.push({ role: "assistant", content: r.answer, steps: r.steps, calls: r.llm_calls });
    } catch (error) {
      AI.chat.push({ role: "error", content: error.message });
    }
    AI.busy = false;
    renderChat();
  }

  function setupAI() {
    const button = document.createElement("button");
    button.className = "ask-btn";
    button.innerHTML = "✦ Ask AI";
    document.querySelector(".controls").prepend(button);
    const drawer = document.createElement("aside");
    drawer.className = "ask-drawer";
    drawer.setAttribute("aria-label", "Ask AI");
    drawer.innerHTML = `<div class="ask-head"><div><b>Ask Northstar AI</b><div class="muted" id="ask-model">Data agent</div></div>
        <button class="icon-btn" id="ask-close" aria-label="Close">✕</button></div>
      <div class="ask-body" id="ask-body"></div>
      <form class="ask-form" id="ask-form"><textarea id="ask-input" rows="2" placeholder="Ask about sales, customers, delivery, finance…"></textarea>
        <button type="submit" class="send">Ask</button></form>`;
    document.body.append(drawer);
    const input = drawer.querySelector("#ask-input");
    const toggle = (open) => { document.body.classList.toggle("ask-open", open); if (open) { renderChat(); input.focus(); } };
    button.addEventListener("click", () => toggle(!document.body.classList.contains("ask-open")));
    drawer.querySelector("#ask-close").addEventListener("click", () => toggle(false));
    drawer.querySelector("#ask-form").addEventListener("submit", (ev) => { ev.preventDefault(); askAI(input.value); input.value = ""; });
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); askAI(input.value); input.value = ""; } });
    drawer.addEventListener("click", (ev) => { const b = ev.target.closest("[data-q]"); if (b) askAI(b.dataset.q); });
    document.addEventListener("click", (ev) => {
      if (ev.target.closest("[data-ai-refresh]")) { delete AI.briefs[state.days]; loadBrief(state.days, true); render(true); }
      if (ev.target.closest("[data-ai-retry]")) { delete AI.errors[state.days]; render(true); }
    });
    if (SERVED) {
      api("/api/health")
        .then((h) => { AI.online = !!h.ai; AI.model = h.model; AI.reason = h.ai ? "" : "key"; })
        .catch(() => { AI.reason = "server"; })
        .finally(() => { AI.checked = true; render(true); renderChat(); });
    }
  }

  // ------------------------------------------------------------------ shell
  function render(keepScroll = false) {
    const ctx = context();
    const view = VIEWS[state.view] || VIEWS.overview;
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + state.view));
    document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === state.view));
    document.querySelectorAll("#period button").forEach((b) => b.classList.toggle("active", +b.dataset.days === state.days));
    document.getElementById("period").style.visibility = view.render ? "visible" : "hidden";
    document.getElementById("view-title").textContent = view.title;
    document.getElementById("crumb").textContent = state.view === "platform" ? "Platform"
      : `${short(ctx.s)} – ${short(ctx.e)}, ${new Date(BASE + ctx.e * DAY).getUTCFullYear()}${ctx.hasPrior ? ` · compared with ${short(ctx.ps)} – ${short(ctx.pe)}` : ""}`;
    if (view.render) {
      charts.splice(0).forEach((el) => Plotly.purge(el));
      document.getElementById("view-" + state.view).innerHTML = view.render(ctx);
      view.charts(ctx);
    }
    if (!keepScroll) window.scrollTo({ top: 0 });
  }

  function init() {
    const P = DATA.platform;
    document.getElementById("asof").innerHTML = `Data through <b>${short(DATA.asOf)}</b>`;
    document.getElementById("pipeline-status").innerHTML = `<div><span class="dot"></span><b>Pipeline healthy</b></div>
      <div>${P.checks}/${P.totalChecks} quality checks passed</div><div>Refreshed ${DATA.generated}</div>`;
    document.getElementById("platform-strip").innerHTML = [
      ["Last pipeline run", P.runSeconds ? `${Math.round(P.runSeconds)} s` : "–"],
      ["Quality checks", `${P.checks} / ${P.totalChecks} passed`], ["Schedule", "every 10 min"], ["Maintenance", "nightly 03:00"],
    ].map(([l, v]) => `<div><b>${v}</b>${l}</div>`).join("");
    document.getElementById("foot").textContent =
      `Northstar Commerce is a fictional retailer; all figures are synthetic, produced by the project's event simulator and lakehouse pipeline. Generated ${DATA.generated}.`;
    document.getElementById("period").addEventListener("click", (ev) => {
      const b = ev.target.closest("button"); if (!b) return; state.days = +b.dataset.days; render();
    });
    const route = () => { const v = location.hash.slice(1); state.view = VIEWS[v] ? v : "overview"; render(); };
    window.addEventListener("hashchange", route);
    setupAI();
    route();
  }
  init();
})();
