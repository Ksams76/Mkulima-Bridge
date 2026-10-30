window.MKULIMA_AUTH_READY.then((authenticated) => {
  if (!authenticated) return;
/* Additional MkulimaBridge-ready modules. Kept separate from the original app.js. */
(() => {
  "use strict";
  const API_BASE = window.location.port === "5500" ? `http://${window.location.hostname}:8000` : "";
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  async function request(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    const response = await fetch(`${API_BASE}${path}`, { ...options, credentials: API_BASE ? "include" : "same-origin", headers });
    let data = {};
    try { data = await response.json(); } catch (_) { /* non-JSON error */ }
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`);
    return data;
  }
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function metricCard(value, label) {
    const card = node("article", null, "metric-card");
    card.append(node("strong", value), node("span", label));
    return card;
  }

  // Farmer workspace dashboard.
  async function loadWorkspace() {
    const metrics = $("workspace-metrics");
    try {
      const [data, preferences] = await Promise.all([request("/dashboard/summary"), request("/settings")]);
      settingsState = preferences;
      metrics.replaceChildren(
        metricCard(data.open_cases, "Open / active cases"),
        metricCard(data.pending_actions, "Pending FarmActions"),
        metricCard(preferences.low_stock_alerts === false ? "Off" : data.low_stock_items, preferences.low_stock_alerts === false ? "Low-stock alerts" : "Low-stock items"),
        metricCard(data.learning_sessions, "Practice sessions")
      );
      const upcoming = $("workspace-upcoming"); upcoming.replaceChildren();
      if (preferences.in_app_reminders === false) {
        upcoming.append(node("p", "In-app FarmAction reminders are turned off in Settings. Open FarmAction to view your saved tasks."));
      } else if (!data.upcoming_actions.length) upcoming.append(node("p", "No pending actions yet."));
      if (preferences.in_app_reminders !== false) data.upcoming_actions.forEach((item) => {
        const row = node("article", null, "mini-record");
        row.append(node("strong", item.title), node("small", new Date(item.due_at).toLocaleString()));
        upcoming.append(row);
      });
      const cases = $("workspace-recent-cases"); cases.replaceChildren();
      if (!data.recent_cases.length) cases.append(node("p", "No farm cases recorded yet."));
      data.recent_cases.forEach((item) => {
        const row = node("article", null, "mini-record");
        const subject = item.case_type === "livestock" ? (item.species || "Livestock") : (item.crop || "Crop");
        row.append(node("strong", `${item.case_ref} · ${item.title}`), node("small", `${subject} · ${item.status}`));
        cases.append(row);
      });
      $("workspace-scope").textContent = `Workspace updated ${new Date().toLocaleString()} · ${data.scope}.`;
    } catch (error) {
      metrics.replaceChildren(node("p", `Workspace unavailable: ${error.message}`));
    }
  }
  $("refresh-workspace")?.addEventListener("click", loadWorkspace);

  // Learning centre with recorded practice sessions.
  let modules = [];
  async function loadLearning() {
    try {
      [modules] = await Promise.all([request("/learning/modules")]);
      const progress = await request("/learning/progress");
      $("learning-progress").replaceChildren(
        metricCard(progress.sessions, "Practice sessions"),
        metricCard(progress.average_percent === null ? "—" : `${progress.average_percent}%`, "Average score"),
        metricCard(progress.best_percent === null ? "—" : `${progress.best_percent}%`, "Best score")
      );
      const grid = $("learning-modules"); grid.replaceChildren();
      modules.forEach((item) => {
        const card = node("article", null, "module-card");
        card.append(node("h3", item.title), node("p", item.summary), node("small", `Estimated ${item.duration}`));
        const button = node("button", "Start practice"); button.type = "button";
        button.addEventListener("click", () => openLearning(item));
        card.append(button); grid.append(card);
      });
      const history = $("learning-history"); history.replaceChildren();
      if (!progress.recent.length) history.append(node("p", "Your completed practice sessions will appear here."));
      progress.recent.forEach((session) => {
        history.append(node("article", `${session.module_title}: ${session.score}/${session.total} · ${new Date(session.completed_at).toLocaleString()}`, "history-item"));
      });
    } catch (error) {
      $("learning-modules").replaceChildren(node("p", `Learning modules unavailable: ${error.message}`));
    }
  }
  function openLearning(item) {
    $("learning-title").textContent = item.title;
    const language = $("language")?.value || "English";
    $("learning-content").textContent = language === "Kiswahili" ? item.content_sw : item.content;
    const source = $("learning-source"); source.replaceChildren();
    source.append(document.createTextNode("Learning reference: "));
    const link = node("a", item.source_title); link.href = item.source_url; link.target = "_blank"; link.rel = "noopener noreferrer"; source.append(link);
    const form = $("learning-quiz"); form.replaceChildren(); form.dataset.moduleId = item.id;
    const quizItems = language === "Kiswahili" ? item.quiz_sw : item.quiz;
    form.dataset.language = language;
    quizItems.forEach((question, index) => {
      const fieldset = node("fieldset", null, "quiz-question");
      fieldset.append(node("legend", `${index + 1}. ${question.question}`));
      question.options.forEach((option, choice) => {
        const label = node("label", null, "quiz-option");
        const input = document.createElement("input"); input.type = "radio"; input.name = `quiz-${index}`; input.value = String(choice); input.required = true;
        label.append(input, document.createTextNode(option)); fieldset.append(label);
      });
      form.append(fieldset);
    });
    const submit = node("button", "Submit practice answers"); submit.type = "submit"; form.append(submit);
    $("learning-result").textContent = "";
    $("learning-activity").hidden = false;
    $("learning-activity").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  $("close-learning")?.addEventListener("click", () => { $("learning-activity").hidden = true; });
  $("learning-quiz")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const selected = [...form.querySelectorAll("fieldset")].map((fieldset) => fieldset.querySelector("input:checked"));
    if (selected.some((item) => !item)) { $("learning-result").textContent = "Please answer every question."; return; }
    const button = form.querySelector("button[type=submit]"); button.disabled = true;
    try {
      const result = await request("/learning/sessions", { method: "POST", body: JSON.stringify({ module_id: form.dataset.moduleId, answers: selected.map((item) => Number(item.value)) }) });
      const explanations = form.dataset.language === "Kiswahili" ? result.explanations_sw : result.explanations;
      const detail = explanations.map((text, index) => `${index + 1}. ${text}`).join("\n");
      $("learning-result").textContent = `Practice recorded: ${result.score}/${result.total} (${result.percent}%).\n${detail}`;
      await loadLearning(); await loadWorkspace();
    } catch (error) { $("learning-result").textContent = `Practice could not be saved: ${error.message}`; }
    finally { button.disabled = false; }
  });

  // Community Pulse: immediately confirms saved reports; shared groups stay threshold-protected.
  const COMMUNITY_CROP_CATEGORIES = ["Leaf discolouration", "Insect activity", "Visible leaf or fruit spots", "Wilting or poor growth", "Water or drainage concern", "Storage or post-harvest concern", "Other crop concern"];
  const COMMUNITY_LIVESTOCK_CATEGORIES = ["Reduced appetite or not eating", "Unusual behaviour or weakness", "Coughing or breathing concern", "Diarrhoea or digestive concern", "Skin, coat or parasite concern", "Lameness or movement concern", "Reproductive or birthing concern", "Egg or milk production change", "Injury or wound", "Sudden illness or multiple animals affected", "Other animal health concern"];
  function syncCommunityReportType() {
    const livestock = $("community-case-type").value === "livestock";
    $("community-crop-group").hidden = livestock;
    $("community-species-group").hidden = !livestock;
    $("community-crop").required = !livestock;
    $("community-species").required = livestock;
    const category = $("community-category");
    const previous = category.value;
    category.replaceChildren(new Option("Choose a category", ""));
    (livestock ? COMMUNITY_LIVESTOCK_CATEGORIES : COMMUNITY_CROP_CATEGORIES).forEach((label) => category.append(new Option(label, label)));
    if ([...category.options].some((option) => option.value === previous)) category.value = previous;
  }
  $("community-case-type")?.addEventListener("change", syncCommunityReportType);
  async function loadCommunity() {
    try {
      const data = await request("/community/pulse?days=30");
      const list = $("community-results"); list.replaceChildren();
      list.append(node("p", `${data.total_reports} category-only farmer reports received in the last ${data.days} days. Similar groups are shown only when at least three reports are aggregated.`));
      if (!data.groups.length) list.append(node("p", "Reports are being collected. No group has reached the privacy threshold for shared display yet."));
      data.groups.forEach((group) => {
        const card = node("article", null, "case-item");
        const subject = group.case_type === "livestock" ? `${group.species || "Livestock"} · animal concern` : group.crop;
        card.append(node("h3", `${subject} · ${group.category}`), node("p", `${group.county} County · ${group.report_count} farmer reports`), node("small", `Latest report ${new Date(group.latest_report).toLocaleDateString()}`), node("span", group.evidence_label, "case-muted"));
        list.append(card);
      });
    } catch (error) { $("community-results").replaceChildren(node("p", `Community trends unavailable: ${error.message}`)); }
  }
  $("community-report-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    // Keep a stable reference: event.currentTarget becomes null after an await.
    const form = event.currentTarget;
    const caseType = $("community-case-type").value;
    const payload = { case_type: caseType, crop: caseType === "crop" ? $("community-crop").value.trim() : null, species: caseType === "livestock" ? $("community-species").value : null, county: $("community-county").value.trim(), category: $("community-category").value, consent: $("community-consent").checked };
    const button = event.currentTarget.querySelector('button[type="submit"]'); button.disabled = true; button.textContent = "Sharing report…";
    try {
      const result = await request("/community/reports", { method: "POST", body: JSON.stringify(payload) });
      $("community-message").textContent = `Report #${result.id} saved. ${result.message}`;
      form.reset(); syncCommunityReportType(); await loadCommunity();
    } catch (error) { $("community-message").textContent = `Report not shared: ${error.message}`; }
    finally { button.disabled = false; button.textContent = "Share category report"; }
  });
  $("refresh-community")?.addEventListener("click", loadCommunity);

  // ExpertConnect maps each case type to a suitable expertise category.
  let referralCases = new Map();
  async function loadExpertCategories(caseType) {
    const select = $("referral-category"); const hint = $("referral-category-help"); select.replaceChildren(new Option("Loading specialist categories…", ""));
    try {
      const categories = await request(`/expert/categories?case_type=${encodeURIComponent(caseType || "crop")}`);
      select.replaceChildren(new Option("Choose expertise category", ""));
      categories.forEach((item) => select.append(new Option(item.label, item.key)));
      select.dataset.recommendations = JSON.stringify(categories);
      hint.textContent = "Select the kind of professional you need. This prototype recommends an expertise type, not a named or verified expert.";
    } catch (error) { select.replaceChildren(new Option("Specialist categories unavailable", "")); hint.textContent = error.message; }
  }
  async function loadReferralCases() {
    const select = $("referral-case");
    const hint = $("referral-case-help");
    if (!select) return;
    select.disabled = true;
    select.replaceChildren(new Option("Loading your saved cases…", ""));
    try {
      // Load both crop and livestock cases belonging to the signed-in farmer.
      const cases = await request("/cases?limit=100");
      select.replaceChildren(new Option("Choose a farm case", ""));
      referralCases = new Map();
      cases.forEach((item) => {
        referralCases.set(String(item.id), item);
        const subject = item.case_type === "livestock" ? (item.species || "Livestock") : (item.crop || "Crop");
        const typeLabel = item.case_type === "livestock" ? "Animal" : "Crop";
        select.append(new Option(`${item.case_ref} · ${typeLabel}: ${subject} · ${item.title}`, String(item.id)));
      });
      if (!cases.length) {
        select.append(new Option("No saved cases in this account yet", ""));
        if (hint) hint.textContent = "Create a case in Farm Cases or Livestock Care first, then return here or refresh this list.";
      } else if (hint) {
        hint.textContent = `${cases.length} saved case${cases.length === 1 ? "" : "s"} available, including crop and livestock cases.`;
      }
    } catch (error) {
      select.replaceChildren(new Option("Could not load your cases", ""));
      if (hint) hint.textContent = `Case list could not be loaded: ${error.message}`;
    } finally {
      select.disabled = false;
    }
  }
  $("refresh-referral-cases")?.addEventListener("click", loadReferralCases);
  // The list may be empty on first visit and populated after the farmer creates a case.
  window.addEventListener("mkb:cases-updated", loadReferralCases);
  document.addEventListener("click", (event) => {
    if (event.target.closest('[data-view-link="expert-connect"]')) loadReferralCases();
  });
  $("referral-case")?.addEventListener("change", () => {
    const chosen = referralCases.get($("referral-case").value);
    if (chosen) loadExpertCategories(chosen.case_type || "crop");
    else { $("referral-category").replaceChildren(new Option("Choose a case first", "")); $("referral-category-help").textContent = "Select a farm case to see suitable expert categories."; }
  });
  $("referral-category")?.addEventListener("change", () => {
    const chosen = [...JSON.parse($("referral-category").dataset.recommendations || "[]")].find((item) => item.key === $("referral-category").value);
    if (chosen) $("referral-category-help").textContent = `${chosen.description} Suggested professional: ${chosen.role}.`;
  });
  async function loadReferrals() {
    try {
      const referrals = await request("/referrals"); const list = $("referral-list"); list.replaceChildren();
      if (!referrals.length) list.append(node("p", "No referral summaries prepared yet."));
      referrals.forEach((item) => {
        const card = node("article", null, "case-item");
        card.append(node("h3", `${item.case_ref} · ${item.status.replaceAll("_", " ")}`), node("p", `Recommended: ${item.recommended_role || item.expert_category || "General agricultural adviser"}`), node("p", `Urgency: ${item.urgency || "routine"} · Updated ${new Date(item.updated_at).toLocaleString()}`));
        const expert = document.createElement("input"); expert.placeholder = "Expert name (only after a real person is identified)"; expert.maxLength = 120; expert.value = item.expert_name || "";
        const notes = document.createElement("input"); notes.placeholder = "Follow-up note (optional)"; notes.maxLength = 500; notes.value = item.notes || "";
        const status = document.createElement("select");
        [["prepared","Prepared"],["shared_by_farmer","Shared by farmer"],["response_received","Response received"],["closed","Closed"]].forEach(([value,label]) => status.append(new Option(label,value)));
        status.value = item.status;
        const save = node("button", "Update referral record"); save.type = "button";
        save.addEventListener("click", async () => {
          save.disabled = true;
          try { await request(`/referrals/${item.id}`, { method: "PATCH", body: JSON.stringify({ status: status.value, expert_name: expert.value.trim() || null, notes: notes.value.trim() || null }) }); $("referral-message").textContent = "Referral tracking record updated."; await loadReferrals(); }
          catch (error) { $("referral-message").textContent = error.message; }
          finally { save.disabled = false; }
        });
        card.append(expert, notes, status, save); list.append(card);
      });
    } catch (error) { $("referral-list").replaceChildren(node("p", `Referral records unavailable: ${error.message}`)); }
  }
  $("prepare-referral")?.addEventListener("click", async () => {
    const id = $("referral-case").value; const category = $("referral-category").value;
    if (!id) { $("referral-message").textContent = "Choose a farm or livestock case first."; return; }
    if (!category) { $("referral-message").textContent = "Choose the type of expert you need."; return; }
    const button = $("prepare-referral"); button.disabled = true; button.textContent = "Preparing summary…";
    try {
      const data = await request(`/cases/${id}/referrals`, { method: "POST", body: JSON.stringify({ expert_category: category, urgency: $("referral-urgency").value, additional_context: $("referral-context").value.trim() || null }) });
      $("referral-summary-text").value = data.summary; $("referral-summary").hidden = false;
      $("referral-message").textContent = `${data.message} Recommended expertise: ${data.recommended_role}.`;
      await loadReferrals();
    } catch (error) { $("referral-message").textContent = `Could not prepare summary: ${error.message}`; }
    finally { button.disabled = false; button.textContent = "Prepare expert summary"; }
  });
  $("copy-referral")?.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("referral-summary-text").value); $("referral-message").textContent = "Summary copied. You control where and with whom you share it."; }
    catch (_) { $("referral-message").textContent = "Clipboard access is unavailable. Select and copy the summary manually."; }
  });

  // Inventory: every saved field can be edited, and the UI refreshes from the server after each mutation.
  async function loadInventory() {
    const list = $("inventory-list"); list.replaceChildren(node("p", "Loading inventory…"));
    try {
      const items = await request("/inventory"); list.replaceChildren();
      const lowCount = items.filter((item) => item.low_stock).length;
      const summary = node("p", `${items.length} inventory items · ${lowCount} at or below their reorder alert.`); list.append(summary);
      if (!items.length) list.append(node("p", "No inventory items recorded yet. Add an item using the form above."));
      items.forEach((item) => {
        const card = node("article", null, `case-item${item.low_stock ? " low-stock-item" : ""}`);
        const name = document.createElement("input"); name.value = item.name; name.maxLength = 120; name.setAttribute("aria-label", `Item name for ${item.name}`);
        const category = document.createElement("select");
        ["Seed","Fertiliser","Animal feed","Veterinary supplies","Tools","Irrigation","Packaging","Other"].forEach((value) => category.append(new Option(value,value)));
        if (![...category.options].some((option) => option.value === item.category)) category.append(new Option(item.category,item.category));
        category.value = item.category;
        const unit = document.createElement("input"); unit.value = item.unit; unit.maxLength = 30; unit.setAttribute("aria-label", `Unit for ${item.name}`);
        const quantity = document.createElement("input"); quantity.type = "number"; quantity.min = "0"; quantity.step = "0.01"; quantity.value = item.quantity; quantity.setAttribute("aria-label", `Quantity for ${item.name}`);
        const reorder = document.createElement("input"); reorder.type = "number"; reorder.min = "0"; reorder.step = "0.01"; reorder.value = item.reorder_level; reorder.setAttribute("aria-label", `Reorder level for ${item.name}`);
        const notes = document.createElement("input"); notes.value = item.notes || ""; notes.maxLength = 500; notes.placeholder = "Notes";
        const labelField = (text, input) => { const label = node("label", text); label.append(input); return label; };
        card.append(node("h3", item.name), node("p", `${item.category} · ${item.quantity} ${item.unit} on hand · Alert at ${item.reorder_level} ${item.unit}`), node("p", item.low_stock ? "LOW STOCK — check whether replenishment is needed." : "Stock is above your reorder level."), labelField("Item name",name), labelField("Category",category), labelField("Unit",unit), labelField("Quantity on hand",quantity), labelField("Reorder alert at",reorder), labelField("Notes",notes));
        const save = node("button", "Save item changes"); save.type = "button";
        save.addEventListener("click", async () => {
          save.disabled = true;
          try {
            const result = await request(`/inventory/${item.id}`, { method: "PATCH", body: JSON.stringify({ name: name.value.trim(), category: category.value, unit: unit.value.trim(), quantity: Number(quantity.value), reorder_level: Number(reorder.value), notes: notes.value.trim() }) });
            $("inventory-message").textContent = `${result.name} updated successfully.`; await loadInventory(); await loadWorkspace();
          } catch (error) { $("inventory-message").textContent = `Inventory update failed: ${error.message}`; }
          finally { save.disabled = false; }
        });
        const del = node("button", "Delete item", "secondary-button"); del.type = "button";
        del.addEventListener("click", async () => { if (!window.confirm(`Delete ${item.name} from inventory?`)) return; try { await request(`/inventory/${item.id}`, { method: "DELETE" }); $("inventory-message").textContent = `${item.name} deleted.`; await loadInventory(); await loadWorkspace(); } catch (error) { $("inventory-message").textContent = error.message; } });
        card.append(save, del); list.append(card);
      });
    } catch (error) { list.replaceChildren(node("p", `Inventory unavailable: ${error.message}`)); $("inventory-message").textContent = error.message; }
  }
  $("refresh-inventory")?.addEventListener("click", loadInventory);
  $("inventory-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    // Keep a stable form reference across the asynchronous save request.
    const form = event.currentTarget;
    const button = form.querySelector('button[type="submit"]'); button.disabled = true;
    const payload = { name: $("inventory-name").value.trim(), category: $("inventory-category").value, unit: $("inventory-unit").value.trim(), quantity: Number($("inventory-quantity").value), reorder_level: Number($("inventory-reorder").value), notes: $("inventory-notes").value.trim() || null };
    try {
      const result = await request("/inventory", { method: "POST", body: JSON.stringify(payload) });
      form.reset(); $("inventory-unit").value = "units"; $("inventory-reorder").value = "0";
      $("inventory-message").textContent = `${result.name} saved successfully.`;
      await loadInventory(); await loadWorkspace();
    } catch (error) { $("inventory-message").textContent = `Item not saved: ${error.message}`; }
    finally { button.disabled = false; }
  });

  // Settings are account-scoped and saved in the signed-in farmer database.
  let settingsState = {};
  function applyTheme(theme) {
    const chosen = theme === "system" ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : theme;
    document.documentElement.dataset.theme = chosen;
  }
  function setValue(id, value) { const field = $(id); if (field && value !== undefined && value !== null) { if (field.type === "checkbox") field.checked = Boolean(value); else field.value = value; } }
  function getValue(id) { const field = $(id); return field ? (field.type === "checkbox" ? field.checked : field.value) : undefined; }
  async function loadSettings() {
    try {
      settingsState = await request("/settings");
      const mapping = {
        "setting-farm-type":"farm_type", "setting-farm-unit":"farm_unit", "weather-county":"weather_county", "weather-area":"weather_area", "weather-rainfall-unit":"rainfall_unit", "weather-alerts":"weather_alerts", "notify-reminders":"in_app_reminders", "notify-stock":"low_stock_alerts", "ai-response-style":"response_style", "save-ai-history":"save_ai_history", "setting-language":"language", "setting-region":"region", "setting-timezone":"timezone", "setting-theme":"theme", "setting-compact":"compact_layout"
      };
      Object.entries(mapping).forEach(([id,key]) => setValue(id, settingsState[key]));
      if ($("language")) $("language").value = settingsState.language || "English";
      if ($("diagnose-language")) $("diagnose-language").value = settingsState.language || "English";
      applyTheme(settingsState.theme || "system");
      if (window.setFarmUnit) window.setFarmUnit(settingsState.farm_unit || "acres");
      document.body.classList.toggle("compact-layout", Boolean(settingsState.compact_layout));
    } catch (error) { $("settings-message").textContent = `Settings could not be loaded: ${error.message}`; }
  }
  async function loadAccountSettings() {
    try {
      const account = await request("/account"); setValue("account-full-name", account.full_name); setValue("account-email-value", account.email);
    } catch (error) { $("account-settings-message").textContent = error.message; }
  }
  async function persistSettings(changes, message = "Settings saved successfully.") {
    settingsState = { ...settingsState, ...changes };
    try {
      const result = await request("/settings", { method: "PUT", body: JSON.stringify(settingsState) });
      settingsState = result.settings; $("settings-message").textContent = result.message || message; applyTheme(settingsState.theme);
    } catch (error) { $("settings-message").textContent = `Settings not saved: ${error.message}`; return false; }
  }
  $("farm-settings-form")?.addEventListener("submit", async (event) => { event.preventDefault(); const unit=getValue("setting-farm-unit"); const saved=await persistSettings({ farm_type:getValue("setting-farm-type"), farm_unit:unit }); if (saved !== false && window.setFarmUnit) window.setFarmUnit(unit); });
  $("weather-settings-form")?.addEventListener("submit", async (event) => { event.preventDefault(); await persistSettings({ weather_county:getValue("weather-county"), weather_area:getValue("weather-area"), rainfall_unit:getValue("weather-rainfall-unit"), weather_alerts:getValue("weather-alerts") }); });
  $("notification-settings-form")?.addEventListener("submit", async (event) => { event.preventDefault(); await persistSettings({ in_app_reminders:getValue("notify-reminders"), low_stock_alerts:getValue("notify-stock") }); await loadWorkspace(); });
  $("ai-settings-form")?.addEventListener("submit", async (event) => { event.preventDefault(); await persistSettings({ response_style:getValue("ai-response-style"), save_ai_history:getValue("save-ai-history") }); });
  $("language-region-form")?.addEventListener("submit", async (event) => { event.preventDefault(); const language=getValue("setting-language"); await persistSettings({ language, region:getValue("setting-region"), timezone:getValue("setting-timezone") }); if ($("language")) $("language").value=language; if ($("diagnose-language")) $("diagnose-language").value=language; });
  $("appearance-settings-form")?.addEventListener("submit", async (event) => { event.preventDefault(); const theme=getValue("setting-theme"); applyTheme(theme); await persistSettings({ theme, compact_layout:getValue("setting-compact") }); document.body.classList.toggle("compact-layout", Boolean(settingsState.compact_layout)); });
  $("setting-theme")?.addEventListener("change", () => applyTheme(getValue("setting-theme")));
  $("account-settings-form")?.addEventListener("submit", async (event) => { event.preventDefault(); try { const data=await request("/account", { method:"PATCH", body:JSON.stringify({ full_name:getValue("account-full-name") }) }); $("account-settings-message").textContent=data.message; $("account-name").textContent=data.full_name; } catch (error) { $("account-settings-message").textContent=error.message; } });
  $("password-change-form")?.addEventListener("submit", async (event) => { event.preventDefault(); const form=event.currentTarget; const current=getValue("current-password"), next=getValue("new-password"), confirm=getValue("confirm-new-password"); if (next !== confirm) { $("password-change-message").textContent="The new passwords do not match."; return; } if (!/[A-Za-z]/.test(next) || !/[0-9]/.test(next)) { $("password-change-message").textContent="Use at least one letter and one number."; return; } try { const data=await request("/account/password", { method:"POST", body:JSON.stringify({ current_password:current, new_password:next }) }); $("password-change-message").textContent=data.message; form.reset(); window.location.reload(); } catch (error) { $("password-change-message").textContent=error.message; } });
  loadAccountSettings(); loadSettings(); syncCommunityReportType();

  // Local estimate only; the farmer supplies all values.
  function calculateEstimate(event) {
    if (event) event.preventDefault();
    const qty = Math.max(0, Number($("calc-quantity").value) || 0);
    const price = Math.max(0, Number($("calc-price").value) || 0);
    const costs = Math.max(0, Number($("calc-cost").value) || 0);
    const revenue = qty * price; const surplus = revenue - costs; const margin = revenue > 0 ? surplus / revenue * 100 : 0;
    const cards = $("calculator-result"); cards.replaceChildren(
      metricCard(`KES ${revenue.toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, "Estimated revenue"),
      metricCard(`KES ${surplus.toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, "Estimated surplus / loss"),
      metricCard(`${margin.toFixed(1)}%`, "Estimated margin")
    );
  }
  $("farm-calculator-form")?.addEventListener("submit", calculateEstimate);
  ["calc-quantity","calc-price","calc-cost"].forEach((id) => $(id)?.addEventListener("input", calculateEstimate));

  // System status and user-initiated spoken feedback.
  async function loadSystemStatus() {
    const panel = $("system-status");
    try {
      const [health, knowledge] = await Promise.all([request("/health"), request("/knowledge/status")]);
      const providerSummary = `Provider: ${health.provider} · Model: ${health.model || "not configured"} · Credentials: ${health.api_key_configured ? "configured" : "not configured"}`;
      if ($("ai-provider-info")) $("ai-provider-info").textContent = providerSummary;
      panel.replaceChildren(
        node("p", `Backend: ${health.status} · Provider: ${health.provider} · Model: ${health.model || "not configured"}`),
        node("p", `AI credentials configured: ${health.api_key_configured ? "Yes" : "No"}`),
        node("p", `Crop classifier configured: ${health.classifier_configured ? "Yes" : "No"}`),
        node("p", `Reviewed knowledge excerpts: ${knowledge.document_count} · Retrieval: ${knowledge.retrieval}`),
        node("p", `Demo mode: ${health.demo_mode ? "ON — scripted sample responses only" : "OFF — configured AI provider is used"}`)
      );
      if (health.demo_mode) panel.append(node("p", "DEMO MODE IS ACTIVE. Do not use sample responses to make real farm decisions.", "demo-warning"));
    } catch (error) { panel.replaceChildren(node("p", `Could not read system status: ${error.message}`)); }
  }
  $("speak-answer-button")?.addEventListener("click", () => {
    const status = $("speech-output-status");
    if (!window.speechSynthesis || typeof SpeechSynthesisUtterance === "undefined") { status.textContent = "Spoken feedback is not supported in this browser. Read the answer on screen."; return; }
    const text = $("answer-content")?.textContent?.trim();
    if (!text) { status.textContent = "There is no answer to read yet."; return; }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = $("language")?.value === "Kiswahili" ? "sw-KE" : "en-KE";
    utterance.onstart = () => { status.textContent = "Reading the answer aloud…"; };
    utterance.onend = () => { status.textContent = "Finished reading the answer."; };
    utterance.onerror = () => { status.textContent = "The browser could not play spoken feedback. You can still read the answer on screen."; };
    window.speechSynthesis.speak(utterance);
  });

  // Supervisor view: server-side token is required. Do not persist it in local storage.
  $("supervisor-form")?.addEventListener("submit", async (event) => {
    event.preventDefault(); const token = $("supervisor-token").value;
    const message = $("supervisor-message"); const result = $("supervisor-results");
    result.replaceChildren(); message.textContent = "Checking access…";
    try {
      const data = await request("/supervisor/overview", { headers: { "X-Supervisor-Token": token } });
      message.textContent = data.note;
      result.append(metricCard(data.cases, "Recorded cases"), metricCard(data.pending_actions, "Pending actions"), metricCard(data.low_stock_items, "Low-stock items"), metricCard(data.community_reports_pending_review, "Community reports"));
      const statuses = node("section", null, "workspace-panel"); statuses.append(node("h3", "Case status summary"));
      data.cases_by_status.forEach((row) => statuses.append(node("p", `${row.status}: ${row.count}`)));
      const crops = node("section", null, "workspace-panel"); crops.append(node("h3", "Cases by crop"));
      data.cases_by_crop.forEach((row) => crops.append(node("p", `${row.crop}: ${row.count}`)));
      result.append(statuses, crops);
      const recent = node("section", null, "workspace-panel"); recent.append(node("h3", "Recent cases"));
      data.recent_cases.forEach((item) => recent.append(node("p", `${item.case_ref} · ${item.crop} · ${item.status}`)));
      result.append(recent);
    } catch (error) { message.textContent = `Supervisor view unavailable: ${error.message}`; }
    finally { $("supervisor-token").value = ""; }
  });

  // Kick off the new panels independently; failures in one panel do not block others.
  loadWorkspace(); loadLearning(); loadCommunity(); loadReferralCases(); loadReferrals(); loadInventory(); loadSystemStatus(); calculateEstimate();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) loadWorkspace(); });
})();

});
