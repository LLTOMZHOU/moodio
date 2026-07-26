const state = {
  now: null,
  currentTrackId: null,
  renderedPlaybackRef: null,
  chatMessages: [],
  streamingMessage: null,
  streamingTextNode: null,
  streamingFrame: null,
  pendingStreamText: "",
  conversationBefore: null,
  conversationHasMore: true,
  conversationLoading: false,
  isSpeaking: false,
  musicVolume: 1,
};

const byId = (id) => document.getElementById(id);

function setMessage(text) {
  byId("message").textContent = text;
}

function fadeMusicOut(duration = 800) {
  const audio = byId("music-audio");
  if (!audio || !audio.src) return;
  state.isSpeaking = true;
  const steps = 20;
  const stepTime = duration / steps;
  let step = 0;
  const fade = setInterval(() => {
    step++;
    const vol = Math.max(0, 1 - step / steps);
    audio.volume = vol * state.musicVolume;
    if (step >= steps) clearInterval(fade);
  }, stepTime);
}

function fadeMusicIn(duration = 800) {
  const audio = byId("music-audio");
  if (!audio || !audio.src) return;
  const steps = 20;
  const stepTime = duration / steps;
  let step = 0;
  const fade = setInterval(() => {
    step++;
    const vol = Math.min(1, step / steps);
    audio.volume = vol * state.musicVolume;
    if (step >= steps) {
      clearInterval(fade);
      state.isSpeaking = false;
    }
  }, stepTime);
}

