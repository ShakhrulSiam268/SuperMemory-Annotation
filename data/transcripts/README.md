# Transcript Files

This directory contains audio transcript sidecars for each de-identified
recording. Files are grouped by participant directory:

```text
data/transcripts/person_N/
```

Each recording can have two transcript JSON files.

## Whisper Transcripts

Files named:

```text
person_N_session_<id>_<date>_glasses_<device>_whisper_transcript.json
```

These are automatic Whisper/WhisperX transcript outputs. They provide
line-level timing and diarization labels from the audio model.

Typical fields:

```json
{
  "start": 18.862,
  "end": 19.323,
  "text": "A first.",
  "speaker": "SPEAKER_01"
}
```

The `speaker` values are automatic diarization labels. They are not guaranteed
to correspond to the person labels used in the dataset annotations.

## Gemini-Aligned Transcripts

Files named:

```text
person_N_session_<id>_<date>_glasses_<device>_gemini_aligned_transcript.json
```

These files align the caption-stage Gemini transcript to the Whisper timing
reference. Use these when you need transcript text that follows the curated
caption narration order and person attribution.

Gemini is treated as authoritative for:

- transcript text
- transcript order
- person labels such as `User`, `A`, `B`, etc.
- non-speech sound events, written in brackets

Whisper is used only as a timing reference. Because the available Whisper data
is line-level rather than word-level, some aligned timestamps are inferred from
nearby matches or caption segment boundaries.

Top-level structure:

```json
{
  "metadata": {
    "source": "gemini_caption_transcript_aligned_to_whisper",
    "timing_counts": {
      "whisper_exact_match": 0,
      "whisper_partial_match": 0,
      "interpolated_between_anchors": 0,
      "inferred_before_first_anchor": 0,
      "inferred_after_last_anchor": 0,
      "caption_segment_evenly_distributed": 0,
      "caption_segment_inferred": 0
    },
    "speaker_mapping": {}
  },
  "transcript": []
}
```

Each `transcript` entry has this shape:

```json
{
  "start": 18.862,
  "end": 19.323,
  "person": "D",
  "text": "A first.",
  "kind": "speech",
  "timing_source": "whisper_exact_match",
  "alignment_confidence": "high"
}
```

For non-speech sounds:

```json
{
  "start": 22.4,
  "end": 23.0,
  "person": null,
  "text": "[Papers rustle]",
  "kind": "sound",
  "timing_source": "caption_segment_inferred",
  "alignment_confidence": "low"
}
```

## Timing Fields

- `start`, `end`: seconds from the beginning of the recording.
- `timing_source`: how the timestamp was assigned.
- `alignment_confidence`: confidence in the timing assignment, not in the
  transcript text.

Timing source meanings:

- `whisper_exact_match`: Gemini text matched a Whisper line or subspan closely.
- `whisper_partial_match`: Gemini text partially matched one or more Whisper
  lines.
- `interpolated_between_anchors`: no direct match; timing was interpolated
  between neighboring matched lines.
- `inferred_before_first_anchor`: no direct match before the first matched line
  in the caption segment.
- `inferred_after_last_anchor`: no direct match after the last matched line in
  the caption segment.
- `caption_segment_evenly_distributed`: no Whisper anchor was available in the
  segment, so speech lines were distributed across the caption segment.
- `caption_segment_inferred`: sound-only or otherwise Gemini-only timing was
  inferred from the caption segment.

Confidence values:

- `high`: direct text match to Whisper timing.
- `medium`: partial text match to Whisper timing.
- `low`: inferred timing or boundary-clamped timing.

## Speaker Mapping Metadata

The `metadata.speaker_mapping` object records diagnostic votes between Gemini
person labels and Whisper diarization speakers. It is included for audit and
analysis only. Gemini `person` labels are not overwritten by Whisper speaker
labels.

## Recommended Use

- Use `*_gemini_aligned_transcript.json` for dataset tasks that need curated
  person labels, non-speech events, and caption-order transcript text.
- Use `*_whisper_transcript.json` when you need the raw automatic speech
  recognition output.
- Treat low-confidence aligned timings as approximate segment-level timing, not
  true word-level timing.
