#!/usr/bin/env bash
# Record real-voice "hello lingorm" positive clips for microWakeWord retraining.
#
# The shipped hello_lingorm model was trained only on synthetic piper/LibriTTS-R
# speakers, so on-device recall on the owner's real voice/accent is poor. This
# harness captures short real-voice utterances to fold into the positive corpus
# as a weighted feature source (see RETRAIN_WITH_REAL_VOICE.md).
#
# Output: 16 kHz mono 16-bit PCM WAV, one utterance per file, resumable
# (never overwrites existing clips in the target directory).
#
# Usage:
#   ./record_real_positives.sh [COUNT] [OUT_DIR] [MIC_SOURCE]
# Defaults:
#   COUNT=60
#   OUT_DIR=~/dev/coach-kws/data/positives_hello_lingorm_real
#   MIC_SOURCE=alsa_input.usb-Logitech_PRO_X_Wireless_Gaming_Headset-00.mono-fallback
#
# List available PulseAudio/PipeWire sources with:  pactl list short sources

set -euo pipefail

COUNT="${1:-60}"
OUT_DIR="${2:-$HOME/dev/coach-kws/data/positives_hello_lingorm_real}"
MIC_SOURCE="${3:-alsa_input.usb-Logitech_PRO_X_Wireless_Gaming_Headset-00.mono-fallback}"

RECORD_SECONDS=2.0     # window per utterance; "hello lingorm" is ~1 s
SAMPLE_RATE=16000      # microWakeWord canonical rate
PHRASE="hello lingorm"

command -v ffmpeg >/dev/null || { echo "ffmpeg not found" >&2; exit 1; }
mkdir -p "$OUT_DIR"

# Resume from the highest existing index so re-runs keep adding clips.
last=-1
for f in "$OUT_DIR"/*.wav; do
  [ -e "$f" ] || continue
  n="$(basename "$f" .wav)"
  [[ "$n" =~ ^[0-9]+$ ]] && (( n > last )) && last="$n"
done
start=$(( last + 1 ))

echo "Recording ${COUNT} clips of \"${PHRASE}\" -> ${OUT_DIR}"
echo "Mic source: ${MIC_SOURCE}"
echo "Existing clips: $(( last + 1 )). New indices: ${start}..$(( start + COUNT - 1 ))."
echo
echo "Vary it: normal pace, a bit faster, a bit slower, softer, louder, and"
echo "hold the terminal at roughly the distance you use the device. This spread"
echo "is what teaches the model YOUR voice rather than one fixed rendition."
echo
read -r -p "Press Enter to start. Ctrl-C to stop anytime (clips so far are kept)."

for (( i = 0; i < COUNT; i++ )); do
  idx=$(( start + i ))
  out="$OUT_DIR/${idx}.wav"
  printf '\n[%d/%d] index %d -- get ready...' "$(( i + 1 ))" "$COUNT" "$idx"
  sleep 0.6; printf ' 3'; sleep 0.5; printf ' 2'; sleep 0.5; printf ' 1'; sleep 0.4
  printf '  SPEAK NOW: "%s"\a\n' "$PHRASE"
  ffmpeg -hide_banner -loglevel error \
    -f pulse -i "$MIC_SOURCE" \
    -t "$RECORD_SECONDS" \
    -ac 1 -ar "$SAMPLE_RATE" -acodec pcm_s16le \
    "$out"
  echo "  saved ${out}"
done

echo
echo "Done. Total clips in ${OUT_DIR}: $(ls "$OUT_DIR"/*.wav 2>/dev/null | wc -l)"
echo "Next: follow RETRAIN_WITH_REAL_VOICE.md to fold these into training."
