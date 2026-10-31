window.MKULIMA_AUTH_READY.then((authenticated) => {
  if (!authenticated) return;
const API_BASE = window.location.port === "5500" ? `http://${window.location.hostname}:8000` : "";
const questionForm = document.getElementById("question-form");
const questionInput = document.getElementById("question");
const languageSelect = document.getElementById("language");
const askButton = document.getElementById("ask-button");
const errorMessage = document.getElementById("error-message");
const answerSection = document.getElementById("answer-section");
const answerContent = document.getElementById("answer-content");
const voiceButton = document.getElementById("voice-button");
const voiceStatus = document.getElementById("voice-status");
const profileForm = document.getElementById("farm-profile-form");
const profileMessage = document.getElementById("profile-message");

let profileFarmUnit = "acres";
let lastSavedFarmProfile = {};

function setFarmUnit(unit = "acres") {
  profileFarmUnit = unit === "hectares" ? "hectares" : "acres";
  const label = document.getElementById("farm-size-label");
  if (label) label.textContent = `Farm size (${profileFarmUnit})`;
  if (lastSavedFarmProfile && lastSavedFarmProfile.saved) renderSavedProfile(lastSavedFarmProfile);
}
window.setFarmUnit = setFarmUnit;

function getFarmProfile() {
  const value = (id) => document.getElementById(id)?.value.trim() || "";
  return { farmer_name:value("farmer-name"), county:value("county"), sub_county:value("sub-county"), main_crop:value("main-crop"), farm_size:value("farm-size") };
}
function setFarmProfile(profile = {}) {
  lastSavedFarmProfile = { ...profile };
  const mapping = { farmer_name:"farmer-name", county:"county", sub_county:"sub-county", main_crop:"main-crop", farm_size:"farm-size" };
  Object.entries(mapping).forEach(([key,id]) => { const el=document.getElementById(id); if(el) el.value=profile[key] || ""; });
  renderSavedProfile(profile);
}
function renderSavedProfile(profile = {}) {
  const card = document.getElementById("profile-saved-card");
  const details = document.getElementById("profile-saved-details");
  if (!card || !details) return;
  details.replaceChildren();
  if (!profile.saved) { card.hidden = true; return; }
  const rows = [
    ["Farmer name", profile.farmer_name], ["County", profile.county],
    ["Sub-county / area", profile.sub_county], ["Main crop", profile.main_crop],
    ["Farm size", profile.farm_size ? `${profile.farm_size} ${profileFarmUnit}` : "Not provided"]
  ];
  rows.forEach(([label, value]) => {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt"); term.textContent = label;
    const description = document.createElement("dd"); description.textContent = value || "Not provided";
    wrapper.append(term, description); details.append(wrapper);
  });
  const updated = document.getElementById("profile-saved-date");
  if (updated) updated.textContent = profile.updated_at ? `Last saved ${new Date(profile.updated_at).toLocaleString()}` : "Your details are saved to your account.";
  card.hidden = false;
}
function showError(message) { errorMessage.textContent=message; errorMessage.hidden=false; }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
async function api(path, options={}) {
  const headers = { ...(options.headers || {}) };
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (options.body && !isFormData && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const response = await fetch(`${API_BASE}${path}`, { ...options, credentials: API_BASE ? "include" : "same-origin", headers });
  let data={}; try { data=await response.json(); } catch (_) {}
  if(!response.ok) throw new Error(typeof data.detail==="string" ? data.detail : `Request failed (${response.status})`);
  return data;
}

// Load and save the signed-in farmer's own profile.
(async function loadProfile(){
  try {
    const profile = await api("/profile");
    setFarmProfile(profile);
    if (profile.saved) profileMessage.textContent = "Your saved farm details are shown below. You can edit them at any time.";
  } catch(error){ profileMessage.textContent=`Could not load your farm profile: ${error.message}`; }
})();
profileForm.addEventListener("submit", async (event)=>{
  event.preventDefault();
  const button=document.getElementById("save-profile-button");
  button.disabled=true; button.textContent="Saving…";
  profileMessage.className = "form-feedback";
  try {
    const result=await api("/profile",{method:"PUT",body:JSON.stringify(getFarmProfile())});
    setFarmProfile(result.profile);
    profileMessage.textContent = "✓ Your farm profile has been saved successfully. Your details are now available in this account.";
    profileMessage.classList.add("success");
    button.textContent = "Saved ✓";
  }
  catch(error){ profileMessage.textContent=`Profile was not saved: ${error.message}`; profileMessage.classList.add("error"); }
  finally { button.disabled=false; if (button.textContent !== "Saved ✓") button.textContent="Save Farm Profile"; }
});
document.getElementById("edit-profile-button")?.addEventListener("click", () => {
  document.getElementById("farm-profile-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
  document.getElementById("farmer-name")?.focus({ preventScroll: true });
});

// Browser speech recognition: optional, browser-dependent capability.
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition=null, isListening=false;
if(!SpeechRecognition){ voiceButton.disabled=true; voiceStatus.textContent="Voice input is not supported in this browser. Please type your question."; }
else voiceButton.addEventListener("click",()=>{
  if(isListening) return;
  recognition=new SpeechRecognition(); recognition.lang=languageSelect.value==="Kiswahili"?"sw-KE":"en-KE"; recognition.interimResults=false; recognition.maxAlternatives=1;
  recognition.onstart=()=>{isListening=true;voiceButton.disabled=true;voiceButton.textContent="🎙️ Listening…";voiceStatus.textContent="Listening now. Speak clearly.";};
  recognition.onresult=(event)=>{const transcript=event.results?.[0]?.[0]?.transcript?.trim(); if(transcript){questionInput.value=transcript;questionInput.focus();voiceStatus.textContent="Speech captured. Review before submitting.";}else voiceStatus.textContent="No speech recognized. Try again or type.";};
  recognition.onerror=(event)=>{const messages={"not-allowed":"Microphone permission denied. Allow microphone access.","no-speech":"No speech detected. Try again.","network":"Speech recognition network error. Try typing.","audio-capture":"No working microphone detected.","language-not-supported":"This speech language is unsupported. Try typing."};voiceStatus.textContent=messages[event.error]||"Voice input failed. Try typing your question.";};
  recognition.onend=()=>{isListening=false;voiceButton.disabled=false;voiceButton.textContent="🎙️ Speak your question";};
  try{voiceStatus.textContent="Requesting microphone access…";recognition.start();}catch(error){isListening=false;voiceButton.disabled=false;voiceButton.textContent="🎙️ Speak your question";voiceStatus.textContent="Could not start voice input. Try again.";}
});

questionForm.addEventListener("submit",async(event)=>{
  event.preventDefault(); const question=questionInput.value.trim(), language=languageSelect.value;
  if(question.length<3){showError("Please enter a farming question with at least 3 characters.");return;}
  errorMessage.hidden=true;answerSection.hidden=true;answerContent.replaceChildren();askButton.disabled=true;askButton.textContent="Getting farming guidance…";
  try{
    const data=await api("/ask",{method:"POST",body:JSON.stringify({question,language,farm_profile:getFarmProfile()})});
    if(!data.answer) throw new Error("The AI returned an empty answer.");
    const markdown=window.marked?marked.parse(data.answer):escapeHtml(data.answer).replace(/\n/g,"<br>");
    answerContent.innerHTML=window.DOMPurify?DOMPurify.sanitize(markdown):escapeHtml(data.answer).replace(/\n/g,"<br>");
    if(Array.isArray(data.sources)&&data.sources.length){const sourceBox=document.createElement("div");sourceBox.className="answer-sources";const heading=document.createElement("h4");heading.textContent="Agricultural reference organisations";sourceBox.append(heading);const ul=document.createElement("ul");data.sources.forEach(source=>{const li=document.createElement("li"),a=document.createElement("a");a.href=source.url;a.textContent=source.title;a.target="_blank";a.rel="noopener noreferrer";li.append(a);ul.append(li);});sourceBox.append(ul);answerContent.append(sourceBox);}
    answerSection.hidden=false; await loadHistory();
  }catch(error){showError(error.message||"Could not connect to the backend. Confirm FastAPI is running.");}
  finally{askButton.disabled=false;askButton.textContent="Ask ShambaSense AI";}
});

document.querySelectorAll(".topic-card").forEach(button=>button.addEventListener("click",()=>{questionInput.value=button.dataset.question||"";if(window.showAppView)window.showAppView("ask-ai");questionInput.focus();}));

// Persistent question history.
async function loadHistory(){
  const list=document.getElementById("history-list");
  try{const rows=await api("/history");list.replaceChildren();if(!rows.length){list.innerHTML="<p>No questions saved yet. Ask ShambaSense AI to begin.</p>";return;}
    rows.forEach(row=>{const article=document.createElement("article");article.className="history-item";const h=document.createElement("h3");h.textContent=row.question;const meta=document.createElement("p");meta.className="history-meta";meta.textContent=`${row.language} · ${new Date(row.created_at).toLocaleString()}`;const answer=document.createElement("div");answer.className="history-answer";const parsed=window.marked?marked.parse(row.answer):escapeHtml(row.answer);answer.innerHTML=window.DOMPurify?DOMPurify.sanitize(parsed):escapeHtml(row.answer);article.append(h,meta,answer);list.append(article);});
  }catch(error){list.innerHTML=`<p>History unavailable: ${escapeHtml(error.message)}</p>`;}
}
document.getElementById("refresh-history")?.addEventListener("click",loadHistory);
document.getElementById("clear-history")?.addEventListener("click",async()=>{if(!confirm("Clear all saved question history?"))return;try{await api("/history",{method:"DELETE"});await loadHistory();}catch(error){showError(error.message);}});

// In-app reminders are persisted, but do not send OS/email notifications.
async function loadReminders(){
 const list=document.getElementById("reminder-list");try{const rows=await api("/reminders");list.replaceChildren();if(!rows.length){list.innerHTML="<p>No reminders yet.</p>";return;}
 rows.forEach(row=>{const article=document.createElement("article");article.className=`reminder-item${row.completed?" completed":""}`;const h=document.createElement("h3");h.textContent=row.title;const when=document.createElement("p");when.textContent=new Date(row.due_at).toLocaleString();const notes=document.createElement("p");notes.textContent=row.notes||"";if(row.case_ref){const linked=document.createElement("p");linked.textContent=`Linked case: ${row.case_ref} · ${row.case_title||"Farm case"}`;linked.className="case-muted";article.append(linked);}const complete=document.createElement("button");complete.type="button";complete.textContent=row.completed?"Mark incomplete":"Mark complete";complete.addEventListener("click",async()=>{try{await api(`/reminders/${row.id}/complete`,{method:"PATCH"});await loadReminders();if(activeCaseId)await openCase(activeCaseId);}catch(error){showError(error.message);}});const del=document.createElement("button");del.type="button";del.className="secondary-button";del.textContent="Delete";del.addEventListener("click",async()=>{try{await api(`/reminders/${row.id}`,{method:"DELETE"});await loadReminders();}catch(error){showError(error.message);}});article.append(h,when,notes,complete,del);list.append(article);});
 }catch(error){list.innerHTML=`<p>Reminders unavailable: ${escapeHtml(error.message)}</p>`;}}
document.getElementById("reminder-form")?.addEventListener("submit",async(event)=>{event.preventDefault();const form=event.currentTarget;const title=document.getElementById("reminder-title").value.trim(),due=document.getElementById("reminder-due").value,notes=document.getElementById("reminder-notes").value.trim();if(!title||!due)return;try{const result=await api("/reminders",{method:"POST",body:JSON.stringify({title,due_at:new Date(due).toISOString(),notes})});form.reset();alert(result.message);await loadReminders();}catch(error){showError(error.message);}});
// Photo diagnosis: image -> /diagnose (classifier + reviewed knowledge + explanation).
const diagnoseForm=document.getElementById("diagnose-form");
const diagnoseImage=document.getElementById("diagnose-image");
const diagnosePreview=document.getElementById("diagnose-preview");
const diagnoseButton=document.getElementById("diagnose-button");
const diagnoseError=document.getElementById("diagnose-error");
const diagnoseResult=document.getElementById("diagnose-result");
const MAX_UPLOAD_BYTES=5*1024*1024;

// Shrink big phone photos before upload (saves mobile data); falls back to the original file.
async function prepareImage(file){
  try{
    const bitmap=await createImageBitmap(file);
    const scale=Math.min(1,1280/Math.max(bitmap.width,bitmap.height));
    if(scale===1&&file.size<=MAX_UPLOAD_BYTES) return file;
    const canvas=document.createElement("canvas"); canvas.width=Math.round(bitmap.width*scale); canvas.height=Math.round(bitmap.height*scale);
    canvas.getContext("2d").drawImage(bitmap,0,0,canvas.width,canvas.height);
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,"image/jpeg",0.85));
    return blob||file;
  }catch(_){return file;}
}
diagnoseImage.addEventListener("change",()=>{
  const file=diagnoseImage.files[0]; diagnoseError.hidden=true;
  if(diagnosePreview.src.startsWith("blob:")) URL.revokeObjectURL(diagnosePreview.src);
  if(!file){diagnosePreview.hidden=true;return;}
  diagnosePreview.src=URL.createObjectURL(file); diagnosePreview.hidden=false;
});
diagnoseForm.addEventListener("submit",async(event)=>{
  event.preventDefault();
  const file=diagnoseImage.files[0];
  diagnoseError.hidden=true; diagnoseResult.hidden=true;
  if(!file){diagnoseError.textContent="Please choose a crop photo first.";diagnoseError.hidden=false;return;}
  diagnoseButton.disabled=true; diagnoseButton.textContent="Analysing photo…";
  try{
    const upload=await prepareImage(file);
    if(upload.size>MAX_UPLOAD_BYTES) throw new Error("The photo is larger than 5 MB. Please choose a smaller one.");
    const form=new FormData();
    form.append("image",upload,"crop-photo."+(upload.type==="image/png"?"png":upload.type==="image/webp"?"webp":"jpg"));
    form.append("language",document.getElementById("diagnose-language").value);
    const note=document.getElementById("diagnose-note").value.trim(); if(note) form.append("note",note);
    const response=await fetch(`${API_BASE}/diagnose`,{method:"POST",body:form,credentials:API_BASE?"include":"same-origin"}); // browser sets the multipart header
    let data={}; try{data=await response.json();}catch(_){}
    if(!response.ok) throw new Error(typeof data.detail==="string"?data.detail:`Request failed (${response.status})`);
    renderDiagnosis(data); await loadHistory();
  }catch(error){diagnoseError.textContent=error.message||"Could not connect to the backend. Confirm FastAPI is running.";diagnoseError.hidden=false;}
  finally{diagnoseButton.disabled=false;diagnoseButton.textContent="Analyse photo";}
});
function renderDiagnosis(data){
  const status=document.getElementById("diagnose-status");
  status.textContent=data.status==="confident"
    ?"The photo matches the suggestions below. Confirm the symptoms on the plant before acting."
    :"The photo could not be identified reliably. Try a clearer, closer photo of one affected leaf in good light.";
  const list=document.getElementById("diagnose-predictions"); list.replaceChildren();
  (data.predictions||[]).forEach(item=>{const li=document.createElement("li");li.textContent=`${item.display_label} — ${(item.confidence*100).toFixed(0)}%`;list.append(li);});
  const warning=document.getElementById("diagnose-warning");
  warning.textContent=data.warning||""; warning.hidden=!data.warning;
  const visionNote=document.getElementById("diagnose-vision-note");
  visionNote.textContent=data.vision_used?"Your photo was also viewed by the AI model (hosted by Hugging Face) to describe visible symptoms.":""; visionNote.hidden=!data.vision_used;
  const answer=document.getElementById("diagnose-answer"); answer.replaceChildren();
  if(data.answer){
    const markdown=window.marked?marked.parse(data.answer):escapeHtml(data.answer).replace(/\n/g,"<br>");
    answer.innerHTML=window.DOMPurify?DOMPurify.sanitize(markdown):escapeHtml(data.answer).replace(/\n/g,"<br>");
  }
  if(Array.isArray(data.sources)&&data.sources.length){
    const box=document.createElement("div"); box.className="answer-sources";
    const heading=document.createElement("h4"); heading.textContent="Reviewed sources used"; box.append(heading);
    data.sources.forEach(src=>{const a=document.createElement("a");a.href=src.url;a.target="_blank";a.rel="noopener noreferrer";a.textContent=src.title;const p=document.createElement("p");p.append(a);box.append(p);});
    answer.append(box);
  }
  document.getElementById("diagnose-disclaimer").textContent=data.disclaimer||"";
  diagnoseResult.hidden=false; diagnoseResult.scrollIntoView({behavior:"smooth"});
}

loadHistory();loadReminders();

// Farm Problem Case Management and FarmAction.
// This local-demo UI uses the existing API/database; it is not a multi-user account system.
let activeCaseId = null;
const farmCaseForm = document.getElementById("farm-case-form");
const caseList = document.getElementById("case-list");
const caseDetail = document.getElementById("case-detail");
const caseDetailContent = document.getElementById("case-detail-content");
const caseFormMessage = document.getElementById("case-form-message");
const caseActionMessage = document.getElementById("case-action-message");

function addTextElement(parent, tag, text, className = "") {
  const element = document.createElement(tag);
  element.textContent = text ?? "";
  if (className) element.className = className;
  parent.append(element);
  return element;
}

function addSafeMarkdown(parent, markdown) {
  const node = document.createElement("div");
  const parsed = window.marked ? marked.parse(markdown || "") : escapeHtml(markdown || "").replace(/\n/g, "<br>");
  node.innerHTML = window.DOMPurify ? DOMPurify.sanitize(parsed) : escapeHtml(markdown || "").replace(/\n/g, "<br>");
  parent.append(node);
}

async function loadCases() {
  try {
    const rows = await api("/cases");
    caseList.replaceChildren();
    if (!rows.length) {
      addTextElement(caseList, "p", "No farm cases yet. Record a challenge above to start tracking it.", "case-empty");
      return;
    }
    rows.forEach((row) => {
      const article = document.createElement("article");
      article.className = "case-item";
      const title = addTextElement(article, "h4", row.title);
      const displaySubject = row.case_type === "livestock" ? `${row.species || "Livestock"} · ${row.issue_category || "Animal concern"}` : `${row.crop} · ${row.issue_category || "Crop concern"}`;
      const meta = addTextElement(article, "p", `${row.case_ref} · ${displaySubject} · Updated ${new Date(row.updated_at).toLocaleString()}`);
      meta.className = "case-muted";
      addTextElement(article, "p", row.problem);
      addTextElement(article, "span", row.status, "case-status");
      addTextElement(article, "p", `${row.observation_count} observations · ${row.assessment_count} AI assessments · ${row.action_count} FarmActions`);
      const open = document.createElement("button");
      open.type = "button";
      open.textContent = "Open case";
      open.setAttribute("aria-label", `Open case ${row.case_ref}: ${row.title}`);
      open.addEventListener("click", () => openCase(row.id));
      article.append(open);
      caseList.append(article);
    });
  } catch (error) {
    caseList.replaceChildren();
    addTextElement(caseList, "p", `Farm cases unavailable: ${error.message}`, "case-empty");
  }
}

function renderCaseDetail(data) {
  activeCaseId = data.id;
  document.getElementById("case-detail-title").textContent = `${data.case_ref} · ${data.title}`;
  caseDetailContent.replaceChildren();

  const summary = document.createElement("div");
  summary.className = "case-detail-summary";
  addTextElement(summary, "span", data.status, "case-status");
  if (data.case_type === "livestock") {
    addTextElement(summary, "p", `Animal: ${data.species || "Not specified"}`);
    if (data.animal_group) addTextElement(summary, "p", `Group / breed: ${data.animal_group}`);
    if (data.animal_age_group) addTextElement(summary, "p", `Age group: ${data.animal_age_group}`);
    if (data.animal_count !== null && data.animal_count !== undefined) addTextElement(summary, "p", `Animals affected: ${data.animal_count}`);
    addTextElement(summary, "p", `Concern: ${data.issue_category || "Animal health"}`);
  } else {
    addTextElement(summary, "p", `Crop: ${data.crop}`);
    addTextElement(summary, "p", `Concern: ${data.issue_category || "Crop concern"}`);
  }
  addTextElement(summary, "p", `Problem: ${data.problem}`);
  if (data.symptoms) addTextElement(summary, "p", `Symptoms: ${data.symptoms}`);
  if (data.onset_date) addTextElement(summary, "p", `First noticed: ${data.onset_date}`);
  if (data.crop_stage) addTextElement(summary, "p", `Growth stage: ${data.crop_stage}`);
  if (data.notes) addTextElement(summary, "p", `Farm notes: ${data.notes}`);
  addTextElement(summary, "p", `Created ${new Date(data.created_at).toLocaleString()} · Updated ${new Date(data.updated_at).toLocaleString()}`, "case-muted");

  const statusLabel = addTextElement(summary, "label", "Update case status");
  const statusSelect = document.createElement("select");
  statusSelect.id = "case-status-select";
  ["open", "monitoring", "resolved", "referred"].forEach((status) => {
    const option = document.createElement("option"); option.value = status; option.textContent = status[0].toUpperCase() + status.slice(1); statusSelect.append(option);
  });
  statusSelect.value = data.status;
  statusLabel.htmlFor = statusSelect.id;
  summary.append(statusSelect);
  const updateStatus = document.createElement("button");
  updateStatus.type = "button"; updateStatus.textContent = "Save status";
  updateStatus.addEventListener("click", async () => {
    try {
      const updated = await api(`/cases/${activeCaseId}/status`, { method: "PATCH", body: JSON.stringify({ status: statusSelect.value }) });
      renderCaseDetail(updated); await loadCases(); await loadLivestockCases();
      caseActionMessage.textContent = "Case status updated.";
    } catch (error) { caseActionMessage.textContent = error.message; }
  });
  summary.append(updateStatus);
  caseDetailContent.append(summary);

  const timeline = document.createElement("section");
  addTextElement(timeline, "h4", `Case activity timeline (${(data.events || []).length})`);
  if (!(data.events || []).length) addTextElement(timeline, "p", "No activity recorded yet.", "case-muted");
  (data.events || []).forEach((event) => {
    const card = document.createElement("article"); card.className = "case-observation";
    addTextElement(card, "strong", event.event_type.replaceAll("_", " "));
    addTextElement(card, "p", event.description);
    addTextElement(card, "small", new Date(event.created_at).toLocaleString(), "case-muted");
    timeline.append(card);
  });
  caseDetailContent.append(timeline);

  const observations = document.createElement("section");
  addTextElement(observations, "h4", `Follow-up observations (${data.observations.length})`);
  if (!data.observations.length) addTextElement(observations, "p", "No follow-up observations recorded yet.", "case-muted");
  data.observations.forEach((item) => {
    const card = document.createElement("article"); card.className = "case-observation";
    addTextElement(card, "p", item.observation);
    addTextElement(card, "small", `${item.observed_at ? new Date(item.observed_at).toLocaleString() + " · " : ""}Saved ${new Date(item.created_at).toLocaleString()}`, "case-muted");
    observations.append(card);
  });
  caseDetailContent.append(observations);

  const assessments = document.createElement("section");
  addTextElement(assessments, "h4", `AI assessments (${data.assessments.length})`);
  if (!data.assessments.length) addTextElement(assessments, "p", "No AI assessment has been requested for this case.", "case-muted");
  data.assessments.forEach((item) => {
    const card = document.createElement("article"); card.className = "case-assessment";
    addTextElement(card, "small", `${item.language} · ${new Date(item.created_at).toLocaleString()}`, "case-muted");
    addSafeMarkdown(card, item.assessment);
    if (item.sources?.length) {
      const sourceTitle = addTextElement(card, "strong", "Reviewed source excerpts used:");
      const ul = document.createElement("ul");
      item.sources.forEach((source) => {
        const li = document.createElement("li"); const link = document.createElement("a");
        link.href = source.url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = source.title;
        li.append(link); ul.append(li);
      });
      card.append(ul);
    }
    assessments.append(card);
  });
  caseDetailContent.append(assessments);

  const actions = document.createElement("section");
  addTextElement(actions, "h4", `FarmActions (${data.actions.length})`);
  if (!data.actions.length) addTextElement(actions, "p", "No tasks linked to this case yet.", "case-muted");
  data.actions.forEach((item) => {
    const card = document.createElement("article"); card.className = "case-action";
    addTextElement(card, "p", `${item.completed ? "✓ Completed" : "○ Pending"} · ${item.title}`);
    addTextElement(card, "small", `Due ${new Date(item.due_at).toLocaleString()}` + (item.notes ? ` · ${item.notes}` : ""), "case-muted");
    actions.append(card);
  });
  caseDetailContent.append(actions);

  const mediaSection = document.createElement("section");
  addTextElement(mediaSection, "h4", "Farm videos and observations");
  addTextElement(mediaSection, "p", "Attach a short MP4, MOV or WebM clip (maximum 20 MB). A 15–30 second clip is usually enough. Videos are stored with this local case; they are not automatically analysed by AI.", "case-muted");
  const uploadForm = document.createElement("form"); uploadForm.className = "case-video-upload-form";
  const fileLabel = addTextElement(uploadForm, "label", "Choose a short video");
  const fileInput = document.createElement("input"); fileInput.type = "file"; fileInput.accept = "video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm"; fileInput.required = true;
  fileLabel.htmlFor = `case-video-${data.id}`; fileInput.id = fileLabel.htmlFor;
  const descriptionInput = document.createElement("input"); descriptionInput.maxLength = 300; descriptionInput.placeholder = "Optional caption: what should the adviser notice?"; descriptionInput.setAttribute("aria-label", "Optional video caption");
  const uploadButton = document.createElement("button"); uploadButton.type = "submit"; uploadButton.textContent = "Attach video to case";
  const uploadStatus = addTextElement(uploadForm, "p", "", "form-feedback"); uploadStatus.setAttribute("role", "status"); uploadStatus.setAttribute("aria-live", "polite");
  uploadForm.append(fileInput, descriptionInput, uploadButton);
  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = fileInput.files?.[0];
    if (!file) return;
    if (file.size > 20 * 1024 * 1024) { uploadStatus.textContent = "This video is larger than 20 MB. Choose a shorter clip."; return; }
    try {
      const duration = await new Promise((resolve, reject) => {
        const probe = document.createElement("video"); const objectUrl = URL.createObjectURL(file);
        const cleanup = () => { URL.revokeObjectURL(objectUrl); probe.removeAttribute("src"); probe.load(); };
        probe.preload = "metadata";
        probe.onloadedmetadata = () => { const value = probe.duration; cleanup(); resolve(value); };
        probe.onerror = () => { cleanup(); reject(new Error("The browser could not read this video. Try an MP4, MOV or WebM clip.")); };
        probe.src = objectUrl;
      });
      if (!Number.isFinite(duration) || duration <= 0) throw new Error("The selected video duration could not be confirmed.");
      if (duration > 60) throw new Error("Please choose a clip of 60 seconds or less. A 15–30 second clip is usually enough.");
    } catch (error) { uploadStatus.textContent = error.message; return; }
    const formData = new FormData(); formData.append("video", file); formData.append("description", descriptionInput.value.trim());
    uploadButton.disabled = true; uploadButton.textContent = "Uploading video…"; uploadStatus.textContent = "Uploading securely to your case…";
    try {
      const response = await api(`/cases/${data.id}/media/videos`, { method: "POST", body: formData });
      uploadStatus.textContent = response.message;
      const updated = await api(`/cases/${data.id}`); renderCaseDetail(updated); await loadCases();
    } catch (error) { uploadStatus.textContent = `Video not uploaded: ${error.message}`; }
    finally { uploadButton.disabled = false; uploadButton.textContent = "Attach video to case"; }
  });
  mediaSection.append(uploadForm);
  const mediaList = document.createElement("div"); mediaList.className = "case-media-list";
  if (!(data.media || []).length) addTextElement(mediaList, "p", "No videos attached to this case yet.", "case-muted");
  (data.media || []).forEach((media) => {
    const card = document.createElement("article"); card.className = "case-observation";
    addTextElement(card, "strong", media.original_name);
    if (media.description) addTextElement(card, "p", media.description);
    const video = document.createElement("video"); video.controls = true; video.preload = "metadata"; video.crossOrigin = "use-credentials"; video.src = `${API_BASE}/case-media/${media.id}`; video.className = "case-video-preview"; video.setAttribute("aria-label", `Video attachment ${media.original_name}`); card.append(video);
    addTextElement(card, "small", `${(media.file_size / (1024 * 1024)).toFixed(1)} MB · Added ${new Date(media.created_at).toLocaleString()}`, "case-muted");
    const remove = document.createElement("button"); remove.type = "button"; remove.className = "secondary-button"; remove.textContent = "Remove video";
    remove.addEventListener("click", async () => { if (!window.confirm("Remove this video from the case?")) return; try { await api(`/case-media/${media.id}`, { method: "DELETE" }); const updated = await api(`/cases/${data.id}`); renderCaseDetail(updated); } catch (error) { uploadStatus.textContent = error.message; } });
    card.append(remove); mediaList.append(card);
  });
  mediaSection.append(mediaList); caseDetailContent.append(mediaSection);
  caseDetail.hidden = false;
  caseDetail.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function openCase(caseId) {
  caseActionMessage.textContent = "Loading case…";
  try {
    const data = await api(`/cases/${caseId}`);
    renderCaseDetail(data);
    caseActionMessage.textContent = "";
  } catch (error) {
    caseActionMessage.textContent = `Could not open case: ${error.message}`;
  }
}

farmCaseForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.getElementById("create-case-button");
  button.disabled = true; button.textContent = "Saving case…";
  const payload = {
    crop: document.getElementById("case-crop").value.trim(),
    title: document.getElementById("case-title").value.trim(),
    problem: document.getElementById("case-problem").value.trim(),
    symptoms: document.getElementById("case-symptoms").value.trim() || null,
    onset_date: document.getElementById("case-onset").value || null,
    crop_stage: document.getElementById("case-stage").value.trim() || null,
    notes: document.getElementById("case-notes").value.trim() || null
  };
  try {
    const created = await api("/cases", { method: "POST", body: JSON.stringify(payload) });
    farmCaseForm.reset();
    caseFormMessage.textContent = `Case ${created.case_ref} saved. You can now add observations and request an assessment.`;
    await loadCases();
    window.dispatchEvent(new CustomEvent("mkb:cases-updated"));
    renderCaseDetail(created);
  } catch (error) {
    caseFormMessage.textContent = `Case was not saved: ${error.message}`;
  } finally {
    button.disabled = false; button.textContent = "Save farm case";
  }
});