function renderEmbed(track) {
  const audio = byId("music-audio");
  const openSource = byId("music-open-link");
  if (!track?.playback_ref?.startsWith("youtube:video:")) return;
  if (openSource) {
    openSource.hidden = !track.external_url;
    openSource.href = track.external_url || "#";
  }
  if (state.renderedPlaybackRef === track.playback_ref) return;
  state.renderedPlaybackRef = track.playback_ref;
  audio.src = `/api/music/stream/${encodeURIComponent(track.playback_ref)}`;
  audio.load();
  audio.play().then(() => setMessage("♪ playing")).catch(() => setMessage("Press Play to begin audio"));
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "--:--";
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function renderPlaybackProgress() {
  const audio = byId("music-audio");
  const progress = byId("playback-progress");
  const duration = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : null;
  progress.disabled = !duration;
  progress.max = String(Math.round(duration || 1000));
  const position = Math.min(Math.round(audio.currentTime || 0), Number(progress.max));
  progress.value = String(position);
  const railWidth = progress.clientWidth || 0;
  const ratio = duration ? position / Number(progress.max) : 0;
  const fillWidth = 8 + Math.max(0, railWidth - 16) * ratio;
  progress.style.setProperty("--playback-fill", `${fillWidth}px`);
  byId("playback-elapsed").textContent = formatTime(audio.currentTime || 0);
  byId("playback-duration").textContent = formatTime(duration);
}

// --- Station state rendering ---

function renderState(payload) {
  state.now = payload;
  state.currentTrackId = payload.now_playing.track_id;

  byId("station-status").textContent = payload.status;
  byId("voice-mode").checked = Boolean(payload.voice_mode);
  byId("track-title").textContent = payload.now_playing.title;
  byId("track-artist").textContent = `${payload.now_playing.artist} · ${payload.now_playing.album}`;

  renderEmbed(payload.now_playing);

  const queueList = byId("queue-list");
  queueList.innerHTML = "";
  if (!payload.queue.length) {
    const item = document.createElement("li");
    item.textContent = "Queue is clear";
    item.className = "empty";
    queueList.appendChild(item);
    return;
  }
  payload.queue.forEach((track, index) => queueList.appendChild(renderQueueItem(track, index)));
}

function renderQueueItem(track, index) {
  const item = document.createElement("li");
  const title = document.createElement("span");
  title.className = "queue-title";
  const isMusic = track.kind === "music";
  title.textContent = isMusic ? `${index + 1}. ${track.track.title}` : `↳ ${track.text}`;

  const meta = document.createElement("span");
  meta.className = "queue-meta";
  meta.textContent = isMusic
    ? `${track.track.artist} · ${track.track.album || "Unknown source"}`
    : track.reason;

  const badge = document.createElement("span");
  badge.className = "queue-badge";
  badge.textContent = isMusic ? (track.track.playback_ref?.startsWith("youtube:") ? "YT" : "music") : "talk";

  item.append(title, meta, badge);
  return item;
}

// --- Chat conversation view ---

function addChatMessage(role, text) {
  state.chatMessages.push({ role, text, time: new Date() });
  renderChat();
}

function isNearChatBottom(container) {
  return container.scrollHeight - container.scrollTop - container.clientHeight < 48;
}

function createChatBubble(msg, { streaming = false } = {}) {
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble chat-${msg.role}${streaming ? " is-streaming" : ""}`;

  const textEl = document.createElement("div");
  textEl.className = "chat-text";
  textEl.append(document.createTextNode(msg.text));

  const timeEl = document.createElement("div");
  timeEl.className = "chat-time";
  timeEl.textContent = streaming ? "live" : msg.time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  bubble.append(textEl, timeEl);
  return { bubble, textEl };
}

function clearStreamingMessage({ render = false } = {}) {
  if (state.streamingFrame !== null) cancelAnimationFrame(state.streamingFrame);
  state.streamingFrame = null;
  state.pendingStreamText = "";
  state.streamingMessage = null;
  state.streamingTextNode = null;
  if (render) renderChat();
}

function flushStreamText() {
  state.streamingFrame = null;
  if (!state.streamingMessage || !state.streamingTextNode || !state.pendingStreamText) return;
  state.streamingTextNode.appendData(state.pendingStreamText);
  state.pendingStreamText = "";
}

function appendStreamDelta(delta) {
  if (!delta) return;
  const container = byId("chat-messages");
  const followStream = isNearChatBottom(container);
  if (!state.streamingMessage) {
    state.streamingMessage = { role: "moodio", text: "", time: new Date() };
    const { bubble, textEl } = createChatBubble(state.streamingMessage, { streaming: true });
    container.appendChild(bubble);
    state.streamingTextNode = textEl.firstChild;
  }
  state.streamingMessage.text += delta;
  state.pendingStreamText += delta;
  if (state.streamingFrame === null) state.streamingFrame = requestAnimationFrame(flushStreamText);
  if (followStream) container.scrollTop = container.scrollHeight;
}

function renderChat({ scrollToBottom = true } = {}) {
  const container = byId("chat-messages");
  container.innerHTML = "";
  for (const msg of state.chatMessages) {
    container.appendChild(createChatBubble(msg).bubble);
  }
  if (state.streamingMessage) {
    const { bubble, textEl } = createChatBubble(state.streamingMessage, { streaming: true });
    container.appendChild(bubble);
    state.streamingTextNode = textEl.firstChild;
  }
  if (scrollToBottom) container.scrollTop = container.scrollHeight;
}

function conversationMessage(item) {
  return {
    id: item.id,
    role: item.role === "listener" ? "user" : "moodio",
    text: item.text,
    time: new Date(item.at),
  };
}

function conversationMessageSaved(item) {
  const message = conversationMessage(item);
  if (message.role === "moodio" && state.streamingMessage) {
    clearStreamingMessage();
    state.chatMessages.push(message);
    renderChat();
    return;
  }
  if (!state.chatMessages.some((existing) => existing.id === message.id)) {
    state.chatMessages.push(message);
    renderChat();
  }
}

async function loadConversation({ older = false } = {}) {
  if (state.conversationLoading || (older && !state.conversationHasMore)) return;
  state.conversationLoading = true;
  const container = byId("chat-messages");
  const priorHeight = container.scrollHeight;
  const priorTop = container.scrollTop;
  try {
    const params = new URLSearchParams({ limit: "50" });
    if (older && state.conversationBefore !== null) params.set("before", String(state.conversationBefore));
    const response = await fetch(`/api/conversation?${params}`);
    if (!response.ok) throw new Error(await response.text());
    const page = await response.json();
    const messages = (page.items || []).map(conversationMessage);
    state.conversationBefore = page.next_before;
    state.conversationHasMore = Boolean(page.has_more);
    if (older) {
      state.chatMessages = [...messages, ...state.chatMessages];
      renderChat({ scrollToBottom: false });
      container.scrollTop = container.scrollHeight - priorHeight + priorTop;
    } else {
      state.chatMessages = messages;
      clearStreamingMessage();
      renderChat();
    }
  } finally {
    state.conversationLoading = false;
  }
}

// --- TTS audio with fade ---

function playTtsAudio(payload) {
  fadeMusicOut();

  const audio = byId("tts-audio");
  audio.src = payload.url;
  audio.hidden = false;
  audio.load();
  byId("tts-hint").textContent = "";

  const playPromise = audio.play();
  if (playPromise?.catch) {
    playPromise
      .then(() => setMessage("moodio is speaking..."))
      .catch(() => {
        byId("tts-hint").textContent = "TTS audio ready. Press play if autoplay was blocked.";
        setMessage("TTS ready");
      });
  }

  audio.onended = () => {
    fadeMusicIn();
    setMessage("♪ playing");
  };
}

function showTtsFailure(payload) {
  fadeMusicIn();
  const message = payload?.message || "TTS audio failed.";
  byId("tts-hint").textContent = `TTS failed: ${message}`;
  setMessage("TTS failed");
}

// --- Server-sent live station events ---

function connectEvents() {
  const events = new EventSource("/api/events");
  const handleMessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.event === "station.state.updated") renderState(message.payload);
    if (message.event === "tts.audio.ready") {
      playTtsAudio(message.payload);
    }
    if (message.event === "tts.audio.failed") {
      showTtsFailure(message.payload);
    }
    if (message.event === "queue.updated") refreshState();
    if (message.event === "agent.response.delta") appendStreamDelta(message.payload.delta);
    if (message.event === "agent.turn.failed") clearStreamingMessage({ render: true });
    if (message.event === "conversation.message.saved") conversationMessageSaved(message.payload.item);
    if (message.event === "conversation.cleared") {
      state.chatMessages = [];
      clearStreamingMessage();
      state.conversationBefore = null;
      state.conversationHasMore = false;
      renderChat();
    }
  };
  ["station.state.updated", "tts.audio.ready", "tts.audio.failed", "queue.updated", "agent.response.delta", "agent.turn.failed", "conversation.message.saved", "conversation.cleared"].forEach((name) => {
    events.addEventListener(name, handleMessage);
  });
  events.addEventListener("error", () => setMessage("reconnecting live updates…"));
}

// --- API helpers ---

async function refreshState() {
  const nowResponse = await fetch("/api/now");
  renderState(await nowResponse.json());
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function postAction(action) {
  const audio = byId("music-audio");
  if (action === "play" && audio?.src) {
    await audio.play();
    await postJson("/api/play", {});
    setMessage("♪ playing");
    await refreshState();
    return;
  }
  if (action === "pause" && audio?.src) {
    audio.pause();
    await postJson("/api/pause", {});
    setMessage("paused");
    await refreshState();
    return;
  }
  const payload = await postJson(`/api/${action}`, {});
  setMessage(`${action} accepted`);
  await refreshState();
  if (action === "play" && audio?.src) {
    await audio.play().then(() => setMessage("♪ playing")).catch(() => setMessage("Press Play to begin audio"));
  }
  return payload;
}

function renderMusicSearch(results) {
  const list = byId("music-search-results");
  list.innerHTML = "";
  for (const track of results) {
    const item = document.createElement("li");
    const title = document.createElement("span");
    title.className = "queue-title";
    title.textContent = track.title;
    const meta = document.createElement("span");
    meta.className = "queue-meta";
    meta.textContent = `${track.artist} · ${Math.round(track.duration_seconds / 60)} min`;
    const queue = document.createElement("button");
    queue.textContent = "Next";
    queue.addEventListener("click", async () => {
      await postJson("/api/music/queue-next", {
        candidate_id: track.playback_ref,
        expected_revision: state.now?.queue_revision,
      });
      setMessage(`Queued ${track.title}`);
      await refreshState();
    });
    const play = document.createElement("button");
    play.textContent = "Play";
    play.addEventListener("click", async () => {
      const audio = byId("music-audio");
      const streamPath = `/api/music/stream/${encodeURIComponent(track.playback_ref)}`;
      state.renderedPlaybackRef = track.playback_ref;
      audio.src = streamPath;
      audio.load();
      const immediatePlayback = audio.play();
      try {
        await postJson("/api/music/play-now", { candidate_id: track.playback_ref });
        await immediatePlayback;
        setMessage(`♪ playing ${track.title}`);
        await refreshState();
      } catch (error) {
        audio.pause();
        setMessage(error.message || "Unable to start that track");
      }
    });
    item.append(title, meta, queue, play);
    list.appendChild(item);
  }
}

// --- Event listeners ---

document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    try { await postAction(button.dataset.action); }
    catch (error) { setMessage(error.message); }
  });
});

byId("favorite-button").addEventListener("click", async () => {
  if (!state.currentTrackId) return;
  try {
    await postJson("/api/favorite", { track_id: state.currentTrackId });
    setMessage("favorited ♥");
  } catch (error) { setMessage(error.message); }
});

byId("voice-mode").addEventListener("change", async (event) => {
  try { await postJson("/api/voice-mode", { enabled: event.target.checked }); }
  catch (error) { setMessage(error.message); }
});

byId("command-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = byId("command-input");
  const text = input.value.trim();
  if (!text) return;
  addChatMessage("user", text);
  input.value = "";
  try {
    await postJson("/api/command", { text });
    setMessage("");
    await refreshState();
  } catch (error) { setMessage(error.message); }
});

byId("clear-conversation").addEventListener("click", async () => {
  const confirmed = window.confirm(
    "Clear all conversation history? This keeps your listener profile, queue, play signals, and station tasks."
  );
  if (!confirmed) return;
  try {
    const response = await fetch("/api/conversation", { method: "DELETE" });
    if (!response.ok) throw new Error(await response.text());
    setMessage("Conversation history cleared. Your taste and station state were kept.");
  } catch (error) {
    setMessage(error.message || "Unable to clear conversation history");
  }
});

byId("music-search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = byId("music-search-input");
  const query = input.value.trim();
  if (!query) return;
  try {
    const result = await postJson("/api/music/search", { query, limit: 10 });
    renderMusicSearch(result.results);
  } catch (error) { setMessage(error.message); }
});

byId("apple-music-import-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = byId("apple-music-import-file").files?.[0];
  if (!file) return;
  try {
    setMessage("Importing taste signals and finding a few opening tracks…");
    const response = await fetch("/api/preferences/apple-music-xml", {
      method: "POST",
      headers: { "content-type": file.type || "application/xml" },
      body: file,
    });
    if (!response.ok) throw new Error((await response.json()).detail || "Apple Music import failed");
    const result = await response.json();
    const queued = result.queue?.total_queued || 0;
    setMessage(`Imported ${result.import.track_count} tracks and queued ${queued} opening picks.`);
    event.target.reset();
    byId("apple-music-import-name").textContent = "No file selected";
    await refreshState();
  } catch (error) {
    setMessage(error.message);
  }
});

byId("apple-music-import-file").addEventListener("change", (event) => {
  byId("apple-music-import-name").textContent = event.target.files?.[0]?.name || "No file selected";
});

const musicAudio = byId("music-audio");
musicAudio.addEventListener("loadedmetadata", renderPlaybackProgress);
musicAudio.addEventListener("durationchange", renderPlaybackProgress);
musicAudio.addEventListener("timeupdate", renderPlaybackProgress);
musicAudio.addEventListener("emptied", renderPlaybackProgress);
byId("playback-progress").addEventListener("input", (event) => {
  const nextPosition = Number(event.target.value);
  if (Number.isFinite(nextPosition) && Number.isFinite(musicAudio.duration)) {
    musicAudio.currentTime = nextPosition;
    renderPlaybackProgress();
  }
});
window.addEventListener("resize", renderPlaybackProgress);
musicAudio.addEventListener("ended", async () => {
  if (!state.now?.now_playing) return;
  await postJson("/api/events/playback", {
    event_type: "music.playback.ended",
    track_id: state.now.now_playing.track_id,
    position_seconds: Math.round(musicAudio.duration || 0),
    duration_seconds: Math.round(musicAudio.duration || 1),
  });
  await postAction("next");
});
musicAudio.addEventListener("error", () => setMessage("Audio stream unavailable"));

byId("chat-messages").addEventListener("scroll", () => {
  const container = byId("chat-messages");
  if (container.scrollTop < 48) loadConversation({ older: true }).catch((error) => setMessage(error.message));
});

Promise.all([refreshState(), loadConversation()]).then(connectEvents).catch((error) => setMessage(error.message));
