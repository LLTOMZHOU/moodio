const state = {
  now: null,
  currentTrackId: null,
  soundCloudWidget: null,
  renderedPlaybackRef: null,
  soundCloudReady: false,
  chatMessages: [],
  isSpeaking: false,
  musicVolume: 1,
};

const byId = (id) => document.getElementById(id);

function setMessage(text) {
  byId("message").textContent = text;
}

function soundCloudUrlFromPlaybackRef(playbackRef) {
  const prefix = "soundcloud:embed:";
  if (!playbackRef || !playbackRef.startsWith(prefix)) return null;
  return playbackRef.slice(prefix.length);
}

function soundCloudPublicUrl(track) {
  return track?.external_url || soundCloudUrlFromPlaybackRef(track?.playback_ref);
}

// --- Audio fade for music when DJ speaks ---

function fadeMusicOut(duration = 800) {
  if (!state.soundCloudWidget || !state.soundCloudReady) return;
  state.isSpeaking = true;
  const steps = 20;
  const stepTime = duration / steps;
  let step = 0;
  const fade = setInterval(() => {
    step++;
    const vol = Math.max(0, 1 - step / steps);
    try { state.soundCloudWidget.setVolume(vol * 100); } catch {}
    if (step >= steps) clearInterval(fade);
  }, stepTime);
}

function fadeMusicIn(duration = 800) {
  if (!state.soundCloudWidget || !state.soundCloudReady) return;
  const steps = 20;
  const stepTime = duration / steps;
  let step = 0;
  const fade = setInterval(() => {
    step++;
    const vol = Math.min(1, step / steps);
    try { state.soundCloudWidget.setVolume(vol * 100); } catch {}
    if (step >= steps) {
      clearInterval(fade);
      state.isSpeaking = false;
    }
  }, stepTime);
}

// --- SoundCloud embed (hidden visually, functional for audio) ---

function renderEmbed(track) {
  const slot = byId("embed-slot");
  const openSoundCloudTrack = byId("soundcloud-open-link");
  const soundCloudUrl = soundCloudUrlFromPlaybackRef(track?.playback_ref);
  if (!soundCloudUrl) {
    state.soundCloudWidget = null;
    state.renderedPlaybackRef = null;
    state.soundCloudReady = false;
    if (openSoundCloudTrack) {
      openSoundCloudTrack.hidden = true;
      openSoundCloudTrack.href = "#";
    }
    slot.innerHTML = "";
    return;
  }
  if (openSoundCloudTrack) {
    openSoundCloudTrack.hidden = false;
    openSoundCloudTrack.href = soundCloudPublicUrl(track);
  }
  if (state.renderedPlaybackRef === track.playback_ref && state.soundCloudWidget) {
    return;
  }

  const playerUrl = new URL("https://w.soundcloud.com/player/");
  playerUrl.searchParams.set("url", soundCloudUrl);
  playerUrl.searchParams.set("auto_play", "true");
  playerUrl.searchParams.set("hide_related", "true");
  playerUrl.searchParams.set("show_comments", "false");
  playerUrl.searchParams.set("show_user", "false");
  playerUrl.searchParams.set("show_reposts", "false");
  playerUrl.searchParams.set("visual", "false");
  playerUrl.searchParams.set("color", "2d2d2d");
  playerUrl.searchParams.set("buying", "false");
  playerUrl.searchParams.set("download", "false");
  playerUrl.searchParams.set("sharing", "false");
  playerUrl.searchParams.set("show_artwork", "false");
  playerUrl.searchParams.set("show_playcount", "false");
  playerUrl.searchParams.set("like", "false");

  slot.innerHTML = "";
  state.soundCloudWidget = null;
  state.renderedPlaybackRef = track.playback_ref;
  state.soundCloudReady = false;
  const iframe = document.createElement("iframe");
  iframe.title = `SoundCloud player for ${track.title}`;
  iframe.allow = "autoplay";
  iframe.src = playerUrl.toString();
  slot.appendChild(iframe);
  if (window.SC?.Widget) {
    state.soundCloudWidget = window.SC.Widget(iframe);
    state.soundCloudWidget.bind(SC.Widget.Events.READY, () => {
      state.soundCloudReady = true;
    });
    state.soundCloudWidget.bind(SC.Widget.Events.PLAY, () => setMessage("♪ playing"));
    state.soundCloudWidget.bind(SC.Widget.Events.PAUSE, () => setMessage("paused"));
    state.soundCloudWidget.bind(SC.Widget.Events.ERROR, () => setMessage("SoundCloud player error"));
  }
}