document.getElementById("refresh-cases")?.addEventListener("click", loadCases);
document.getElementById("close-case-detail")?.addEventListener("click", () => { caseDetail.hidden = true; activeCaseId = null; });

async function loadLivestockCases() {
  const list = document.getElementById("livestock-case-list");
  if (!list) return;
  try {
    const rows = await api("/cases?case_type=livestock"); list.replaceChildren();
    if (!rows.length) { addTextElement(list, "p", "No animal care cases recorded yet.", "case-empty"); return; }
    rows.forEach((row) => {
      const card = document.createElement("article"); card.className = "case-item";
      addTextElement(card, "h4", row.title);
      addTextElement(card, "p", `${row.case_ref} · ${row.species || "Livestock"} · ${row.issue_category || "Animal concern"}`, "case-muted");
      addTextElement(card, "p", row.problem);
      addTextElement(card, "span", row.status, "case-status");
      const open = document.createElement("button"); open.type = "button"; open.textContent = "Open animal case"; open.addEventListener("click", () => openCase(row.id)); card.append(open); list.append(card);
    });
  } catch (error) { list.replaceChildren(); addTextElement(list, "p", `Livestock cases unavailable: ${error.message}`); }
}
document.getElementById("refresh-livestock-cases")?.addEventListener("click", loadLivestockCases);
document.getElementById("livestock-case-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget; const button = document.getElementById("livestock-save-button");
  const payload = {
    case_type: "livestock", species: document.getElementById("livestock-species").value,
    animal_group: document.getElementById("livestock-group").value.trim() || null,
    animal_age_group: document.getElementById("livestock-age").value || null,
    animal_count: document.getElementById("livestock-count").value === "" ? null : Number(document.getElementById("livestock-count").value),
    issue_category: document.getElementById("livestock-issue").value,
    title: document.getElementById("livestock-title").value.trim(),
    problem: document.getElementById("livestock-problem").value.trim(),
    symptoms: document.getElementById("livestock-symptoms").value.trim() || null,
    onset_date: document.getElementById("livestock-onset").value || null,
    notes: document.getElementById("livestock-notes").value.trim() || null
  };
  button.disabled = true; button.textContent = "Saving animal case…";
  try {
    const created = await api("/cases", { method: "POST", body: JSON.stringify(payload) });
    form.reset(); document.getElementById("livestock-message").textContent = `Animal case ${created.case_ref} saved. If the animal is seriously ill, contact a veterinary professional promptly.`;
    await loadLivestockCases(); await loadCases();
    window.dispatchEvent(new CustomEvent("mkb:cases-updated"));
    await openCase(created.id);
  } catch (error) { document.getElementById("livestock-message").textContent = `Animal case not saved: ${error.message}`; }
  finally { button.disabled = false; button.textContent = "Save animal care case"; }
});

