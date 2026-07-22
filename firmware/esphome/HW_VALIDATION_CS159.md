# CS-159 hardware validation — end-word turn control live on device

Date: 2026-07-22 evening. Setup: HA core upgraded 2026.3.1 -> 2026.7.3
(container `hass` on the NAS; previous container preserved as
`hass-2026.3-backup`, config tarball taken before first 2026.7 boot),
`coach_stt` custom integration deployed and selected as the Coach FR
pipeline STT engine, firmware `fa8d8f5`+`ced9e79` (voice_assistant fork +
dual KWS with the trained jai_fini model) flashed over USB serial.
Evidence: serial log session 19:43-19:55, observer transcript in the
session notes; USER present and validating by ear.

## Results

| # | Test | Result | Evidence (serial log) |
|---|------|--------|-----------------------|
| 1 | Wake -> capture -> end word -> graceful finish -> transcript -> reply | PASS | 19:43:11 wake 0.65/0.90 -> `Signaling end of speech (voice_assistant.finish)` -> `Intent started` -> TTS plays. The stock `stop` used to ABORT (no transcript, no reply); `Intent started` after finish is the direct proof the graceful path works. |
| 2 | Long pauses do not end the turn (server VAD removed) | PASS | Multiple captures of 21 s, 33 s and 35 s with mid-speech pauses; no truncation. The old 1.25 s silence cut AND the 15 s VoiceCommandSegmenter hard cap are both gone. |
| 3 | End-word model (jai_fini) detection during active STT capture | PASS | 7/7 deliberate end words detected first try across the session (sliding avg 0.60-0.77, max 0.88-1.00), each correctly routed to `voice_assistant.finish`. |
| 4 | Wake model re-armed after turn / after reply | PASS | `Starting wake word detection` follows every turn end and every reply; exactly one model enabled at any moment throughout the log. |
| 5 | End word spoken alone on a continued turn | PASS (edge) | Transcript empty -> `stt-no-text-recognized` -> device returns to IDLE cleanly, wake re-armed. Acceptable close-without-content path; shows briefly as an error state on screen. |
| 6 | Coach answers the question instead of closing (transcript hygiene) | PASS after fix | First trial FAILED: "Est-ce que tout va bien ? j'ai fini" -> coach replied "ok, on s'arrête là" (the transcribed end word collided with the prompt's closing-cue tier). Fixed by stripping ONE trailing end word in `coach_stt` before the conversation stage (const.py END_WORD_TRAILING_PATTERN + stt.py). Re-test: coach answered the question. USER-confirmed. |

## Findings

- **R1 (open, follow-up): first wake shortly after a turn ends can be
  swallowed.** Twice (19:43:38, ~4 s after turn end; 19:53:57, ~8 s after)
  a detected wake word produced `State changed from IDLE to IDLE` and no
  pipeline start; the 1 s interval safety-net re-armed the wake model and
  the NEXT attempt always succeeded. Reproducible, retry-once workaround,
  suspected teardown race between the previous HA pipeline run and the new
  start request. Needs a source-level trace (device `is_running` vs HA
  satellite entity state) before any fix.
- **R2 (resolved): the spoken end word reaches the transcript** and reads
  as a farewell to the coach prompt. Structural (the audio necessarily
  contains the end word before the stream closes); resolved
  deterministically in the STT entity, trailing occurrence only, so
  mid-sentence "j'ai fini ..." content survives. Known residual ambiguity:
  a learner ANSWERING "oui, j'ai fini" as content immediately followed by
  the end word would lose one occurrence.
- **R3 (behavior note): continue_conversation now composes well with the
  end word.** After a coach relance the mic re-opens without a wake word,
  the learner answers at leisure and closes with the end word. Playback
  finishes BEFORE the mic re-opens, so no TTS echo. Walk-away case: an
  abandoned continued turn runs until the coach_stt 120 s backstop, then
  transcribes ambient audio (or nothing); observed to end in the
  no-text path. Acceptable; revisit if it annoys in real use.
- The bench-era concern "continuous KWS breaks TTS" stays resolved: the
  listening-window-only design played every reply fully.

## Verdict

CS-159's product objective — "the learner can pause as long as she wants;
the turn ends only on her explicit end word" — is ACHIEVED and validated
live by the user. R1 is the only open defect (retry-once UX).

## Addendum 2026-07-22 late evening — « Connexion HA » live capture

Dedicated investigation of the on-device « Connexion HA » drops (open since
session 21, then attributed to environmental RF with "software maxed out").
Setup: device on USB serial next to the PC, serial log streamed to disk, plus
a 2 s-interval probe pinging the device AND the HA web port so a drop splits
into wifi-down vs HA-api-down. A 10-minute measured baseline window
(21:53:09-22:03:09) plus one pre-window drop were captured.

### Drop capture: the cascade is roam-initiated

Every observed drop had `dev=DOWN ha=UP` — the HA side never failed. The
in-window drop is one 56 s cascade, device-initiated (serial excerpt):

```
22:00:03.817 [I][wifi:2495]: Roaming to 3A:07:16:22:22:80 (+17 dB)
22:00:03.861 [W][wifi_esp32:803]: Disconnected ssid='Freebox-1EFAD1'
             bssid=3A:07:16:8B:5F:74 reason='Association Leave'
22:00:03.883 [D][wifi:2112]: Roam failed, reconnecting (attempt 2/3)
22:00:20-32  (summarised) four HA TCP accepts each die "Network down; disconnect"
22:00:34.876 [E][wifi:1442]: Scan timeout
22:00:34.909 Disconnected bssid=3A:07:16:22:22:80 reason='Association Leave'
22:00:34.929 [W][wifi:736]: Restarting adapter
22:00:38.059 scan: 'Freebox-1EFAD1' (3A:07:16:8B:5F:74) Ch:11 -72dB
22:00:56.675 Connected, BSSID 3A:07:16:8B:5F:74, -70 dB
22:00:59     (ping probe, not serial) dev=UP ha=UP — full recovery
```

Signal from the pinned AP measured -53 dB at 21:50:00 and -72 dB at
22:00:38 with the device stationary: the desk RF swing is real (the
environmental half of the session-21 conclusion stands). What turns a
transient fade into a 56 s outage is the ESPHome roam engine
(`post_connect_roaming`, C++ default true, single use-site
wifi_component.cpp:818): on seeing a sibling BSSID >=10 dB stronger it
leaves the current AP ('Association Leave' is the device leaving), bypasses
the configured bssid pin (candidate filter wifi_component.cpp:2467-2470
never consults it), and on failure falls into the scan/adapter-restart
retry loop. A successful roam would be sticky too: every connect persists
the fast_connect BSSID (wifi_component.cpp:1639), so the next cold boot
would fast-connect to the unpinned AP. Fix: `post_connect_roaming: false`
in coach-terminal-base.yaml. The pre-window drop (21:49, scan cycles with
"No networks found" against the hidden SSID) matches the same
blind-window signature mid-cascade.

Post-fix control window (same position, same probes, firmware with the
fix flashed 22:23): 22:24:39-22:34:39, ZERO drops and zero
roam/disconnect serial events, vs 1 cascade in the pre-fix window. One
window is not statistical proof; the mechanism-level evidence (source
audit + live capture + clean control) is what carries the conclusion.
The RF swing itself remains environmental — physical relocation stays
the fallback if drops recur in daily use.

### R1 field re-assessment: park it

Deliberate re-repro failed in normal use: after « j'ai fini » the coach
reply itself occupies the 4-8 s window, and re-waking after the reply
succeeded consistently. Combined with the retry-once workaround and the
1 s re-arm (0.6 s measured this session: IDLE 21:59:24.47 -> wake armed
21:59:25.05), R1's practical impact is negligible. DECISION: R1 is parked
as accepted behavior (retry once); no further device time. The candidate
mechanism recorded for the archive: `request_start` needs `state_ == IDLE`
and a non-null `api_client_` (voice_assistant.cpp:644-657) — a wake landing
in the post-turn teardown hits either the silent non-IDLE guard or the
null-client path that logs `State changed from IDLE to IDLE`.

### R2 residual variant observed (new)

21:59:08 turn: the spoken end word was transcribed as « Réfinis. Réfinis. »
and passed the coach_stt trailing strip (which matches fini/finit/finis/
finie variants, not this mistranscription). First turn after power-on is
the suspected aggravator (USER observation). One benign occurrence (the
coach ignored it); logged as an open residual: extend
END_WORD_TRAILING_PATTERN with observed mistranscription variants and/or
bias the whisper initial_prompt with the end phrase. The latter was the
deliberately-deferred half of the 2026-07-22 Lingorm initial_prompt fix
("only if residuals appear") — that trigger condition is now met.
