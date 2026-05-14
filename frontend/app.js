/**
 * app.js – Voice Agent Integrator frontend logic
 *
 * Flow
 * ----
 * 1. User clicks the green phone button  → mic opens, WebSocket connects.
 * 2. MediaRecorder records audio chunks  → binary frames sent to server.
 * 3. Silence detector (Web Audio API) watches the microphone level.
 *    When RMS stays below SILENCE_THRESHOLD for SILENCE_DURATION_MS, it
 *    means the user has finished speaking:
 *      a. Recording stops.
 *      b. {"type":"end_of_speech"} is sent to the server.
 * 4. Server replies with status, transcript, and finally {"type":"speak"}.
 * 5. SpeechSynthesis speaks the reply aloud.
 * 6. After speaking ends (or is interrupted), the mic resumes for the
 *    next turn.
 * 7. User clicks the red phone button  → call ends.
 */

"use strict";

// ── Tuneable constants ────────────────────────────────────────────────────────
const SILENCE_THRESHOLD   = 0.015;   // RMS amplitude below which = silence
const SILENCE_DURATION_MS = 1500;    // ms of continuous silence → end-of-speech
const ANALYSIS_INTERVAL   = 100;     // ms between RMS checks
const WS_URL              = `ws://${location.host}/ws`;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const btnStart      = document.getElementById("btn-start");
const btnEnd        = document.getElementById("btn-end");
const statusEl      = document.getElementById("status");
const transcriptEl  = document.getElementById("transcript");
const replyEl       = document.getElementById("reply");
const logEl         = document.getElementById("log");
const waveCanvas    = document.getElementById("waveform");
const ctx2d         = waveCanvas ? waveCanvas.getContext("2d") : null;

// ── State ─────────────────────────────────────────────────────────────────────
let ws               = null;
let mediaRecorder    = null;
let audioChunks      = [];
let audioCtx         = null;
let analyser         = null;
let silenceTimer     = null;
let silenceCheckInterval = null;
let animFrameId      = null;
let micStream        = null;
let isRecording      = false;
let agentSpeaking    = false;   // true while SpeechSynthesis is active
let currentUtterance = null;

// ── Helpers ───────────────────────────────────────────────────────────────────
function log(msg, level = "info") {
    if (!logEl) return;
    const line = document.createElement("div");
    line.className = `log-${level}`;
    line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    logEl.prepend(line);
}

function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
    log(text);
}

function showError(msg) {
    setStatus("⚠ " + msg);
    log(msg, "error");
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
function connectWebSocket() {
    ws = new WebSocket(WS_URL);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
        setStatus("Connected – listening…");
        startListening();
    };

    ws.onclose = () => {
        setStatus("Disconnected.");
        stopCall();
    };

    ws.onerror = (e) => {
        showError("WebSocket error – check the server.");
        console.error(e);
    };

    ws.onmessage = (event) => {
        if (typeof event.data !== "string") return;
        let payload;
        try { payload = JSON.parse(event.data); }
        catch { return; }

        switch (payload.type) {
            case "status":
                setStatus(payload.text);
                break;
            case "transcript":
                if (transcriptEl) {
                    transcriptEl.textContent = "You: " + payload.text;
                }
                log("You: " + payload.text);
                break;
            case "speak":
                if (replyEl) replyEl.textContent = "Agent: " + payload.text;
                log("Agent: " + payload.text);
                speak(payload.text);
                break;
            case "error":
                showError(payload.text);
                // Resume listening even on error
                scheduleResumeListening(500);
                break;
            case "pong":
                break;
        }
    };
}

// ── Microphone & recording ────────────────────────────────────────────────────
async function openMic() {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    return micStream;
}

function buildAudioGraph(stream) {
    audioCtx  = new (window.AudioContext || window.webkitAudioContext)();
    analyser  = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    const source = audioCtx.createMediaStreamSource(stream);
    source.connect(analyser);
    // Note: we do NOT connect analyser to destination – avoids mic feedback
}

function startMediaRecorder(stream) {
    const mimeType = getSupportedMimeType();
    const options  = mimeType ? { mimeType } : {};
    mediaRecorder  = new MediaRecorder(stream, options);
    audioChunks    = [];

    mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
            audioChunks.push(e.data);
            if (ws && ws.readyState === WebSocket.OPEN) {
                e.data.arrayBuffer().then(buf => {
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(buf);
                    }
                });
            }
        }
    };

    mediaRecorder.start(200); // emit chunks every 200 ms
    isRecording = true;
}

function getSupportedMimeType() {
    const types = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/ogg;codecs=opus",
        "audio/mp4",
    ];
    return types.find(t => MediaRecorder.isTypeSupported(t)) || "";
}

function stopMediaRecorder() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
    }
    isRecording = false;
}

