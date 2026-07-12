#!/usr/bin/env bash
# Run the microWakeWord training + quantized-tflite export inside the container.
# Intended to be invoked under gpu-solo so wyoming-whisper is paused for the
# single contiguous GPU block.
#
# Usage: gpu-solo scripts/train_in_container.sh
set -euo pipefail

# Root of the work tree mounted into the container as /work. Defaults to the
# current directory; override with COACH_KWS_DIR for an out-of-tree checkout.
WORK_DIR="${COACH_KWS_DIR:-$PWD}"
IMAGE="coach-kws-train:1.0"

docker run --rm --gpus all --ipc=host \
    --ulimit memlock=-1 --ulimit stack=67108864 \
    -e TF_USE_LEGACY_KERAS=0 \
    -e PYTHONPATH=/work/scripts \
    -v "${WORK_DIR}:/work" -w /work \
    "${IMAGE}" \
    bash -c '
set -euo pipefail
# Register microWakeWord as editable without touching frozen numpy/tensorflow.
pip install --no-deps -q -e /work/ohf-src
python -m microwakeword.model_train_eval \
    --training_config=training_parameters.yaml \
    --train 1 \
    --restore_checkpoint 1 \
    --test_tf_nonstreaming 0 \
    --test_tflite_nonstreaming 0 \
    --test_tflite_nonstreaming_quantized 0 \
    --test_tflite_streaming 0 \
    --test_tflite_streaming_quantized 1 \
    --use_weights "best_weights" \
    mixednet \
    --pointwise_filters "64,64,64,64" \
    --repeat_in_block "1, 1, 1, 1" \
    --mixconv_kernel_sizes "[5], [7,11], [9,15], [23]" \
    --residual_connection "0,0,0,0" \
    --first_conv_filters 32 \
    --first_conv_kernel_size 5 \
    --stride 3

# Hand ownership of generated artifacts back to the host user.
chown -R '"$(id -u)":"$(id -g)"' /work/trained_models
'
