# BENCH PROCEDURE — CS-159 concurrent mid-turn wake word

**Throwaway bench test. Not production.** Validates the single open condition
from `SPIKE_REPORT_CS159.md` §4/§6.2: on the real ESP32-S3 @ ESPHome 2026.5.3,
can ONE `micro_wake_word` model keep **detecting during an active
`voice_assistant` turn** while STT stays intact?

Config under test: `coach-terminal-benchtest-cs159.yaml` (single model, reuses
`ml/kws/models/hello_lingorm.json`; `stop_after_detection: false`;
`silence_detection: false`; mid-turn detection routed to `voice_assistant.stop`).

Run everything below from `firmware/esphome/`.

---

## 0. Prerequisites

- Device: ESP32-S3 HW-678A, connected by USB. It enumerates as `/dev/ttyACM0`
  (owner `root:uucp`). Your user is NOT in `uucp`/`dialout`, so a permission fix
  is required before flashing (step 1).
- `secrets.yaml` already exists in this folder (contains wifi/api/ota secrets).
- Home Assistant reachable, with the voice pipeline (Whisper STT -> coach LLM ->
  Piper TTS) that the production terminal normally uses. The bench needs a live
  pipeline so STT transcripts appear in HA.
- ESPHome 2026.5.3 on PATH (`esphome version`).

Pre-check the config still validates (no device needed):

```bash
esphome config coach-terminal-benchtest-cs159.yaml
# expect: "INFO Configuration is valid!"  (exit code 0)
```

---

## 1. Pre-flash — serial permission fix

Plug the device in, confirm it enumerated, then grant read/write on the port:

```bash
ls -l /dev/ttyACM0            # confirm it exists, owner root:uucp

# Option A (simplest, per-session):
sudo chmod a+rw /dev/ttyACM0

# Option B (this box has no TTY for sudo — use the askpass GUI helper):
SUDO_ASKPASS=/usr/bin/ksshaskpass sudo -A chmod a+rw /dev/ttyACM0
```

The permission resets when the device is unplugged/replugged; re-run if needed.

---

## 2. Flash (serial, first flash)

This is a new firmware name (`coach-terminal-bench159`), so the first flash MUST
go over serial — OTA has nothing to update yet.

```bash
esphome run coach-terminal-benchtest-cs159.yaml --device /dev/ttyACM0
```

- When prompted, pick the serial port (`/dev/ttyACM0`).
- The first build downloads the esp-idf toolchain and compiles — this is slow
  the first time. Let it finish; it flashes automatically, then drops into the
  serial log stream.
- After the first flash, subsequent iterations may use OTA (the config keeps the
  production `ota:` block): `esphome run coach-terminal-benchtest-cs159.yaml`
  and pick the network/OTA target. Serial is fine too.

If you want to (re)attach to logs separately at any time:

```bash
esphome logs coach-terminal-benchtest-cs159.yaml --device /dev/ttyACM0
```

Keep this log stream visible throughout the observation — it is where the
`cs159` transition lines appear.

---

## 3. Observation protocol

Watch two things at once: the `esphome logs` stream (device side) and the HA
Assist/pipeline view (STT transcript side).

1. **Wait for idle.** Screen shows "Dites hello lingorm"; onboard LED off.
2. **Start a turn.** Say the wake word: **"hello lingorm"**.
   - Expect in logs: `cs159: wake word while IDLE -> voice_assistant.start
     (silence_detection off)`, then `cs159: voice_assistant LISTENING`.
   - LED turns blue (listening).
3. **Speak a long sentence WITH a deliberate long pause** in the middle, e.g.
   say a few words, stay silent ~4-5 seconds, then continue and finish.
   - Expect: the turn does NOT end during the pause (silence_detection:false
     working). The device stays in "Ecoute..." / blue LED through the pause.
4. **Say the wake word AGAIN, mid-turn** ("hello lingorm"), while the turn is
   still active (before you would otherwise stop).
   - Expect in logs: `cs159: wake word during ACTIVE turn -> voice_assistant.stop
     (end-word proxy)`. This line is the key positive result: KWS detected while
     `voice_assistant` was capturing.
   - The turn then ends and STT completes: `cs159: voice_assistant STT_END --
     transcript delivered`.
5. **Check the transcript in HA** — it should contain the sentence you spoke
   (up to the mid-turn wake word), not garbled or truncated audio.
6. **Repeat steps 1-5 several times** (at least 4-5 trials). Concurrency has to
   be *reliable*, not a one-off; note any trial where the mid-turn detection
   was missed or the transcript was mangled.
7. **Routing sanity check (do once).** Let a normal turn complete so the coach
   is speaking (TTS playing, LED green). While the TTS is still playing, say the
   wake word **once** and record which log line fires: `-> voice_assistant.stop`
   or `-> voice_assistant.start`. This pins down whether `voice_assistant.is_running`
   is true during TTS playback:
   - `-> stop` ⇒ `is_running` is true during TTS ⇒ an echo-driven detection is a
     benign `stop` no-op.
   - `-> start` ⇒ `is_running` is false during TTS ⇒ an echo-driven detection
     starts a NEW turn on the coach's own audio (harmful — feeds the echo loop).
   Note the result; it is needed to interpret the false-trigger analysis below.