document.getElementById("case-observation-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!activeCaseId) return;
  const field = document.getElementById("case-observation");
  try {
    const updated = await api(`/cases/${activeCaseId}/observations`, { method: "POST", body: JSON.stringify({ observation: field.value.trim(), observed_at: new Date().toISOString() }) });
    field.value = ""; renderCaseDetail(updated); await loadCases();
    caseActionMessage.textContent = "Follow-up observation saved.";
  } catch (error) { caseActionMessage.textContent = `Observation was not saved: ${error.message}`; }
});

document.getElementById("assess-case-button")?.addEventListener("click", async () => {
  if (!activeCaseId) return;
  const button = document.getElementById("assess-case-button");
  button.disabled = true; button.textContent = "Requesting assessment…";
  try {
    const updated = await api(`/cases/${activeCaseId}/assessments`, { method: "POST", body: JSON.stringify({ language: languageSelect.value }) });
    renderCaseDetail(updated); await loadCases();
    caseActionMessage.textContent = "Assessment saved to this case. Review it carefully before deciding what to do.";
  } catch (error) { caseActionMessage.textContent = `Assessment unavailable: ${error.message}`; }
  finally { button.disabled = false; button.textContent = "Request AI assessment"; }
});

document.getElementById("case-action-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!activeCaseId) return;
  const title = document.getElementById("case-action-title").value.trim();
  const due = document.getElementById("case-action-due").value;
  const notes = document.getElementById("case-action-notes").value.trim();
  if (!title || !due) return;
  try {
    await api(`/cases/${activeCaseId}/actions`, { method: "POST", body: JSON.stringify({ title, due_at: new Date(due).toISOString(), notes: notes || null }) });
    form.reset();
    const updated = await api(`/cases/${activeCaseId}`); renderCaseDetail(updated);
    await loadCases(); await loadReminders();
    caseActionMessage.textContent = "Farmer-approved task added to FarmAction and linked to this case.";
  } catch (error) { caseActionMessage.textContent = `Task was not saved: ${error.message}`; }
});

// Load recorded crop and livestock cases after the signed-in workspace initializes.
loadCases();
loadLivestockCases();

});