// --- Station state rendering ---

function renderState(payload) {
  state.now = payload;
  state.currentTrackId = payload.now_playing.track_id;

  byId("status-line").textContent = `${payload.mode} / ${payload.talk_density}`;
  byId("station-status").textContent = payload.status;
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
  title.textContent = `${index + 1}. ${track.title}`;

  const meta = document.createElement("span");
  meta.className = "queue-meta";
  meta.textContent = `${track.artist} · ${track.album || "Unknown source"}`;

  const badge = document.createElement("span");
  badge.className = "queue-badge";
  badge.textContent = soundCloudUrlFromPlaybackRef(track.playback_ref) ? "SC" : "demo";

  item.append(title, meta, badge);
  return item;
}

// --- Chat conversation view ---

function addChatMessage(role, text) {
  state.chatMessages.push({ role, text, time: new Date() });
  renderChat();
}

function renderChat() {
  const container = byId("chat-messages");
  container.innerHTML = "";
  for (const msg of state.chatMessages) {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble chat-${msg.role}`;

    const textEl = document.createElement("div");
    textEl.className = "chat-text";
    textEl.textContent = msg.text;

    const timeEl = document.createElement("div");
    timeEl.className = "chat-time";
    timeEl.textContent = msg.time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    bubble.append(textEl, timeEl);
    container.appendChild(bubble);
  }
  container.scrollTop = container.scrollHeight;
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

// --- WebSocket event stream ---

function connectEvents() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${window.location.host}/api/stream`);
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.event === "station.state.updated") renderState(message.payload);
    if (message.event === "tts.segment.started") {
      addChatMessage("moodio", message.payload.text);
    }
    if (message.event === "tts.audio.ready") {
      playTtsAudio(message.payload);
    }
    if (message.event === "tts.audio.failed") {
      showTtsFailure(message.payload);
    }
    if (message.event === "queue.updated") refreshState();
  });
  socket.addEventListener("close", () => setMessage("event stream disconnected"));
}

// --- API helpers ---

async function refreshState() {
  const [nowResponse, transcriptResponse] = await Promise.all([
    fetch("/api/now"),
    fetch("/api/transcript/current"),
  ]);
  renderState(await nowResponse.json());
  const transcript = await transcriptResponse.json();
  // Sync transcript into chat (only add segments not already in chat)
  for (const seg of transcript.segments || []) {
    const already = state.chatMessages.some(m => m.role === "moodio" && m.text === seg.text);
    if (!already && seg.text) {
      addChatMessage("moodio", seg.text);
    }
  }
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
  if (action === "play" && state.soundCloudWidget) {
    playSoundCloud();
    return;
  }
  if (action === "pause" && state.soundCloudWidget) {
    state.soundCloudWidget.pause();
    setMessage("Pausing...");
    return;
  }
  const payload = await postJson(`/api/${action}`, {});
  setMessage(`${action} accepted`);
  await refreshState();
  return payload;
}

function playSoundCloud() {
  if (!state.soundCloudWidget) {
    setMessage("No SoundCloud player loaded");
    return;
  }
  if (!state.soundCloudReady) {
    setMessage("SoundCloud still loading...");
    return;
  }
  state.soundCloudWidget.play();
  setMessage("Playing from SoundCloud...");
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

refreshState().then(connectEvents).catch((error) => setMessage(error.message));
