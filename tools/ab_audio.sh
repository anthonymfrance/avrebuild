#!/usr/bin/env bash
# Play each stimulus at 1.0 s and then at 0.5 s, for listening A/B.
#
#   tools/ab_audio.sh              # both categories
#   tools/ab_audio.sh animate      # one category
#
# Uses the first available player: pw-play, paplay, aplay or ffplay.
set -u
cd "$(dirname "$0")/.."

blocks=("$@")
if [ ${#blocks[@]} -eq 0 ]; then
  blocks=(animate inanimate)
fi

ANIMATE=(cat frog duck cow rooster dog horse lion pig elephant)
INANIMATE=(camera door phone toilet clock car wineglass helicopter motorcycle ship)

player=''
for candidate in pw-play paplay aplay ffplay; do
  if command -v "$candidate" >/dev/null 2>&1; then
    player=$candidate
    break
  fi
done
if [ -z "$player" ]; then
  echo 'No audio player found (tried pw-play, paplay, aplay, ffplay).' >&2
  exit 1
fi

play() {
  case $player in
    ffplay) ffplay -nodisp -autoexit -loglevel quiet "$1" ;;
    *) "$player" "$1" ;;
  esac
}

for block in "${blocks[@]}"; do
  case $block in
    animate) names=("${ANIMATE[@]}") ;;
    inanimate) names=("${INANIMATE[@]}") ;;
    *)
      echo "usage: $0 [animate|inanimate]" >&2
      exit 2
      ;;
  esac
  for index in "${!names[@]}"; do
    number=$((index + 1))
    one="20_stimuli/$block/obj_snds/_cleaned/snd_$number.wav"
    half="20_stimuli/$block/obj_snds/_cleaned_0p5/snd_$number.wav"
    if [ ! -f "$one" ] || [ ! -f "$half" ]; then
      echo "missing audio: $one or $half" >&2
      exit 1
    fi
    printf '\n%s (snd_%d) -> 1.0 s\n' "${names[index]}" "$number"
    play "$one"
    sleep 0.35
    printf '%s (snd_%d) -> 0.5 s\n' "${names[index]}" "$number"
    play "$half"
    sleep 0.6
  done
done
printf '\ndone\n'
