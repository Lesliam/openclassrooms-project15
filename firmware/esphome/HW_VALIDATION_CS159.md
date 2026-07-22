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
