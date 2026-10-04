// Point every "Open the app" button at the deployed Streamlit app.
document.querySelectorAll("[data-app-link]").forEach((a) => {
  a.href = window.ATTENDSENSE_APP_URL || "#";
  a.target = "_blank";
  a.rel = "noopener";
});
document.getElementById("year").textContent = new Date().getFullYear();

// The same arithmetic as app/src/core/analytics.py (classes_needed / classes_can_miss).
function classesNeeded(a, t, target) {
  if (t === 0 || a / t >= target) return 0;
  if (target >= 1) return a < t ? -1 : 0;
  return Math.ceil((target * t - a) / (1 - target) - 1e-9);
}
function classesCanMiss(a, t, target) {
  if (t === 0 || target <= 0 || a / t < target) return 0;
  return Math.max(0, Math.floor(a / target - t + 1e-9));
}

const att = document.getElementById("att");
const tot = document.getElementById("tot");
const tgt = document.getElementById("tgt");
const out = document.getElementById("calc-out");
const fill = document.getElementById("meter-fill");
const mark = document.getElementById("meter-target");

function update() {
  let t = Math.max(0, Math.floor(+tot.value || 0));
  let a = Math.min(t, Math.max(0, Math.floor(+att.value || 0)));
  const target = Math.min(100, Math.max(1, +tgt.value || 75)) / 100;
  const pct = t ? (100 * a) / t : 0;
  fill.style.width = pct + "%";
  fill.style.background = pct >= target * 100 ? "var(--ok)" : pct >= target * 100 - 10 ? "var(--warn)" : "var(--bad)";
  mark.style.left = `calc(${target * 100}% - 1px)`;

  if (t === 0) { out.textContent = "No classes held yet."; return; }
  const need = classesNeeded(a, t, target);
  const label = `${pct.toFixed(1)}% now. `;
  if (need > 0) out.textContent = label + `Attend the next ${need} class${need > 1 ? "es" : ""} in a row to reach ${Math.round(target * 100)}%.`;
  else if (need < 0) out.textContent = label + `${Math.round(target * 100)}% can no longer be reached.`;
  else {
    const miss = classesCanMiss(a, t, target);
    out.textContent = label + `On track: you can miss ${miss} class${miss === 1 ? "" : "es"} and stay above target.`;
  }
}
[att, tot, tgt].forEach((el) => el.addEventListener("input", update));
update();