// ── Silence detection ─────────────────────────────────────────────────────────
function startSilenceDetection() {
    clearInterval(silenceCheckInterval);
    clearTimeout(silenceTimer);
    silenceTimer = null;
    const data = new Float32Array(analyser.fftSize);

    const check = () => {
        if (!isRecording || agentSpeaking) return;

        analyser.getFloatTimeDomainData(data);
        const rms = Math.sqrt(data.reduce((s, v) => s + v * v, 0) / data.length);

        if (rms < SILENCE_THRESHOLD) {
            if (silenceTimer === null) {
                silenceTimer = setTimeout(onEndOfSpeech, SILENCE_DURATION_MS);
            }
        } else {
            clearTimeout(silenceTimer);
            silenceTimer = null;
        }
    };

    // Use setInterval for silence checks (separate from animation frame)
    silenceCheckInterval = setInterval(check, ANALYSIS_INTERVAL);
}

function stopSilenceDetection() {
    clearInterval(silenceCheckInterval);
    clearTimeout(silenceTimer);
    silenceTimer = null;
}

function onEndOfSpeech() {
    if (!isRecording || agentSpeaking) return;
    log("Silence detected – sending audio for processing.");
    setStatus("Processing…");
    stopMediaRecorder();
    stopSilenceDetection();

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "end_of_speech" }));
    }
}

// ── Waveform visualisation ────────────────────────────────────────────────────
function drawWaveform() {
    if (!ctx2d || !analyser) return;

    animFrameId = requestAnimationFrame(drawWaveform);
    const bufLen = analyser.frequencyBinCount;
    const data   = new Uint8Array(bufLen);
    analyser.getByteTimeDomainData(data);

    const W = waveCanvas.width;
    const H = waveCanvas.height;

    ctx2d.clearRect(0, 0, W, H);
    ctx2d.lineWidth   = 2;
    ctx2d.strokeStyle = agentSpeaking ? "#4CAF50" : "#2196F3";
    ctx2d.beginPath();

    const sliceW = W / bufLen;
    let x = 0;
    for (let i = 0; i < bufLen; i++) {
        const v = data[i] / 128.0;
        const y = (v * H) / 2;
        i === 0 ? ctx2d.moveTo(x, y) : ctx2d.lineTo(x, y);
        x += sliceW;
    }
    ctx2d.lineTo(W, H / 2);
    ctx2d.stroke();
}

// ── Text-to-Speech (Web Speech API) ──────────────────────────────────────────
function speak(text) {
    agentSpeaking = true;
    setStatus("Agent speaking…");
    stopSilenceDetection();

    window.speechSynthesis.cancel(); // cancel any ongoing speech

    currentUtterance = new SpeechSynthesisUtterance(text);
    currentUtterance.rate   = 1.0;
    currentUtterance.pitch  = 1.0;
    currentUtterance.volume = 1.0;

    currentUtterance.onend = () => {
        agentSpeaking = false;
        scheduleResumeListening(300);
    };

    currentUtterance.onerror = (e) => {
        console.error("SpeechSynthesis error:", e);
        agentSpeaking = false;
        scheduleResumeListening(300);
    };

    window.speechSynthesis.speak(currentUtterance);
}

function scheduleResumeListening(delayMs) {
    setTimeout(startListening, delayMs);
}

// ── Call lifecycle ────────────────────────────────────────────────────────────
async function startListening() {
    if (!micStream || !ws || ws.readyState !== WebSocket.OPEN || agentSpeaking) return;
    startMediaRecorder(micStream);
    startSilenceDetection();
    setStatus("Listening… (speak now)");
}

async function startCall() {
    btnStart.disabled = true;
    btnEnd.disabled   = false;
    setStatus("Requesting microphone…");

    try {
        const stream = await openMic();
        buildAudioGraph(stream);
        drawWaveform();
        connectWebSocket();
        // listening starts inside ws.onopen after connection is established
    } catch (err) {
        showError("Microphone access denied: " + err.message);
        btnStart.disabled = false;
        btnEnd.disabled   = true;
    }
}

function stopCall() {
    // Stop recording
    stopMediaRecorder();
    stopSilenceDetection();

    // Stop animation
    if (animFrameId) cancelAnimationFrame(animFrameId);
    animFrameId = null;

    // Stop TTS
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    agentSpeaking = false;

    // Close WebSocket
    if (ws) {
        ws.onclose = null; // prevent recursive stopCall
        ws.close();
        ws = null;
    }

    // Release mic
    if (micStream) {
        micStream.getTracks().forEach(t => t.stop());
        micStream = null;
    }

    // Close AudioContext
    if (audioCtx) {
        audioCtx.close().catch(() => {});
        audioCtx = null;
    }

    btnStart.disabled = false;
    btnEnd.disabled   = true;
    setStatus("Call ended.");
}

// ── Button listeners ──────────────────────────────────────────────────────────
btnStart.addEventListener("click", startCall);
btnEnd.addEventListener("click",   stopCall);