---

## 3b. False-trigger discrimination (read before scoring PASS/FAIL)

This harness reuses ONE word (`hello lingorm`) as both the start word and the
end-word proxy, and keeps KWS alive through the pause AND through TTS. As a
result, three DIFFERENT paths all emit the SAME
`cs159: wake word during ACTIVE turn -> voice_assistant.stop` line as a genuine
mid-turn detection. Do not score them the same.

**A `during ACTIVE turn -> stop` line counts as a VALID PASS trial ONLY if it
lands within ~1 s of a DELIBERATELY-spoken second wake word** (step 4). Any
`-> stop` that fires without you speaking a second wake word is a FALSE TRIGGER:

- (i) **Start-word self-retrigger** — a `-> stop` fires immediately after the
  `-> start`, with no second utterance (the start word's own acoustic tail
  re-detecting).
- (ii) **Self-speech false positive** — a `-> stop` fires during the deliberate
  silent pause or while you are mid-sentence, without a wake word.
- (iii) **Acoustic echo** — a `-> stop` fires during or after coach TTS playback
  (the coach's own audio re-detecting; the session-23 echo loop).

**Record every false trigger, and EXCLUDE it from BOTH tallies** — it is neither
a PASS trial nor a CPU-budget FAIL.

Separate the two failure families and never conflate them:

| Family | Symptoms | What it means |
|---|---|---|
| **FALSE TRIGGER** | `-> stop` without a deliberate 2nd wake word: self-retrigger (i), self-speech FP (ii), echo (iii) | A UX / acoustics issue. Does NOT answer the spike's question. |
| **CPU-BUDGET FAIL** | crash, reboot, task-watchdog / CPU stall, or STT transcript garbled/dropped under load | The S3 real-time budget overran. This is the ONLY family that answers the spike. |

Only the CPU-budget family decides the spike verdict. Reusing one word as both
start and end **inherently inflates the false-trigger rate**, so a modest
false-trigger count is EXPECTED and is NOT by itself a CPU-budget FAIL — it just
argues for a distinct end-word (or the push-to-talk fallback) in production.

---

## 4. PASS / FAIL criteria

Score only the trials that survive the §3b false-trigger filter (a valid
detection = a `-> stop` within ~1 s of a deliberately-spoken second wake word).

**PASS** — ALL of the following hold across the repeated trials:
- The mid-turn wake word is **reliably detected DURING an active turn** — the
  `wake word during ACTIVE turn` line fires in response to the deliberate second
  wake word on essentially every trial (false triggers per §3b excluded).
- The **STT transcript stays intact** — the spoken sentence transcribes cleanly
  in HA, not garbled, dropped, or empty.
- The long mid-sentence pause does **not** end the turn (silence_detection:false
  confirmed).
- The device stays stable — no crash, no reboot, no watchdog reset in the logs.

If PASS: promote the concurrent end-word path (spike §4) from stretch goal to a
real design; the two models overrun (§2) does not apply to this single-model case.

**FAIL** — ANY of the following:
- The mid-turn wake word is missed during turns (no `during ACTIVE turn` line,
  or only intermittently).
- The STT transcript breaks (garbled / truncated / empty) when KWS runs during
  capture.
- The device crashes, reboots, or logs a task watchdog / CPU stall (the S3
  real-time budget overran — the exact risk the spike flagged).

If FAIL: the push-to-talk fallback (spike §5) stands as the permanent CS-159
solution.

---

## 5. What to capture (attach to the CS-159 ticket)

- The `esphome logs` output for 2-3 representative trials, showing the sequence:
  `IDLE -> voice_assistant.start` ... `LISTENING` ... `during ACTIVE turn ->
  voice_assistant.stop` ... `STT_END`. This is the evidence of mid-turn detection.
- The HA STT transcript text for those same trials (proves STT stayed intact).
- Any crash/reboot/watchdog log lines if the run FAILED.
- The routing sanity-check result (step 7): which line fired when the wake word
  was said during TTS playback (`-> stop` vs `-> start`), so the reader knows
  whether `voice_assistant.is_running` is true during TTS.
- A per-trial tally that separates the three counts kept distinct in §3b: valid
  mid-turn detections, false triggers (self-retrigger / self-speech FP / echo),
  and CPU-budget faults (crash / reboot / watchdog / garbled STT).
- A one-line verdict per trial and the overall PASS/FAIL.

---

## 6. Tuning notes if results are marginal

- **Weak / missed detection:** the `gain_factor: 4` on the KWS microphone path
  is an unverified migration guess for the 32-bit mic (spike open item #4). If
  detection is unreliable, try editing `micro_wake_word:` -> `microphone:` ->
  `gain_factor` down to `1` (or remove it) and re-flash — the STT path already
  runs at `gain_factor: 1` and works, so the raw mic level may not need the x4.
- **STT breaks but no crash:** likely a gain/AGC interaction, not a CPU-budget
  problem — note it distinctly from a watchdog/reboot, since the two point at
  different root causes for the PM.
- **STT quiet independent of the KWS `gain_factor`:** the STT-path gain equals
  the validated production config, so quiet STT that persists regardless of the
  KWS `gain_factor` is a pre-existing 32-bit-mic migration question, not a
  CS-159 regression.
```

